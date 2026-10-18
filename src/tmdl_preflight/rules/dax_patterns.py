"""DAX shape rules that need no contract: D010 calc-dax-blocks-present,
D011 calc-item-blind-average, X001 cross-fact-multirow-key-join."""

from __future__ import annotations

import re

from ..dax import strip_comments
from .base import Context, Rule, Severity, Violation

_CALC_KINDS = ("partition_source", "calculation_item", "format_string_definition")


class CalcDaxBlocksPresentRule(Rule):
    id = "D010"
    name = "calc-dax-blocks-present"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {"enabled": True, "min_blocks": 1}
    description = (
        "Models built on field parameters and a format calculation group "
        "always carry calculated-table sources, calculation items or dynamic "
        "format strings. Finding none means the tables were lost or the "
        "layout changed under the parser, and every DAX check on those "
        "blocks would pass vacuously. Warns when fewer than min_blocks such "
        "blocks exist; the per-kind counts go to the report notes. Opt-in."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("enabled") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        floor = int(self.options.get("min_blocks", 1))
        for model in ctx.models:
            counts = {k: 0 for k in _CALC_KINDS}
            for block in model.dax_blocks():
                if block.kind in counts:
                    counts[block.kind] += 1
            key = ctx.model_key(model)
            ctx.notes.append(
                f"D010: {key}: " + ", ".join(f"{k} {v}" for k, v in counts.items())
            )
            if sum(counts.values()) < floor:
                out.append(self.violation(
                    "no calculated-table, calculation-item or format-string DAX blocks "
                    "found; the tables were lost or the TMDL layout changed under the "
                    "parser, so the checks on those blocks would pass vacuously.",
                    file=model.definition_path, obj=key,
                ))
        return out


class CalcItemBlindAverageRule(Rule):
    id = "D011"
    name = "calc-item-blind-average"
    severity = Severity.ERROR
    option_defaults = {
        "table": "z-Toggle Daily Calculation",
        "item": "Daily",
        "calendar": "__Calendar",
    }
    description = (
        "A 'Daily' calculation item that averages every measure per day turns "
        "ratios (CTR, ROAS, %) into a mean of daily ratios, silently off by a "
        "large factor. The item must classify measures by name (\"#\", \"/\", "
        "\" per \"), test additivity (SUMX + ISNUMBER) and average only "
        "additive measures over the calendar (AVERAGEX). Models without the "
        "calculation-group table are skipped."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        tname, item = self.options["table"], self.options["item"]
        calendar = self.options["calendar"].lower()
        for model in ctx.models:
            table = model.get_table(tname)
            if table is None:
                continue
            body = next((expr for name, expr, _line in table.calculation_items if name == item), None)
            if body is None:
                out.append(self.violation(
                    f"calculation group '{tname}' has no '{item}' item.",
                    file=table.file, obj=tname,
                ))
                continue
            low = body.lower()
            missing = []
            if not ("containsstring" in low and all(t in low for t in ('"#"', '"/"', '" per "'))):
                missing.append('name rules (CONTAINSSTRING on "#", "/" and " per ")')
            if not ("sumx" in low and "isnumber" in low and ("_additive" in low or "_dailysum" in low)):
                missing.append("an additivity test (SUMX and ISNUMBER into _additive/_dailySum)")
            if not ("averagex" in low and calendar in low):
                missing.append(f"an additive branch (AVERAGEX over {self.options['calendar']})")
            if missing:
                line = next((ln for name, _e, ln in table.calculation_items if name == item), None)
                out.append(self.violation(
                    f"the '{item}' calculation item of '{tname}' averages blindly: it lacks "
                    f"{'; '.join(missing)}, so ratio measures become a mean of daily ratios. "
                    f"Re-propagate the fixed item from the template.",
                    file=table.file, line=line, obj=f"{tname}[{item}]",
                ))
        return out


_TABLE_TOKEN = r"(?:'[^']*'|[A-Za-z_]\w*)"


class CrossFactMultirowKeyJoinRule(Rule):
    id = "X001"
    name = "cross-fact-multirow-key-join"
    severity = Severity.ERROR
    option_defaults = {"multi_row_keys": []}
    description = (
        "Some dimensions carry several rows per real-world entity (a page "
        "dimension grained by URL x domain x source). Two facts loaded from "
        "different sources key the same entity to different rows, so "
        "'A'[key] IN VALUES('B'[key]) intersects key spaces that never "
        "overlap: the measure returns blank and nothing errors. Lists the "
        "keys in multi_row_keys (empty by default: add a key only with "
        "row-count evidence); a comparison of the same table is not flagged."
    )

    def check(self, ctx: Context) -> list[Violation]:
        keys = list(self.options.get("multi_row_keys") or [])
        if not keys:
            return []
        out: list[Violation] = []
        for model in ctx.models:
            for f in sorted((model.definition_path / "tables").glob("*.tmdl")):
                if ctx.is_excluded(f):
                    continue
                try:
                    code = strip_comments(f.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeDecodeError):
                    continue
                for key in keys:
                    k = re.escape(key)
                    pattern = re.compile(
                        rf"(?P<left>{_TABLE_TOKEN})\s*\[\s*{k}\s*\]\s+IN\s+"
                        rf"(?:CALCULATETABLE\s*\(\s*)?VALUES\s*\(\s*(?P<right>{_TABLE_TOKEN})\s*\[\s*{k}\s*\]",
                        re.IGNORECASE,
                    )
                    for m in pattern.finditer(code):
                        left = m.group("left").strip("'")
                        right = m.group("right").strip("'")
                        if not left or not right or left.lower() == right.lower():
                            continue
                        line = code.count("\n", 0, m.start()) + 1
                        out.append(self.violation(
                            f"{f.name}:{line}: '{left}'[{key}] IN VALUES('{right}'[{key}]) "
                            f"joins two tables on multi-row key '{key}'; the key spaces do "
                            f"not overlap, so the measure silently returns blank. Compare "
                            f"natural-key sets (INTERSECT/EXCEPT over VALUES of the business "
                            f"key) instead.",
                            file=f, line=line, obj=f"{left}->{right}[{key}]",
                        ))
        return out
