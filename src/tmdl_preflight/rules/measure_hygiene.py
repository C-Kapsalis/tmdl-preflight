"""Measure visibility, folders, descriptions and filter coverage, plus the
required calculation-group tables. IDs C012 and O008-O015 (all opt-in: they
encode one team's naming conventions)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..categories import (
    MAPPING_TABLE,
    METRIC_AXIS_GLOBS,
    NON_ATTRIBUTING_GROUPS,
    FactTracer,
    axis_rows,
    category_map,
    load_mapping,
)
from ..edits import EditRefused, read_text_file, verified_write
from ..measure_classes import classify_measure_name, helper_subcategory, is_helper_name
from ..model import Measure, SemanticModel
from ..recognizers import _expression_end
from .base import Context, Rule, Severity, Violation


def _user_facing(m: Measure) -> bool:
    return not is_helper_name(m.name)


class RequiredCalcGroupsRule(Rule):
    id = "C012"
    name = "required-calc-groups"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {
        "format_selector": True,
        "time_intelligence_selector": True,
        "format_table": "z-Selector Format",
        "time_intelligence_table": "z-Selector Time Intelligence Function",
        "names": [],
    }
    description = (
        "The calculation-group tables the report's selectors rely on must "
        "exist (exact names): by default the format selector (z-Selector "
        "Format) and the time-intelligence selector (z-Selector Time "
        "Intelligence Function), each switchable, plus any names listed. "
        "Without them every visual that applies the selector loses its "
        "format or its time logic. All switches off skips the rule."
    )

    def _required(self) -> list[str]:
        out = []
        if self.options.get("format_selector"):
            out.append(self.options["format_table"])
        if self.options.get("time_intelligence_selector"):
            out.append(self.options["time_intelligence_table"])
        out += [n for n in self.options.get("names") or [] if n not in out]
        return out

    def disabled_by_policy(self) -> bool:
        return not self._required()

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for name in self._required():
                if model.get_table(name) is None:
                    out.append(self.violation(
                        f"required calculation-group table '{name}' is missing; copy it from "
                        f"the template.", file=model.definition_path / "tables", obj=name))
        return out


class IntermediaryHelperFolderRule(Rule):
    id = "O008"
    name = "intermediary-helper-folder"
    severity = Severity.WARNING
    opt_in = True
    description = (
        "Intermediary helper measures ('-Name') are building blocks other "
        "measures reuse; each needs a display folder so they stay grouped "
        "instead of cluttering the measure list."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for m in model.all_measures():
                c = classify_measure_name(m.name)
                if c.subcategory == "intermediary_helper" and not (m.display_folder or "").strip():
                    out.append(self.violation(
                        f"intermediary helper {m.full_name} has no displayFolder; give it one.",
                        file=m.file, line=m.line, obj=m.full_name))
        return out


ALWAYS_VISIBLE = [
    "f-All", "f-Slicer", "f-Matrix Title", "i-On-Plot Title", "i-On-Plot Subtitle",
    "i-HTML x/y Plot Specific", "i-HTML x/y Selector-2", "i-Applied Filters",
    "i-Selected Timeframe", "i-Selected Analysis Category", "i-Diagnostic Measures",
    "i-Tooltip", "i-Enhanced Timeframe", "i-Enhanced Timeframe HTML",
    "i-Selected Timeframe HTML",
]


class HelperMeasuresHiddenRule(Rule):
    id = "O009"
    name = "helper-measures-hidden"
    severity = Severity.WARNING
    opt_in = True
    fixable = True
    option_defaults = {"always_visible": list(ALWAYS_VISIBLE)}
    description = (
        "Helper measures (names classified as helpers) are plumbing and must "
        "be hidden, except the ones on the always_visible list that report "
        "pages bind directly. Auto-fix adds isHidden to the measure's "
        "property section."
    )

    def _offenders(self, ctx: Context):
        keep = set(self.options.get("always_visible") or [])
        for model in ctx.models:
            for m in model.all_measures():
                if is_helper_name(m.name) and not m.is_hidden and m.name not in keep:
                    yield m

    def check(self, ctx: Context) -> list[Violation]:
        return [self.violation(
            f"helper measure {m.full_name} ({helper_subcategory(m.name)}) is visible; hide it "
            f"(the auto-fix adds isHidden).", file=m.file, line=m.line, obj=m.full_name)
            for m in self._offenders(ctx)]

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        by_file: dict[Path, list[Measure]] = {}
        for m in self._offenders(ctx):
            by_file.setdefault(m.file, []).append(m)
        for path, measures in by_file.items():
            tf = read_text_file(path)
            lines = tf.lines()
            inserts = []
            for m in measures:
                decl = m.line - 1
                if decl >= len(lines) or not lines[decl].lstrip().startswith("measure"):
                    continue
                indent = lines[decl][: len(lines[decl]) - len(lines[decl].lstrip())]
                inserts.append((_expression_end(lines, decl) + 1, indent + "\t" + "isHidden", m))
            for at, text, _m in sorted(inserts, key=lambda x: x[0], reverse=True):
                lines.insert(at, text)

            def verify(old: str, new: str, n=len(inserts)) -> None:
                if len(new.split(tf.newline)) - len(old.split(tf.newline)) != n:
                    raise EditRefused("unexpected line count")

            try:
                verified_write(tf, tf.join(lines), verify)
            except EditRefused:
                continue
            applied.extend(f"{path.name}: hid {m.full_name}" for _a, _t, m in inserts)
        return applied


class UnusedHelperMeasuresRule(Rule):
    id = "O010"
    name = "unused-helper-measures"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"frequent_threshold": 5}
    description = (
        "Inventory (never fails): helper measures no expression in the model "
        "and no report file next to it references, and the most used "
        "helpers. Check the other models built from the same template before "
        "deleting one."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            helpers = sorted({m.name for m in model.all_measures() if is_helper_name(m.name)},
                             key=len, reverse=True)
            if not helpers:
                continue
            tmdl = "\n".join(p.read_text(encoding="utf-8-sig", errors="replace")
                             for p in model.definition_path.rglob("*.tmdl"))
            report_text = ""
            for rep in model.definition_path.parent.parent.glob("*.Report"):
                for p in rep.rglob("*"):
                    if p.is_file() and p.suffix in (".json", ".pbir", ".bim"):
                        report_text += "\n" + p.read_text(encoding="utf-8", errors="replace")
            counts: dict[str, int] = {}
            for name in helpers:  # longer names first so they claim their matches
                pat = re.escape(f"[{name}]")
                counts[name] = len(re.findall(pat, tmdl))
                tmdl = re.sub(pat, " ", tmdl)
                bare = len(re.findall(re.escape(name), report_text))
                report_text = report_text.replace(name, " ")
                counts[name] += bare
            unused = sorted(n for n, c in counts.items() if c == 0)
            frequent = sorted(n for n, c in counts.items() if c >= self.options["frequent_threshold"])
            if unused:
                out.append(self.violation(
                    f"unused in this model ({len(unused)}): {', '.join(unused)}",
                    file=model.definition_path, obj="unused"))
            if frequent:
                out.append(self.violation(
                    f"frequently used helpers ({len(frequent)}): {', '.join(frequent)}",
                    file=model.definition_path, obj="frequent"))
        return out


class UserFacingMeasureVisibleRule(Rule):
    id = "O011"
    name = "user-facing-measure-visible"
    severity = Severity.ERROR
    opt_in = True
    description = (
        "A measure whose name says it is for report authors (not a helper "
        "name) must not be hidden: hidden, it disappears from the field list "
        "and from Q&A. Either unhide it or rename it with a helper prefix; "
        "decide per measure."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for m in model.all_measures():
                c = classify_measure_name(m.name)
                if c.is_user_facing and not c.is_noise and m.is_hidden:
                    out.append(self.violation(
                        f"user-facing measure {m.full_name} is hidden; unhide it or give it a "
                        f"helper name.", file=m.file, line=m.line, obj=m.full_name))
        return out


class UserFacingDisplayFolderRule(Rule):
    id = "O012"
    name = "user-facing-display-folder"
    severity = Severity.INFO
    opt_in = True
    description = (
        "Advisory: user-facing measures without a display folder, with the "
        "folder coverage of the model."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            facing = [m for m in model.all_measures() if _user_facing(m)]
            missing = [m for m in facing if not (m.display_folder or "").strip()]
            if missing:
                pct = 100.0 * (len(facing) - len(missing)) / len(facing)
                out.append(self.violation(
                    f"{len(missing)} of {len(facing)} user-facing measures have no display folder "
                    f"({pct:.0f}% covered): {', '.join(m.full_name for m in missing)}",
                    file=model.definition_path, obj="display-folders"))
        return out


class UserFacingMeasureDescriptionRule(Rule):
    id = "O013"
    name = "user-facing-measure-description"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"enabled": True, "min_length": 10}
    description = (
        "Advisory: user-facing measures (by name, hidden or not) whose /// "
        "description is missing or shorter than min_length characters "
        "(default 10). enabled = false skips the rule."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("enabled") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        floor = int(self.options["min_length"])
        for model in ctx.models:
            facing = [m for m in model.all_measures() if _user_facing(m)]
            missing = [m for m in facing if len((m.description or "").strip()) < floor]
            if missing:
                out.append(self.violation(
                    f"{len(missing)} of {len(facing)} user-facing measures lack a description of "
                    f"at least {floor} characters: {', '.join(m.full_name for m in missing)}",
                    file=model.definition_path, obj="descriptions"))
        return out


class TableDescriptionCoverageRule(Rule):
    id = "O014"
    name = "table-description-coverage"
    severity = Severity.INFO
    opt_in = True
    description = "Advisory: how many tables carry a /// description."

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            tables = model.table_list
            described = sum(1 for t in tables if (t.description or "").strip())
            pct = 100.0 * described / len(tables) if tables else 0.0
            out.append(self.violation(
                f"{described} of {len(tables)} tables have a description ({pct:.0f}%)",
                file=model.definition_path, obj="table-descriptions"))
        return out


_SENSORS = ("ISFILTERED", "ISINSCOPE", "ISEMPTY", "ISCROSSFILTERED", "HASONEVALUE", "HASONEFILTER")


def _strip_dax_comments(text: str) -> str:
    out, i, n = [], 0, len(text)
    quote: Optional[str] = None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if text.startswith(("--", "//"), i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _sensor_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in re.finditer(r"\b(" + "|".join(_SENSORS) + r")\s*\(", text, re.IGNORECASE):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        spans.append((m.end(), i))
    return spans


def reads_data(expression: str, fact: str) -> bool:
    """True when ``fact`` is read outside a sensor function (ISEMPTY, ...)."""
    text = _strip_dax_comments(expression or "")
    spans = _sensor_spans(text)
    pats = [re.escape("'" + fact.replace("'", "''") + "'")]
    if re.fullmatch(r"[A-Za-z_]\w*", fact):
        pats.append(r"(?<![\w'\[])" + re.escape(fact) + r"(?![\w'])")
    for pat in pats:
        for m in re.finditer(pat, text):
            if not any(a <= m.start() < b for a, b in spans):
                return True
    return False


class FactTableFilterCoverageRule(Rule):
    id = "O015"
    name = "fact-table-filter-coverage"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"filter_prefix": "f-", "mapping_table": MAPPING_TABLE,
                       "axis_globs": list(METRIC_AXIS_GLOBS)}
    description = (
        "Every fact table a user-facing measure reads (directly or through "
        "other measures) must also be read by some visual-filter measure "
        "(f- prefix); otherwise visual-level filters never narrow that "
        "fact's rows. Facts reached only through the analysis-category "
        "mechanism (an axis measure whose group maps to a category) are "
        "exempt. pbip-forge can write the missing filter measure."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        prefix = self.options["filter_prefix"]
        for model in ctx.models:
            tracer = FactTracer(model)
            consumers: dict[str, list[str]] = {}
            covered: set[str] = set()
            for m in model.all_measures():
                facts = tracer.trace(m.name)
                if m.name.startswith(prefix):
                    covered |= facts
                elif _user_facing(m):
                    for f in facts:
                        consumers.setdefault(f, []).append(m.name)
            uncovered = sorted(set(consumers) - covered)
            if uncovered:
                uncovered = [f for f in uncovered if not self._exempt(model, f, consumers[f], tracer)]
            for f in uncovered:
                names = ", ".join(sorted(set(consumers[f])))
                table = model.get_table(f)
                out.append(self.violation(
                    f"fact table {f} is read by user-facing measures ({names}) but by no {prefix} "
                    f"filter measure, so visual filters never narrow its rows. Add a filter "
                    f"measure (pbip-forge can write int(not ISEMPTY('{f}'))).",
                    file=table.file if table else model.definition_path, obj=f))
        return out

    def _exempt(self, model: SemanticModel, fact: str, consumers: list[str],
                tracer: FactTracer) -> bool:
        """Is the fact gated through the analysis-category mechanism?

        The forge's gap-fill planner decides this the same way: an x-row
        measure with a mapped group that reads the fact DIRECTLY (a data
        read, not only inside a sensor) means the fact is already gated, so
        no f- measure is owed. The x-row measure must be user-facing; a
        helper on an x row is the model's own business.
        """
        mapping = load_mapping(model, name=self.options["mapping_table"])
        if mapping is None:
            return False
        cmap = category_map(mapping.rows, NON_ATTRIBUTING_GROUPS)
        for row in axis_rows(model, self.options["axis_globs"]):
            if not cmap.get(row.group or ""):
                continue
            m = tracer.by_name.get(row.target)
            if m is None or not _user_facing(m):
                continue
            if reads_data(m.expression, fact):
                return True
        return False
