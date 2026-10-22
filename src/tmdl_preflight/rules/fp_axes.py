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
                    f"field-parameter tuples carry {widths[0]} field(s) but the table "
                    f"declares {declared} column(s) (Value1..Value{declared}) — "
                    f"mismatch breaks compilation.",
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
        family = pattern.replace(" {n}", "")
        lo, hi = (list(fam.get("range") or [1, 9]) + [9])[:2]
        levels: "OrderedDict[int, tuple[Table, set[str]]]" = OrderedDict()
        for n in range(int(lo), int(hi) + 1):
            table = model.get_table(pattern.replace("{n}", str(n)))
            tf = _read(table) if table is not None else None
            if tf is not None:
                levels[n] = (table, nameof_targets(tf.text))
        out: list[Violation] = []
        if not levels:
            return out
        union: set[str] = set().union(*(t for _tb, t in levels.values()))
        if len(levels) >= 2:
            for target in sorted(union):
                have = [n for n, (_tb, t) in levels.items() if target in t]
                lack = [n for n, (_tb, t) in levels.items() if target not in t]
                if not lack:
                    continue
                first = levels[lack[0]][0]
                out.append(self.violation(
                    f"NAMEOF({target}) in {family} {','.join(map(str, have))} "
                    f"but MISSING from {family} {','.join(map(str, lack))}",
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
                for target in extra:
                    out.append(self.violation(
                        f"{table.name}: NAMEOF({target}) absent from every numbered "
                        f"{family} level",
                        file=table.file, obj=f"{table.name}:{target}",
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
    option_defaults = {"families": [{"globs": ["y-Selector *", "y-Plot Specific *"]}],
                        "curated_categories": [], "category_position": 4}
    description = (
        "A display name must carry the same category (row value 4) in every "
        "sibling table of a field-parameter family. Retagging a row in some "
        "siblings and not others makes consumers that read different "
        "siblings disagree on what a category holds. The default family is "
        "the numbered y-Selector tables together with the y-Plot Specific "
        "tables. Restricted to curated_categories when set; commented and "
        "bracket-labelled rows are ignored. Configure a family as "
        "{globs: [glob, ...]}. Use 'tmdl-preflight fieldparam retag' to "
        "retag all siblings at once."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        curated = set(self.options.get("curated_categories") or [])
        pos = int(self.options.get("category_position") or 4) - 1
        for model in ctx.models:
            for fam in self.options.get("families") or []:
                out.extend(self._family(model, fam, curated, pos))
        return out

    def _family(self, model: SemanticModel, fam, curated: set[str],
                pos: int) -> list[Violation]:
        globs = fam.get("globs") if isinstance(fam, dict) else [fam]
        tables: list[Table] = []
        for glob in globs or []:
            tables.extend(_matching(model, [str(glob)]))
        seen: "OrderedDict[str, list[tuple[Table, Row, str]]]" = OrderedDict()
        for table in tables:
            for row in live_rows(table):
                if len(row.fields) <= pos:
                    continue
                label, cat = _label(row.fields[0]), _label(row.fields[pos])
                if label is None or cat is None or (curated and cat not in curated):
                    continue
                seen.setdefault(label, []).append((table, row, cat))
        out: list[Violation] = []
        for label, entries in seen.items():
            first = entries[0][2]
            other = next((e for e in entries if e[2] != first), None)
            if other is None:
                continue
            table, row, cat = other
            out.append(self.violation(
                f"{label} is {cat} in {table.file.name} but {first} in a sibling table",
                file=table.file, line=row.index + 1, obj=label,
            ))
        return out


class RetagIncomplete(RuntimeError):
    pass


def _retag_hits(lines: list[str], names: list[str], old: str, pos: int) -> "OrderedDict[str, Row]":
    """The first live row of each requested name whose category is ``old``,
    in the order the rows occur in the file."""
    hits: "OrderedDict[str, Row]" = OrderedDict()
    for row in read_rows(lines):
        if not is_live_row(row) or len(row.fields) <= pos:
            continue
        label = _label(row.fields[0])
        if label is None or label not in names or label in hits:
            continue
        if _label(row.fields[pos]) != old:
            continue
        hits[label] = row
    return hits


def retag_rows(files: list[Path], names: list[str], old: str, new: str,
               position: int = 4) -> list[str]:
    """Change the category of the first live row named N under ``old`` to
    ``new``, for each N, in EVERY file; all or nothing across ``files``."""
    pos = position - 1
    loaded = [read_text_file(Path(f)) for f in files]
    lines = [tf.lines() for tf in loaded]
    edits: dict[tuple[int, int], tuple[int, int]] = {}
    order: list[str] = []
    for fi, ls in enumerate(lines):
        hits = _retag_hits(ls, names, old, pos)
        missing = [n for n in names if n not in hits]
        if missing:
            where = f" in {Path(files[fi]).name}" if len(files) > 1 else ""
            raise RetagIncomplete(
                f"field-parameter retag incomplete: {sorted(missing)!r} not found "
                f"under category {old!r}{where}")
        if fi == 0:
            order = list(hits)
        for label, row in hits.items():
            edits[(fi, row.index)] = field_spans(row.text, row.open_at, row.close_at)[pos]
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
    return order


# ---------------------------------------------------------------------------
# F011 category value required
# ---------------------------------------------------------------------------

# The report each axis family prints when one of its rows carries no
# category: the count, the rows, and the categories a row may use.
_FAMILY_REPORT = {
    "x": {
        "categories": "Valid categories: Performance_x, analytics_api_x, kplanner_x, etc.",
        "example": 'Example: ("Cost", NAMEOF([!Cost]), -10, "Performance_x")',
    },
    "y": {
        "categories": "Valid categories: Campaign_y, Ad_Group_y, Keyword_y, Landing_Page_y, etc.",
        "example": ('Example: ("Campaign Name", NAMEOF(\'_Campaigns\'[Campaign Actual]), '
                    '-10, "campaign_universal_y", "Other")'),
    },
}

_ORDER_RE = re.compile(r"^\s*-?\d+\s*$")


def _family_label(glob: str) -> str:
    """The family a glob names: its text before the first number or bracket."""
    head = re.split(r"[\[0-9]", glob, maxsplit=1)[0]
    return head.strip() or glob.strip()


def _table_number(name: str) -> int:
    tail = name.rsplit(" ", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _family_report(family: str, kind: str, rows: list[tuple[str, str]],
                   n_tables: int) -> str:
    """The report block of one axis family."""
    text = _FAMILY_REPORT[kind]
    lines: list[str] = []
    if kind == "y":
        lines.append(f"{family} Field Parameter Validation:")
        lines.append(f"Tables analyzed: {n_tables}")
    lines.append(f"Found {len(rows)} {family} entries without category (4th parameter)")
    if kind == "x":
        lines.append(f"All {family} field parameters must have 4th parameter "
                     f"(category_x_id)")
    lines.append("")
    for table, label in rows:
        lines.append(f'  - {table}: "{label}"')
    lines.append("")
    lines.append(text["categories"])
    lines.append(text["example"])
    return "\n".join(lines)


class FieldParameterCategoryRequiredRule(Rule):
    id = "F011"
    name = "fieldparam-category-required"
    severity = Severity.ERROR
    option_defaults = {"category_tables": ["x-Selector [1-9]", "y-Selector [1-9]"],
                       "require_category": True}
    description = (
        "In the numbered axis tables (x-Selector N, y-Selector N) value 4 of "
        "each row is its analysis category. A 3-value row (label, NAMEOF, "
        "order) belongs to no category and never appears under any analysis "
        "(unless the same label also has a categorised row). The report "
        "lists the rows without a category, family by family. "
        "require_category = false skips the rule."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("require_category") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for glob in self.options["category_tables"]:
                out.extend(self._family(model, str(glob)))
        return out

    def _family(self, model: SemanticModel, glob: str) -> list[Violation]:
        family = _family_label(glob)
        kind = "y" if family[:1].lower() == "y" else "x"
        tables = sorted(_matching(model, [glob]), key=lambda t: (_table_number(t.name), t.name))
        rows: list[tuple[str, str]] = []
        first: Optional[tuple[Table, Row]] = None
        for table in tables:
            live = live_rows(table)
            categorised = {_label(r.fields[0]) for r in live if len(r.fields) >= 4}
            for row in live:
                if len(row.fields) != 3:
                    continue
                label = _label(row.fields[0])
                if label is None or label in categorised:
                    continue
                if not _ORDER_RE.match(row.fields[2]):
                    continue
                rows.append((table.name, label))
                if first is None:
                    first = (table, row)
        if not rows:
            return []
        table, row = first
        return [self.violation(
            _family_report(family, kind, rows, len(tables)),
            file=table.file, line=row.index + 1,
        )]


# ---------------------------------------------------------------------------
# F012 axis coverage (info)
# ---------------------------------------------------------------------------

# The coverage summary, one line per count, in the columns the audit report
# has always used.
_COVERAGE_SUMMARY = (
    "x-Selector — measure level:\n"
    "  x-Selector measure count:                  {axis}\n"
    "  User-facing measures (total):          {user_facing}\n"
    "  Covered in x-Selector:                     {covered} ({percent}%)\n"
    "  Uncovered (not in any x-Selector):         {uncovered}\n"
    "\n"
    "y-Selector — dim-table level:\n"
    "  y-Selector dim tables referenced:          {dim_refs}\n"
    "  `_` dim tables in model (total):       {dim_total}\n"
    "  Dim tables in model not in y-Selector:     {dim_hidden}\n"
    "  y-Selector refs to missing tables:         {dim_missing}"
)


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
        "table that does not exist. The report opens with the counts of the "
        "audit and then lists what it found."
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
            out.extend(self._model(model))
        return out

    def _model(self, model: SemanticModel) -> list[Violation]:
        where = model.definition_path / "tables"
        on_axis = {m for _t, _q, m in self._refs(model, self.options["metric_axis_globs"])}
        measures = list(model.all_measures())
        user_facing = [m for m in measures if not is_helper_name(m.name)]
        uncovered = [m for m in user_facing if m.name not in on_axis]
        hidden = [m for m in measures if is_helper_name(m.name) and m.name in on_axis]
        dim_refs = self._refs(model, self.options["dimension_axis_globs"])
        dim_tables = {q for _t, q, _m in dim_refs if q}
        prefix = self.options["dimension_prefix"]
        dim_hidden = sorted(t.name for t in model.table_list
                            if t.name.startswith(prefix) and t.name not in dim_tables)
        known = {t.name for t in model.table_list}
        dim_missing = sorted(dim_tables - known)
        covered = len(user_facing) - len(uncovered)
        percent = (covered / len(user_facing) * 100) if user_facing else 100.0
        summary = _COVERAGE_SUMMARY.format(
            axis=len(on_axis), user_facing=len(user_facing), covered=covered,
            percent=f"{percent:.1f}", uncovered=len(uncovered),
            dim_refs=len(dim_tables), dim_total=sum(1 for t in model.table_list
                                                    if t.name.startswith(prefix)),
            dim_hidden=len(dim_hidden), dim_missing=len(dim_missing),
        )
        lists = [
            (f"User-facing measures not in x-Selector ({len(uncovered)}):",
             sorted(uncovered, key=lambda m: m.name),
             lambda m: f"{m.table}[{m.name}]"),
            (f"Helper-named measures present in x-Selector ({len(hidden)}):", hidden,
             lambda m: f"{m.table}[{m.name}]"),
            ("`_` dim tables in model not exposed on y-Selector:", dim_hidden,
             lambda t: t),
            ("y-Selector references tables that don't exist:", dim_missing,
             lambda t: t),
        ]
        out = [self.violation(summary, file=where)]
        for heading, items, render in lists:
            if not items:
                continue
            body = "\n".join([heading] + [f"  - {render(i)}" for i in items])
            out.append(self.violation(body, file=where))
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

_MODE_RE = re.compile(r"^\s*mode:\s*(import|directQuery)\b", re.IGNORECASE | re.MULTILINE)
_TUPLE_RE = re.compile(r'\(\s*"(?:[^"]|"")*"\s*,\s*NAMEOF\b', re.IGNORECASE)
_FENCED_SOURCE_RE = re.compile(r"source\s*=\s*```(.*?)```", re.DOTALL)


class FieldParameterPartitionShapeRule(Rule):
    id = "F015"
    name = "field-parameter-partition-shape"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"axis_globs": ["x-Selector [1-9]", "y-Selector [1-9]"],
                       "validate_field_parameter_pattern": True}
    description = (
        "Advisory shape check of the numbered axis tables: an import-mode "
        "calculated partition whose fenced source lists (\"label\", "
        "NAMEOF(...), ...) tuples. A DirectQuery or unknown mode, or a source "
        "without such tuples, means the table is not the field parameter the "
        "axis visuals expect. validate_field_parameter_pattern = false skips "
        "the rule."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("validate_field_parameter_pattern") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for table in _matching(model, self.options["axis_globs"]):
                tf = _read(table)
                if tf is None:
                    out.append(self.violation(f"'{table.name}': no partition (file unreadable)",
                                              file=table.file, obj=table.name))
                    continue
                m = _MODE_RE.search(tf.text)
                mode = m.group(1) if m else "unknown"
                if mode.lower() != "import":
                    out.append(self.violation(
                        f"'{table.name}' partition mode is {mode}, not import; axis field "
                        f"parameters are import-mode calculated tables.",
                        file=table.file, obj=table.name))
                    continue
                body = _FENCED_SOURCE_RE.search(tf.text)
                if body is None or not _TUPLE_RE.search(body.group(1)):
                    out.append(self.violation(
                        f"'{table.name}' source has no (\"label\", NAMEOF(...), ...) tuple "
                        f"(no tuple pattern); it is not a field parameter.",
                        file=table.file, obj=table.name))
        return out
