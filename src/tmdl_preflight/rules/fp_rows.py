"""Field-parameter row hygiene over whole files: F001 comma runs, F004
ragged rows (with a fixer), F006 duplicate rows, F007 family consistency."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

from ..dax import collapse_comma_runs, find_comma_runs, insert_missing_row_separators
from ..edits import EditRefused, TextFile, read_text_file, verified_write
from ..fieldparams import (
    AXIS_GLOBS,
    Row,
    axis_tables,
    comma_runs,
    drop_offsets,
    expected_width,
    field_parameter_files,
    identity,
    nameof_parts,
    read_rows,
    rows_alone,
    split_fields,
)
from ..model import SemanticModel, Table
from .base import Context, Rule, Severity, Violation


def _lines_of(table: Table) -> Optional[TextFile]:
    try:
        return read_text_file(table.file)
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# F001
# ---------------------------------------------------------------------------


class FieldParameterCommaRunsRule(Rule):
    id = "F001"
    name = "fieldparam-comma-runs"
    severity = Severity.ERROR
    fixable = True
    option_defaults = {"axis_globs": list(AXIS_GLOBS)}
    description = (
        "Field-parameter files (and every other calculated-table source) "
        "must not contain stray structural commas: two or more commas "
        "separated only by whitespace, typically left behind when a row was "
        "removed but its separator was not. In a field-parameter file the "
        "whole file is scanned (rows, calculated columns). Observed in Power "
        "BI Desktop: the model still opens, but every visual that uses the "
        "field parameter fails ('Error fetching data for this visual. Failed "
        "to move the data reader to the next row.'). Commas inside comments "
        "and string literals are exempt. Auto-fix keeps each run's first "
        "comma and deletes the orphans."
    )

    def _targets(self, ctx: Context):
        """``(table, file text, first line offset or None)``: whole files of
        field parameters, partition sources of other calculated tables."""
        for model in ctx.models:
            fp = {t.name for t in field_parameter_files(model, self.options.get("axis_globs"))}
            for t in model.table_list:
                if t.name in fp:
                    yield t, None
                else:
                    for p in t.partitions:
                        if p.kind == "calculated" and p.source:
                            yield t, p

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for table, part in self._targets(ctx):
            if part is None:
                tf = _lines_of(table)
                if tf is None:
                    continue
                found = [(line, len(offs)) for line, offs in comma_runs(tf.text.replace("\r\n", "\n"))]
                where, base = table.file, 1
            else:
                found = find_comma_runs(part.source)
                where, base = part.file, part.source_start_line or part.line
            for line, orphans in found:
                out.append(self.violation(
                    f"stray comma run ({orphans} orphan comma(s)) in calculated partition "
                    f"source. Power BI Desktop still opens the model, but every visual "
                    f"that uses this table fails ('Error fetching data for this visual'). "
                    f"Delete the orphan comma(s) (the auto-fix does).",
                    file=where, line=base + line - 1,
                    obj=f"{table.name} (partition source)",
                ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        done: set[Path] = set()
        for table, part in list(self._targets(ctx)):
            if part is not None:
                if find_comma_runs(part.source) and part.source_start_line and part.source_end_line:
                    applied.extend(_collapse_range(part.file, part.source_start_line,
                                                   part.source_end_line, table.name))
                continue
            if table.file in done:
                continue
            done.add(table.file)
            tf = _lines_of(table)
            if tf is None:
                continue
            runs = comma_runs(tf.text)
            surplus = [o for _line, offs in runs for o in offs]
            if not surplus:
                continue
            new = drop_offsets(tf.text, surplus)

            def verify(old: str, new_text: str) -> None:
                if old.replace(",", "") != new_text.replace(",", ""):
                    raise EditRefused("comma-run repair changed more than commas")
                if comma_runs(new_text):
                    raise EditRefused("comma runs remain")

            try:
                if verified_write(tf, new, verify):
                    applied.append(f"{table.file.name}: removed {len(surplus)} orphan comma(s) "
                                   f"from '{table.name}'")
            except EditRefused:
                continue
        return applied


def _collapse_range(file: Path, start: int, end: int, table_name: str) -> list[str]:
    tf = read_text_file(file)
    lines = tf.lines()
    lo, hi = start - 1, min(end, len(lines))
    block = tf.join(lines[lo:hi])
    new_block, removed = collapse_comma_runs(block)
    if not removed:
        return []
    lines[lo:hi] = new_block.split(tf.newline)

    def verify(old: str, new: str) -> None:
        if old.replace(",", "") != new.replace(",", ""):
            raise EditRefused("comma-run repair changed more than commas")

    try:
        verified_write(tf, tf.join(lines), verify)
    except EditRefused:
        return []
    return [f"{file.name}: removed {removed} orphan comma(s) from '{table_name}' partition source"]


# ---------------------------------------------------------------------------
# F004
# ---------------------------------------------------------------------------


class RaggedRowWidthRule(Rule):
    id = "F004"
    name = "fieldparam-ragged-rows"
    severity = Severity.ERROR
    fixable = True
    option_defaults = {"axis_globs": list(AXIS_GLOBS), "marker_padded": "AUTO-PADDED",
                       "marker_realigned": "AUTO-REALIGNED"}
    description = (
        "Every row of a field-parameter table must have the same number of "
        "values; the engine refuses to build the table otherwise ('Each tuple "
        "in table constructor must have the same number of columns'). The "
        "expected width is the most common one. Auto-fix pads a short row "
        "with the most common value of each missing position, or drops the "
        "one value of a long row no other row uses, and leaves two review "
        "comments above every edited row; an ambiguous long row is left for "
        "a human."
    )

    def _tables(self, model: SemanticModel) -> list[Table]:
        return field_parameter_files(model, self.options.get("axis_globs"))

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in self._tables(model):
                tf = _lines_of(t)
                if tf is None:
                    continue
                rows = read_rows(tf.lines())
                want = expected_width(rows)
                if want is None:
                    continue
                counts = Counter(len(r.fields) for r in rows)
                summary = ", ".join(f"{counts[w]} row(s) with {w}" for w in sorted(counts))
                for r in rows:
                    if len(r.fields) != want:
                        out.append(self.violation(
                            f"row {r.fields[0]} has {len(r.fields)} value(s) where the table's "
                            f"rows have {want} ({summary}); the engine refuses a constructor "
                            f"with uneven rows.",
                            file=t.file, line=r.index + 1, obj=f"{t.name} (partition source)",
                        ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for t in self._tables(model):
                tf = _lines_of(t)
                if tf is None:
                    continue
                lines = tf.lines()
                rows = read_rows(lines)
                want = expected_width(rows)
                if want is None:
                    continue
                good = [r for r in rows if len(r.fields) == want]
                edits = 0
                alone = rows_alone(rows)
                for r in sorted((r for r in alone if len(r.fields) != want), key=lambda r: -r.index):
                    new = self._repair(r, want, good)
                    if new is None:
                        continue
                    row_text, notes = new
                    lines[r.index:r.index + 1] = [r.indent + n for n in notes] + [row_text]
                    edits += 1
                if not edits:
                    continue

                def verify(old: str, new_text: str) -> None:
                    after = read_rows(new_text.split(tf.newline))
                    if len(after) != len(rows):
                        raise EditRefused("row repair changed the number of rows")

                try:
                    if verified_write(tf, tf.join(lines), verify):
                        applied.append(f"{t.file.name}: repaired {edits} ragged row(s)")
                except EditRefused:
                    continue
        return applied

    def _repair(self, r: Row, want: int, good: list[Row]) -> Optional[tuple[str, list[str]]]:
        if len(r.fields) < want:
            fills = []
            for pos in range(len(r.fields), want):
                values = Counter(g.fields[pos] for g in good)
                if not values:
                    return None
                top = max(values.values())
                fills.append((pos + 1, next(g.fields[pos] for g in good if values[g.fields[pos]] == top)))
            head = r.text[: r.close_at].rstrip()
            text = head + "".join(f", {v}" for _p, v in fills) + " " + r.text[r.close_at:]
            what = "; ".join(f"position {p} filled with {v}" for p, v in fills)
            return text, [
                f"-- {self.options['marker_padded']}: {what} (most frequent value in this column).",
                "-- Review needed: confirm this filled value is right for this row.",
            ]
        used = {g.fields[k] for g in good for k in range(3, len(g.fields))}
        candidates = [k for k in range(3, len(r.fields)) if r.fields[k] not in used]
        if len(candidates) != 1:
            return None
        k = candidates[0]
        kept = [f for i, f in enumerate(r.fields) if i != k]
        text = r.text[: r.open_at] + "( " + ", ".join(kept) + " )" + r.text[r.close_at + 1:]
        return text, [
            f"-- {self.options['marker_realigned']}: position {k + 1} (value {r.fields[k]}) "
            f"dropped; no other row uses it.",
            "-- Review needed: if the value belongs to another position, move it back by hand.",
        ]


# ---------------------------------------------------------------------------
# F006 duplicate rows
# ---------------------------------------------------------------------------

_DUP_ROW_RE = re.compile(
    r'\(\s*("(?:[^"]|"")*"|\[[^\]]*\])\s*,\s*NAMEOF\s*\(((?:[^()]|\([^()]*\))*)\)\s*,'
    r'\s*(-?\d+)\s*,\s*("(?:[^"]|"")*")((?:\s*,\s*"(?:[^"]|"")*")*)\s*\)'
)


class FieldParameterDuplicateRowsRule(Rule):
    id = "F006"
    name = "fieldparam-duplicate-rows"
    severity = Severity.ERROR
    fixable = True
    option_defaults = {"axis_globs": list(AXIS_GLOBS)}
    description = (
        "Two rows of an axis field parameter that agree on every field "
        "(label, NAMEOF target, order, group and the remaining values) list "
        "the same choice twice in the slicer. Rows that differ in group or "
        "order are distinct. Auto-fix keeps the first copy and removes later "
        "copies with exactly the same text; a copy written differently (the "
        "last row, without its comma) stays and keeps being reported."
    )

    @staticmethod
    def _groups(text: str):
        groups: dict[tuple, list] = {}
        for m in _DUP_ROW_RE.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            before = text[line_start:m.start()]
            if "//" in before or "--" in before:
                continue
            extra = tuple(x.strip() for x in re.findall(r'"(?:[^"]|"")*"', m.group(5)))
            key = (m.group(1), re.sub(r"\s+", " ", m.group(2).strip()), int(m.group(3)),
                   m.group(4), extra)
            groups.setdefault(key, []).append(m)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in axis_tables(model, self.options.get("axis_globs")):
                tf = _lines_of(t)
                if tf is None:
                    continue
                for key, matches in self._groups(tf.text).items():
                    first = matches[0]
                    out.append(self.violation(
                        f"row ({key[0]}, NAMEOF({key[1]}), {key[2]}, {key[3]}) appears "
                        f"{len(matches)} times; the slicer lists the choice more than once.",
                        file=t.file, line=tf.text.count("\n", 0, first.start()) + 1,
                        obj=f"{t.name}[{key[0]}]",
                    ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for t in axis_tables(model, self.options.get("axis_globs")):
                tf = _lines_of(t)
                if tf is None:
                    continue
                text = tf.text
                removed = 0
                for _key, matches in self._groups(text).items():
                    survivor = matches[0]
                    piece = survivor.group(0)
                    if text[survivor.end():survivor.end() + 1] == ",":
                        piece += ","
                    pos = survivor.end()
                    while True:
                        hit = text.find(piece, pos + 1)
                        if hit < 0:
                            break
                        ls = text.rfind("\n", 0, hit) + 1
                        le = text.find("\n", hit + len(piece))
                        le = len(text) if le < 0 else le
                        if not text[ls:hit].strip() and not text[hit + len(piece):le].strip():
                            text = text[:ls] + text[le + 1:]
                        else:
                            text = text[:hit] + text[hit + len(piece):]
                        removed += 1
                if not removed:
                    continue
                try:
                    if verified_write(tf, text):
                        applied.append(f"{t.file.name}: removed {removed} duplicate row(s)")
                except EditRefused:
                    continue
        return applied


# ---------------------------------------------------------------------------
# F007 family consistency
# ---------------------------------------------------------------------------

_DATE_WORD_RE = re.compile(r"\bdate\b", re.IGNORECASE)


class _Family:
    def __init__(self, model: SemanticModel, axis: str, plot: str):
        self.numbered: list[Table] = []
        self.ps1: Optional[Table] = None
        self.ps2: Optional[Table] = None
        for t in sorted(model.table_list, key=lambda t: t.name):
            m = re.fullmatch(re.escape(axis) + r" (\d+)", t.name)
            if m:
                self.numbered.append(t)
                continue
            m = re.fullmatch(re.escape(plot) + r" (\d+)", t.name)
            if m:
                if m.group(1) == "1":
                    self.ps1 = t
                elif self.ps2 is None:
                    self.ps2 = t


class FieldParameterFamilyConsistencyRule(Rule):
    id = "F007"
    name = "fieldparam-family-consistency"
    severity = Severity.ERROR
    fixable = True
    option_defaults = {
        "axes": [["x-Selector", "x-Plot Specific"], ["y-Selector", "y-Plot Specific"]],
        "excluded_word": "date",
        "marker_removed": "AUTO-REMOVED", "marker_promoted": "AUTO-PROMOTED",
        "marker_added": "AUTO-ADDED",
    }
    description = (
        "The numbered tables of an axis family (x-Selector 1, 2, ...) must "
        "offer the same fields, so a field does not vanish when a report "
        "swaps slots. On the x axis the second plot-specific table belongs to "
        "the group but must not carry a 'date' field; the first plot-specific "
        "table may offer a subset, never a field the family lacks. Fields are "
        "identified by their NAMEOF target (a measure by name alone). "
        "Auto-fix comments out date rows, promotes plot-specific-only rows "
        "into the first numbered table, copies missing rows, and annotates "
        "every edit."
    )

    def _families(self, model: SemanticModel):
        for axis, plot in self.options.get("axes") or []:
            fam = _Family(model, axis, plot)
            if len(fam.numbered) >= 2:
                yield axis, fam

    def _analyse(self, model: SemanticModel, axis: str, fam: _Family):
        measures = {m.name for m in model.all_measures()}
        word = re.compile(rf"\b{re.escape(self.options['excluded_word'])}\b", re.IGNORECASE)
        rows: dict[str, list[Row]] = {}
        for t in fam.numbered + [x for x in (fam.ps1, fam.ps2) if x]:
            tf = _lines_of(t)
            rows[t.name] = read_rows(tf.lines()) if tf else []
        group = list(fam.numbered) + ([fam.ps2] if fam.ps2 and axis.startswith("x") else [])
        family: dict[str, tuple[str, Row]] = {}
        for t in sorted(group, key=lambda t: t.name):
            for r in rows[t.name]:
                if len(r.fields) > 1:
                    family.setdefault(identity(r.fields[1], measures), (t.name, r))
        missing, dates, unique = [], [], []
        for t in group:
            have = {identity(r.fields[1], measures) for r in rows[t.name] if len(r.fields) > 1}
            for ident, (owner, r) in family.items():
                if ident in have:
                    continue
                if fam.ps2 is not None and t is fam.ps2 and word.search(nameof_parts(r.fields[1])[1]):
                    continue
                missing.append((t, ident, owner, r))
        if fam.ps2 is not None and axis.startswith("x"):
            for r in rows[fam.ps2.name]:
                if len(r.fields) > 1 and word.search(nameof_parts(r.fields[1])[1]):
                    dates.append((fam.ps2, r))
        if fam.ps1 is not None:
            for r in rows[fam.ps1.name]:
                if len(r.fields) > 1 and identity(r.fields[1], measures) not in family:
                    unique.append((fam.ps1, r))
        return missing, dates, unique

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for axis, fam in self._families(model):
                missing, dates, unique = self._analyse(model, axis, fam)
                for t, ident, owner, _r in missing:
                    out.append(self.violation(
                        f"{t.name} is missing {ident}, which {owner} offers; the field "
                        f"vanishes when a report swaps to this slot.",
                        file=t.file, obj=f"{t.name}:{ident}",
                    ))
                for t, r in dates:
                    out.append(self.violation(
                        f"{t.name} carries the date field {r.fields[1]}; the second "
                        f"plot-specific table must not offer date fields.",
                        file=t.file, line=r.index + 1, obj=f"{t.name}:{r.fields[1]}",
                    ))
                for t, r in unique:
                    out.append(self.violation(
                        f"{t.name} offers {r.fields[1]}, which no {axis} table offers.",
                        file=t.file, line=r.index + 1, obj=f"{t.name}:{r.fields[1]}",
                    ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for axis, fam in self._families(model):
                for step in ("dates", "unique", "missing"):
                    ctx.reload()
                    model = next(m for m in ctx.models
                                 if m.definition_path == model.definition_path)
                    fam = _Family(model, axis, dict(self.options["axes"])[axis])
                    missing, dates, unique = self._analyse(model, axis, fam)
                    if step == "dates":
                        for t, r in dates:
                            if self._comment_out(t, r):
                                applied.append(f"{t.file.name}: commented out date row {r.fields[0]}")
                    elif step == "unique":
                        for t, r in unique:
                            target = fam.numbered[0]
                            if self._insert(target, r, [
                                f"-- {self.options['marker_promoted']}: copied from {t.name}, the "
                                f"only table that offered it.",
                                "-- Review needed: confirm the field belongs to the whole family.",
                            ]):
                                applied.append(f"{target.file.name}: promoted {r.fields[0]} from {t.name}")
                    else:
                        for t, ident, owner, r in missing:
                            if self._insert(t, r, [f"-- {self.options['marker_added']}: copied from {owner}."]):
                                applied.append(f"{t.file.name}: added {r.fields[0]} from {owner}")
        return applied

    @staticmethod
    def _comment_out(t: Table, r: Row) -> bool:
        tf = read_text_file(t.file)
        lines = tf.lines()
        rows = read_rows(lines)
        target = next((x for x in rows if x.index == r.index and x.text == r.text), None)
        if target is None:
            return False
        if not target.trailing_comma:
            prev = [x for x in rows if x.index < target.index]
            if prev and prev[-1].trailing_comma:
                p = prev[-1]
                cut = p.text.index(",", p.close_at)
                lines[p.index] = p.text[:cut] + p.text[cut + 1:]
        lines[target.index:target.index + 1] = [
            f"{target.indent}-- AUTO-REMOVED: date field {target.fields[1]} removed from the "
            f"second plot-specific table.",
            f"{target.indent}-- Review needed: was: {target.text.strip()}",
        ]
        try:
            return verified_write(tf, tf.join(lines))
        except EditRefused:
            return False

    @staticmethod
    def _insert(t: Table, r: Row, notes: list[str]) -> bool:
        tf = read_text_file(t.file)
        lines = tf.lines()
        rows = read_rows(lines)
        if not rows:
            return False
        widths = Counter(len(x.fields) for x in rows)
        if len(r.fields) != max(widths, key=lambda w: widths[w]):
            return False
        try:
            order = int(r.fields[2])
        except (IndexError, ValueError):
            order = None
        at = None
        if order is not None:
            for x in rows:
                try:
                    if int(x.fields[2]) > order:
                        at = x.index
                        break
                except (IndexError, ValueError):
                    continue
        indent = rows[0].indent
        body = r.text.strip()
        body = body[:-1].rstrip() if body.endswith(",") else body
        if at is None:
            at = rows[-1].index + 1
        new_lines = lines[:at] + [indent + n for n in notes] + [indent + body] + lines[at:]
        text, _n = insert_missing_row_separators(tf.join(new_lines))
        try:
            return verified_write(tf, text)
        except EditRefused:
            return False
