"""Axis field-parameter tables: arity, categories, levels, retags, coverage
and the selector branches that call measures. IDs F008-F014, M020."""

from __future__ import annotations

import re
from collections import OrderedDict
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterable, Optional

from ..dax import extract_nameof_references
from ..edits import EditRefused, TextFile, read_text_file, verified_write
from ..fieldparams import (
    AXIS_GLOBS,
    Row,
    field_parameter_files,
    field_spans,
    is_live_row,
    read_rows,
)
from ..measure_classes import is_helper_name
from ..model import SemanticModel, Table
from ..recognizers import nameof_targets
from .base import Context, Rule, Severity, Violation

_VALUE_COL_RE = re.compile(r"sourceColumn:\s*\[Value(\d+)\]")


def _read(table: Table) -> Optional[TextFile]:
    try:
        return read_text_file(table.file)
    except (OSError, UnicodeDecodeError):
        return None


def _matching(model: SemanticModel, globs: Iterable[str]) -> list[Table]:
    pats = list(globs)
    return [t for t in model.table_list if any(fnmatchcase(t.name, p) for p in pats)]


def _label(field: str) -> Optional[str]:
    field = field.strip()
    if len(field) >= 2 and field[0] == field[-1] == '"':
        return field[1:-1].replace('""', '"')
    return None


def live_rows(table: Table) -> list[Row]:
    tf = _read(table)
    if tf is None:
        return []
    return [r for r in read_rows(tf.lines()) if is_live_row(r)]


# ---------------------------------------------------------------------------
# F008 declared arity
# ---------------------------------------------------------------------------


class FieldParameterArityRule(Rule):
    id = "F008"
    name = "fieldparam-arity"
    severity = Severity.ERROR
    option_defaults = {"axis_globs": list(AXIS_GLOBS)}
    description = (
        "Every row of a field parameter must be as wide as the table's "
        "declared columns (the highest sourceColumn [ValueN]). When all rows "
        "agree with each other but not with the declared columns (a custom "
        "column was dropped while its per-row value stayed, or added without "
        "one), the calculated table does not compile and every visual bound "
        "to it breaks. Rows of mixed widths are F004's finding. Commas inside "
        "quoted labels are not separators. Not auto-fixable: only the author "
        "knows which value is wrong."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for table in field_parameter_files(model, self.options.get("axis_globs")):
                tf = _read(table)
                if tf is None:
                    continue
                declared = max((int(n) for n in _VALUE_COL_RE.findall(tf.text)), default=0)
                rows = [r for r in read_rows(tf.lines()) if is_live_row(r)]
                widths = sorted({len(r.fields) for r in rows})
                if not declared or len(widths) != 1 or widths[0] == declared:
                    continue
                out.append(self.violation(
                    f"every row of '{table.name}' has {widths[0]} values, but the table "
                    f"declares {declared} columns (Value1..Value{declared}); the calculated "
                    f"table will not compile. Add or remove the column, or fix the rows.",
                    file=table.file, line=rows[0].index + 1, obj=table.name,
                ))
        return out


# ---------------------------------------------------------------------------
# F009 drilldown levels agree
# ---------------------------------------------------------------------------

_DEFAULT_FAMILIES = [{"levels": "y-Selector {n}", "range": [1, 9],
                      "subset": "y-Plot Specific *", "placeholder_table": "#Report Measures"}]


class FieldParameterLevelConsistencyRule(Rule):
    id = "F009"
    name = "fieldparam-level-consistency"
    severity = Severity.ERROR
    option_defaults = {"families": [dict(f) for f in _DEFAULT_FAMILIES]}
    description = (
        "Numbered drilldown levels of one field-parameter family (y-Selector "
        "1, 2, ...) each hold their own copy of the dimension list. They must "
        "reference identical sets of NAMEOF targets, or a dimension is offered "
        "at some drill depths and vanishes at others. The family's subset "
        "tables (y-Plot Specific *) may only use targets the levels offer; "
        "rows pointing at the placeholder table are exempt. Configure "
        "families as {levels: 'name {n}', range: [lo, hi], subset: glob, "
        "placeholder_table: name}."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for fam in self.options.get("families") or []:
                out.extend(self._family(model, fam))
        return out

    def _family(self, model: SemanticModel, fam: dict) -> list[Violation]:
        pattern = str(fam.get("levels") or "")
        lo, hi = (list(fam.get("range") or [1, 9]) + [9])[:2]
        levels: "OrderedDict[str, tuple[Table, set[str]]]" = OrderedDict()
        for n in range(int(lo), int(hi) + 1):
            table = model.get_table(pattern.replace("{n}", str(n)))
            tf = _read(table) if table is not None else None
            if tf is not None:
                levels[table.name] = (table, nameof_targets(tf.text))
        out: list[Violation] = []
        if not levels:
            return out
        union: set[str] = set().union(*(t for _tb, t in levels.values()))
        if len(levels) >= 2:
            for target in sorted(union):
                have = [name for name, (_tb, t) in levels.items() if target in t]
                lack = [name for name, (_tb, t) in levels.items() if target not in t]
                if not lack:
                    continue
                first = levels[lack[0]][0]
                out.append(self.violation(
                    f"dimension {target} is missing from {', '.join(lack)} (present in "
                    f"{', '.join(have)}), so it disappears at those drilldown levels. Add "
                    f"the row to every level, or remove it from all of them.",
                    file=first.file, obj=f"{first.name}:{target}",
                ))
        placeholder = str(fam.get("placeholder_table") or "").replace("'", "").lower()
        sub = fam.get("subset")
        if sub:
            for table in _matching(model, [str(sub)]):
                tf = _read(table)
                if tf is None:
                    continue
                extra = sorted(t for t in nameof_targets(tf.text) - union
                               if not (placeholder and t.startswith(placeholder)))
                if extra:
                    out.append(self.violation(
                        f"'{table.name}' is not a subset of the {pattern.replace(' {n}', '')} "
                        f"levels: it adds {', '.join(extra)}, which no level offers. Register "
                        f"the dimension in the levels first, or drop the row.",
                        file=table.file, obj=table.name,
                    ))
        return out


# ---------------------------------------------------------------------------
# F010 retag consistency (and the retag command)
# ---------------------------------------------------------------------------


class FieldParameterRetagRule(Rule):
    id = "F010"
    name = "fieldparam-retag"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"families": ["y-Selector *"], "curated_categories": [], "category_position": 4}
    description = (
        "A display name must carry the same category (row value 4) in every "
        "sibling table of a field-parameter family. Retagging a row in some "
        "siblings and not others makes consumers that read different "
        "siblings disagree on what a category holds. Restricted to "
        "curated_categories when set; commented and bracket-labelled rows are "
        "ignored. Use 'tmdl-preflight fieldparam retag' to retag all siblings "
        "at once."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        curated = set(self.options.get("curated_categories") or [])
        pos = int(self.options.get("category_position") or 4) - 1
        for model in ctx.models:
            for glob in self.options.get("families") or []:
                tables = _matching(model, [glob])
                seen: "OrderedDict[str, OrderedDict[str, set[str]]]" = OrderedDict()
                for table in tables:
                    for row in live_rows(table):
                        if len(row.fields) <= pos:
                            continue
                        label, cat = _label(row.fields[0]), _label(row.fields[pos])
                        if label is None or cat is None or (curated and cat not in curated):
                            continue
                        seen.setdefault(label, OrderedDict()).setdefault(table.name, set()).add(cat)
                for label, per_table in seen.items():
                    if len(per_table) < 2 or len({frozenset(c) for c in per_table.values()}) == 1:
                        continue
                    detail = "; ".join(f"{t}: {', '.join(sorted(c))}" for t, c in per_table.items())
                    first = model.get_table(next(iter(per_table)))
                    out.append(self.violation(
                        f"\"{label}\" carries different categories across the '{glob}' "
                        f"family ({detail}); finish the retag in every sibling "
                        f"(tmdl-preflight fieldparam retag).",
                        file=first.file if first else None, obj=f"{glob}:{label}",
                    ))
        return out


class RetagIncomplete(RuntimeError):
    pass


def retag_rows(files: list[Path], names: list[str], old: str, new: str,
               position: int = 4) -> list[str]:
    """Change the category of the first live row named N under ``old`` to
    ``new``, for each N; all or nothing across ``files``."""
    pos = position - 1
    loaded = [read_text_file(Path(f)) for f in files]
    lines = [tf.lines() for tf in loaded]
    edits: dict[tuple[int, int], tuple[int, int]] = {}
    done: list[str] = []
    for name in names:
        hit = None
        for fi, ls in enumerate(lines):
            for row in read_rows(ls):
                if not is_live_row(row) or len(row.fields) <= pos:
                    continue
                if (fi, row.index) in edits:
                    continue
                if _label(row.fields[0]) == name and _label(row.fields[pos]) == old:
                    hit = (fi, row)
                    break
            if hit:
                break
        if hit is None:
            continue
        fi, row = hit
        edits[(fi, row.index)] = field_spans(row.text, row.open_at, row.close_at)[pos]
        done.append(name)
    missing = [n for n in names if n not in done]
    if missing:
        raise RetagIncomplete(
            f"retag incomplete: no live row under category \"{old}\" for "
            f"{', '.join(missing)}; nothing was written")
    literal = '"' + new.replace('"', '""') + '"'
    for (fi, idx), (s, e) in edits.items():
        ln = lines[fi][idx]
        lines[fi][idx] = ln[:s] + literal + ln[e:]
    for fi, tf in enumerate(loaded):
        if any(k[0] == fi for k in edits):
            def verify(o: str, n: str) -> None:
                if len(o.split("\n")) != len(n.split("\n")):
                    raise EditRefused("line count changed")
            verified_write(tf, tf.join(lines[fi]), verify)
    return done


# ---------------------------------------------------------------------------
# F011 category value required
# ---------------------------------------------------------------------------


class FieldParameterCategoryRequiredRule(Rule):
    id = "F011"
    name = "fieldparam-category-required"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"category_tables": ["x-Selector [1-9]", "y-Selector [1-9]"],
                       "require_category": True}
    description = (
        "In the numbered axis tables (x-Selector N, y-Selector N) value 4 of "
        "each row is its analysis category. A 3-value row (label, NAMEOF, "
        "order) belongs to no category and never appears under any analysis "
        "(unless the same label also has a categorised row). "
        "require_category = false skips the rule."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("require_category") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for table in _matching(model, self.options["category_tables"]):
                rows = live_rows(table)
                full = {_label(r.fields[0]) for r in rows if len(r.fields) >= 4}
                for r in rows:
                    label = _label(r.fields[0])
                    if len(r.fields) != 3 or label is None or label in full:
                        continue
                    out.append(self.violation(
                        f"row \"{label}\" of '{table.name}' has no category (value 4), so it "
                        f"appears under no analysis category; add the category.",
                        file=table.file, line=r.index + 1, obj=f"{table.name}[{label}]",
                    ))
        return out


# ---------------------------------------------------------------------------
# F012 axis coverage (info)
# ---------------------------------------------------------------------------


class FieldParameterCoverageRule(Rule):
    id = "F012"
    name = "fieldparam-coverage"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"metric_axis_globs": ["x-Selector*", "x-Plot Specific*"],
                       "dimension_axis_globs": ["y-Selector*", "y-Plot Specific*"],
                       "dimension_prefix": "_"}
    description = (
        "Advisory audit of what the axis field parameters expose: user-facing "
        "measures on no metric axis, helper measures that are on one, "
        "dimension tables on no dimension axis, and axis rows that name a "
        "table that does not exist."
    )

    @staticmethod
    def _refs(model: SemanticModel, globs) -> list[tuple[Table, Optional[str], str]]:
        out = []
        for t in _matching(model, globs):
            for p in t.partitions:
                if p.kind == "calculated" and p.source:
                    out.extend((t, q, m) for q, m, _ln in extract_nameof_references(p.source))
        return out

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            where = model.definition_path / "tables"
            on_axis = {m for _t, _q, m in self._refs(model, self.options["metric_axis_globs"])}
            measures = sorted({m.name for m in model.all_measures()})
            lists = [
                ("user-facing measures on no metric axis",
                 [m for m in measures if not is_helper_name(m) and m not in on_axis]),
                ("helper measures on a metric axis",
                 [m for m in measures if is_helper_name(m) and m in on_axis]),
            ]
            dim_refs = self._refs(model, self.options["dimension_axis_globs"])
            dim_tables = {q for _t, q, _m in dim_refs if q}
            prefix = self.options["dimension_prefix"]
            lists.append(("dimension tables on no dimension axis",
                          sorted(t.name for t in model.table_list
                                 if t.name.startswith(prefix) and t.name not in dim_tables)))
            missing = sorted({f"{t.name} -> {q}" for t, q, _m in dim_refs
                              if q and model.find_table(q) is None})
            lists.append(("axis rows referencing a missing table", missing))
            for title, items in lists:
                if items:
                    out.append(self.violation(f"{title} ({len(items)}): {', '.join(items)}",
                                              file=where, obj=title))
        return out


# ---------------------------------------------------------------------------
# F013 no measures on axis tables
# ---------------------------------------------------------------------------


class FieldParameterNoMeasuresRule(Rule):
    id = "F013"
    name = "field-parameter-table-no-measures"
    severity = Severity.ERROR
    option_defaults = {"axis_globs": list(AXIS_GLOBS)}
    description = (
        "Field-parameter (axis selector) tables are regenerated from their "
        "row list; a measure parked on one is lost the next time the table "
        "is rebuilt from the template, breaking everything that calls it. "
        "Move the measure to a measures table (and update qualified "
        "references)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for table in field_parameter_files(model, self.options.get("axis_globs")):
                if not table.measure_list:
                    continue
                names = ", ".join(m.name for m in table.measure_list)
                out.append(self.violation(
                    f"field-parameter table '{table.name}' declares "
                    f"{len(table.measure_list)} measure(s) ({names}); they are lost when "
                    f"the table is regenerated. Move them to a measures table.",
                    file=table.file, line=table.measure_list[0].line, obj=table.name,
                ))
        return out


# ---------------------------------------------------------------------------
# M020 calculated columns have an expression
# ---------------------------------------------------------------------------


class CalculatedColumnExpressionRule(Rule):
    id = "M020"
    name = "calculated-column-expression-present"
    severity = Severity.ERROR
    description = (
        "A column declared with '=' is a calculated column and needs an "
        "expression. 'column X =' followed directly by its properties "
        "declares a calculated column with no definition, which the engine "
        "rejects. Write the expression or drop the '='."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for col in model.all_columns():
                if col.expression is not None and not col.expression.strip():
                    out.append(self.violation(
                        f"calculated column {col.full_name} is declared with '=' but has an "
                        f"empty expression; write the expression or remove the '='.",
                        file=col.file, line=col.line, obj=col.full_name,
                    ))
        return out


# ---------------------------------------------------------------------------
# F014 selector branches call existing measures
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(
    r"""(?:^\s*|[=,(]\s*)"(?:'(?:[^']|'')+'|[A-Za-z_][\w .]*)\[[^\]"]+\]\"""")
_CALL_RE = re.compile(r"(?<![\w'\]])\[([^\]]+)\]")


def selector_branch_calls(lines: list[str], measures: set[str]) -> list[tuple[int, str]]:
    """``(0-based line, name)`` of each unresolved ``[X]`` called in the
    result part of a selector branch line; parked lines are exempt."""
    out = []
    for idx, line in enumerate(lines):
        if line.lstrip().startswith(("--", "//")):
            continue
        key = _KEY_RE.search(line)
        if not key:
            continue
        for m in _CALL_RE.finditer(line, key.end()):
            name = m.group(1)
            if name.replace('""', '"').lower() not in measures:
                out.append((idx, name))
    return out


def _has_branch(lines: list[str]) -> bool:
    return any(_KEY_RE.search(ln) and not ln.lstrip().startswith(("--", "//")) for ln in lines)


class SelectorBranchResolutionRule(Rule):
    id = "F014"
    name = "selector-branch-resolution"
    severity = Severity.ERROR
    fixable = True
    description = (
        "A selector measure maps the selected field-parameter key "
        "(\"'Table'[object]\") to a measure call, as a SWITCH branch. When a "
        "measure is deleted its axis rows go but the branch keeps calling "
        "it; the containing measure then fails when the model is processed, "
        "so refresh and deployment are rejected. Every bare [X] in the "
        "result part of a branch must name an existing measure; keys and "
        "commented (parked) branches are never judged. Auto-fix deletes the "
        "dangling branch lines (and a comma left before a closing "
        "parenthesis)."
    )

    def _findings(self, model: SemanticModel):
        measures = {m.name.lower() for m in model.all_measures()}
        for table in model.table_list:
            tf = _read(table)
            if tf is None:
                continue
            calls = selector_branch_calls(tf.lines(), measures)
            if calls:
                yield table, tf, calls

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for table, _tf, calls in self._findings(model):
                for idx, name in calls:
                    out.append(self.violation(
                        f"selector branch calls [{name}], which is no measure in the model; "
                        f"the measure holding the branch fails when the model is processed. "
                        f"Delete the branch (the auto-fix does) or restore the measure.",
                        file=table.file, line=idx + 1, obj=f"{table.name}:[{name}]",
                    ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for table, tf, calls in list(self._findings(model)):
                dead = sorted({idx for idx, _n in calls})
                lines = tf.lines()
                keep = [ln for i, ln in enumerate(lines) if i not in set(dead)]
                # positions (in ``keep``) right after each removed run
                cuts = sorted({i - sum(1 for d in dead if d < i) for i in dead})
                for cut in cuts:
                    above = cut - 1
                    while above >= 0 and (not keep[above].strip() or keep[above].lstrip().startswith(("--", "//"))):
                        above -= 1
                    below = cut
                    while below < len(keep) and (not keep[below].strip() or keep[below].lstrip().startswith(("--", "//"))):
                        below += 1
                    if above >= 0 and below < len(keep) and keep[above].rstrip().endswith(",") \
                            and keep[below].lstrip().startswith(")"):
                        keep[above] = keep[above].rstrip()[:-1]

                def verify(old: str, new: str) -> None:
                    measures = {m.name.lower() for m in model.all_measures()}
                    if selector_branch_calls(new.split(tf.newline), measures):
                        raise EditRefused("dangling branch still present")

                try:
                    verified_write(tf, tf.join(keep), verify)
                except EditRefused:
                    continue
                applied.append(f"{table.file.name}: removed {len(dead)} dangling selector "
                               f"branch(es)")
        return applied


# ---------------------------------------------------------------------------
# F015 axis partition shape (advisory)
# ---------------------------------------------------------------------------

_MODE_RE = re.compile(r"mode:\s*(import|directQuery)\b", re.IGNORECASE)
_TUPLE_RE = re.compile(r'\(\s*"[^"]+"\s*,\s*NAMEOF')
_FENCED_SOURCE_RE = re.compile(r"source\s*=\s*```(.*?)```", re.DOTALL)
#: the unfenced M source: after the ``source =`` line, up to the next
#: partition-level keyword or the next top-level block
_UNFENCED_SOURCE_RE = re.compile(
    r"source\s*=\s*\n(.+?)(?=\n\s*(?:annotation|changedProperty|queryGroup|mode)\b"
    r"|\n(?:column|partition|table|measure|calculationGroup)\b|\Z)", re.DOTALL)
_PARTITION_RE = re.compile(r"^\s*partition\s+\S", re.MULTILINE)
#: the calculated tables the partition-coverage inventory looks at
CALCULATED_TABLE_PATTERNS = ("x-Selector", "y-Selector", "z-Map", "z-Selector")


def _partition_mode(text: str) -> str:
    """The partition mode a file declares, lower-cased; 'unknown' when it
    declares none."""
    m = _MODE_RE.search(text)
    return m.group(1).lower() if m else "unknown"


class FieldParameterPartitionShapeRule(Rule):
    id = "F015"
    name = "field-parameter-partition-shape"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"axis_globs": ["x-Selector [1-9]", "y-Selector [1-9]"],
                       "validate_field_parameter_pattern": True}
    description = (
        "Advisory shape check of the numbered axis tables: an import-mode "
        "calculated partition whose source lists (\"label\", NAMEOF(...), ...) "
        "tuples. A DirectQuery or unknown mode, or a source without such "
        "tuples, means the table is not the field parameter the axis visuals "
        "expect. The run also reports, per model, how many axis tables were "
        "analysed and how many of the calculated tables carry a partition. "
        "validate_field_parameter_pattern = false skips the rule."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("validate_field_parameter_pattern") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            issues: list[tuple[str, str]] = []
            analyzed = 0
            for table in _matching(model, self.options["axis_globs"]):
                analyzed += 1
                tf = _read(table)
                if tf is None or not _PARTITION_RE.search(tf.text):
                    issues.append((table.name, "No partition found"))
                    continue
                mode = _partition_mode(tf.text)
                if mode != "import":
                    issues.append((table.name,
                                   f"Partition mode is '{mode}', expected 'import'"))
                    continue
                source = self._source(tf.text)
                if not _TUPLE_RE.search(source):
                    issues.append((table.name,
                                   "Source does not follow tuple pattern with NAMEOF"))
            ctx.notes.append(self._summary(analyzed, issues))
            ctx.notes.append(self._coverage(model))
            for name, issue in issues:
                table = model.get_table(name)
                out.append(self.violation(f"{name}: {issue}",
                                           file=table.file if table else model.definition_path,
                                           obj=name))
        return out

    @staticmethod
    def _source(text: str) -> str:
        """The partition's source: the fenced body, or the unfenced M that
        follows the ``source =`` line."""
        fenced = _FENCED_SOURCE_RE.search(text)
        if fenced:
            return fenced.group(1).strip()
        unfenced = _UNFENCED_SOURCE_RE.search(text)
        return unfenced.group(1).strip() if unfenced else ""

    @staticmethod
    def _summary(analyzed: int, issues: list[tuple[str, str]]) -> str:
        """The per-model summary of the partition-pattern check."""
        out = [
            "",
            "📊 Field Parameter Partition Pattern Validation:",
            f"Tables analyzed: {analyzed}",
            f"Valid partitions: {analyzed - len(issues)}",
            f"Violations: {len(issues)}",
        ]
        if issues:
            out.append("")
            out.append("⚠️  Partition pattern issues:")
            for name, issue in issues:
                out.append(f"  - {name}: {issue}")
            out.append("")
            out.append("Expected pattern: partition = calculated, mode: import, tuple source")
        else:
            out.append("✓ All field parameter tables follow standard partition pattern")
        return "\n".join(out)

    @staticmethod
    def _coverage(model) -> str:
        """The per-model inventory of the calculated tables' partitions."""
        tables = [t for t in model.table_list
                  if any(p in t.name for p in CALCULATED_TABLE_PATTERNS)]
        total = len(tables)
        with_partition = [t for t in tables if t.partitions]
        without = [t for t in tables if not t.partitions]
        pct = (len(with_partition) / total * 100) if total else 100.0
        out = [
            "",
            "📊 Calculated Table Partition Coverage:",
            f"Total calculated tables: {total}",
            f"With partitions: {len(with_partition)} ({pct:.1f}%)",
            f"Without partitions: {len(without)}",
        ]
        modes: dict[str, int] = {}
        for table in with_partition:
            mode = _partition_mode(_read(table).text if _read(table) else "")
            modes[mode] = modes.get(mode, 0) + 1
        if modes:
            out.append("")
            out.append("Partition modes:")
            for mode, count in sorted(modes.items()):
                out.append(f"  - {mode}: {count}")
        if without:
            out.append("")
            out.append("💡 Tables without partitions:")
            for table in without:
                out.append(f"  - {table.name}")
        else:
            out.append("✓ All calculated tables have partition definitions")
        return "\n".join(out)
