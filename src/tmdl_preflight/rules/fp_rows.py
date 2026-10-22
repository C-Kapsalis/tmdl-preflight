"""Field-parameter row hygiene over whole files: F001 comma runs, F004
ragged rows (with a fixer), F006 duplicate rows, F007 family consistency."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

from ..dax import (
    collapse_comma_runs,
    find_comma_runs,
    insert_missing_row_separators,
    remove_trailing_row_commas,
)
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
    no_axis_files_note,
    read_rows,
    rows_alone,
    source_span,
    split_fields,
)
from ..model import SemanticModel, Table
from .base import Context, Rule, Severity, Violation


def _lines_of(table: Table) -> Optional[TextFile]:
    try:
        return read_text_file(table.file)
    except (OSError, UnicodeDecodeError):
        return None


#: What Power BI Desktop does with a field-parameter table whose source does
#: not parse (observed on the Windows bench, 2026-10-18).
DESKTOP_COMMA = (
    "Power BI Desktop still opens the model, but every visual that uses this "
    "table fails ('Error fetching data for this visual')."
)


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
        for model in ctx.models:
            note = no_axis_files_note(model)
            if note:
                ctx.notes.append(note)
        for table, part in self._targets(ctx):
            if part is None:
                tf = _lines_of(table)
                if tf is None:
                    continue
                found = [(line, len(offs)) for line, offs in comma_runs(tf.text.replace("\r\n", "\n"))]
                where, base = table.file, 1
                obj = f"{table.name} (field-parameter file)"
                place = ""
            else:
                found = find_comma_runs(part.source)
                where, base = part.file, part.source_start_line or part.line
                obj = f"{table.name} (partition source)"
                place = " in calculated partition source"
            for line, orphans in found:
                out.append(self.violation(
                    f"{orphans} orphan comma(s){place}. {DESKTOP_COMMA} "
                    f"Delete the orphan comma(s) (the auto-fix does).",
                    file=where, line=base + line - 1, obj=obj,
                ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        done: set[Path] = set()
        total = 0
        touched: set[Path] = set()
        for table, part in list(self._targets(ctx)):
            if part is not None:
                if find_comma_runs(part.source) and part.source_start_line and part.source_end_line:
                    removed = _collapse_range(part.file, part.source_start_line,
                                             part.source_end_line)
                    if removed:
                        applied.append(f"{part.file.name}: removed {removed} orphan comma(s)")
                        total += removed
                        touched.add(part.file)
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
                    applied.append(f"{table.file.name}: removed {len(surplus)} orphan comma(s)")
                    total += len(surplus)
                    touched.add(table.file)
            except EditRefused:
                continue
        if total:
            ctx.blocks.append(
                f"Removed {total} orphan comma(s) across {len(touched)} file(s). Commit "
                f"the changes and re-sync the affected workspace(s).")
        return applied


def _collapse_range(file: Path, start: int, end: int) -> int:
    tf = read_text_file(file)
    lines = tf.lines()
    lo, hi = start - 1, min(end, len(lines))
    block = tf.join(lines[lo:hi])
    new_block, removed = collapse_comma_runs(block)
    if not removed:
        return 0
    lines[lo:hi] = new_block.split(tf.newline)

    def verify(old: str, new: str) -> None:
        if old.replace(",", "") != new.replace(",", ""):
            raise EditRefused("comma-run repair changed more than commas")

    try:
        verified_write(tf, tf.join(lines), verify)
    except EditRefused:
        return 0
    return removed


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
                for r in rows:
                    if len(r.fields) != want:
                        out.append(self.violation(
                            f"{r.fields[0]} has {len(r.fields)} fields, norm is {want}",
                            file=t.file, line=r.index + 1, obj=f"{t.name} (partition source)",
                        ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            realigned = padded = long_left = 0
            for t in self._tables(model):
                tf = _lines_of(t)
                if tf is None:
                    continue
                lines = tf.lines()
                rows = read_rows(tf.lines())
                want = expected_width(rows)
                if want is None:
                    continue
                good = [r for r in rows if len(r.fields) == want]
                edits = 0
                alone = rows_alone(rows)
                for r in sorted((r for r in alone if len(r.fields) != want), key=lambda r: -r.index):
                    kind, row_text, notes, report = self._repair(r, want, good)
                    if kind in ("pad", "realign"):
                        lines[r.index:r.index + 1] = [r.indent + n for n in notes] + [row_text]
                        edits += 1
                        padded += kind == "pad"
                        realigned += kind == "realign"
                    elif kind == "ambiguous":
                        long_left += 1
                    if report:
                        applied.append(f"{t.file.name}:{r.index + 1}: {report}")
                if not edits:
                    continue

                def verify(old: str, new_text: str) -> None:
                    after = read_rows(new_text.split(tf.newline))
                    if len(after) != len(rows):
                        raise EditRefused("row repair changed the number of rows")

                try:
                    verified_write(tf, tf.join(lines), verify)
                except EditRefused:
                    continue
            if realigned:
                ctx.blocks.append(
                    f"  ⚠ {realigned} row(s) AUTO-REALIGNED under "
                    f"{model.definition_path} by removing the field whose value appears\n"
                    f"    nowhere else in the table's grouping columns. The removed value "
                    f"is named in a\n"
                    f"    '{self.options['marker_realigned']}' comment beside each row — a BI "
                    f"developer must confirm it did not belong.")
            if padded:
                ctx.blocks.append(
                    f"  ⚠ {padded} row(s) AUTO-PADDED with modal values under "
                    f"{model.definition_path}.\n"
                    f"    Each padded row carries a '{self.options['marker_padded']}' comment "
                    f"in the TMDL.\n"
                    f"    These values were chosen automatically — a BI developer must\n"
                    f"    confirm each one is the right grouping for that row.")
            if long_left:
                ctx.blocks.append(
                    f"  ✗ {long_left} over-long row(s) left untouched: the surplus field "
                    f"could not be identified.\n"
                    f"    An over-long row IS realigned when exactly one of its grouping "
                    f"values appears nowhere\n"
                    f"    else in the table — that one is the interloper. Here two or more "
                    f"values are unique to\n"
                    f"    the row (or none are), so there is no basis to pick. Widen the "
                    f"table's columns or fix\n"
                    f"    the row by hand. The gate stays red until then — a ragged tuple "
                    f"stops the whole\n"
                    f"    calculated table from compiling.")
        return applied

    def _repair(self, r: Row, want: int, good: list[Row]):
        """What to do with one ragged row.

        Returns ``(kind, row text, comment lines, report line)``. ``kind`` is
        ``"pad"``, ``"realign"``, ``"no_modal"`` or ``"ambiguous"``; the last
        two leave the row alone but still say so.
        """
        label = r.fields[0] if r.fields else "?"
        if len(r.fields) < want:
            fills = []
            for pos in range(len(r.fields), want):
                values = Counter(g.fields[pos] for g in good)
                if not values:
                    return ("no_modal", None, [],
                            f"{label} has {len(r.fields)} fields (norm {want}) but no modal "
                            f"value could be derived — skipped.")
                top = max(values.values())
                fills.append((pos + 1, next(g.fields[pos] for g in good
                                           if values[g.fields[pos]] == top)))
            head = r.text[: r.close_at].rstrip()
            text = head + "".join(f", {v}" for _p, v in fills) + " " + r.text[r.close_at:]
            shown = ", ".join(f"field {p} set to {v}" for p, v in fills)
            notes = [
                f"-- {self.options['marker_padded']}: {shown} (modal value of this column).",
                "-- A BI developer MUST confirm this is correct for this row.",
            ]
            return ("pad", text, notes,
                    f"{label} padded {len(r.fields)} -> {want} ({shown}) — ANNOTATED IN "
                    f"PLACE, needs BI review.")
        used = {g.fields[k] for g in good for k in range(3, len(g.fields))}
        candidates = [k for k in range(3, len(r.fields)) if r.fields[k] not in used]
        if len(candidates) != 1:
            values = ", ".join(r.fields[3:])
            return ("ambiguous", None, [],
                    f"{label} has {len(r.fields)} fields (norm {want}) and the surplus "
                    f"field is AMBIGUOUS — no single value is unique to this row "
                    f"({values}). Not auto-fixed: widen the table's columns or fix the "
                    f"row by hand.")
        k = candidates[0]
        removed = r.fields[k]
        kept = [f for i, f in enumerate(r.fields) if i != k]
        text = r.text[: r.open_at] + "( " + ", ".join(kept) + " )" + r.text[r.close_at + 1:]
        notes = [
            f"-- {self.options['marker_realigned']}: removed field {k + 1}, value {removed} "
            f"— it appears nowhere else in this table's grouping columns, so it is the "
            f"inserted one; {len(r.fields)} fields -> {want}.",
            "-- A BI developer MUST confirm. If that value belongs here, widen the "
            "table's columns instead.",
        ]
        return ("realign", text, notes,
                f"{label} realigned {len(r.fields)} -> {want} by removing field {k + 1} "
                f"({removed}), unique to this row — ANNOTATED IN PLACE, needs BI review.")


# ---------------------------------------------------------------------------
# F006 duplicate rows
# ---------------------------------------------------------------------------

_DUP_ROW_RE = re.compile(
    r'\(\s*(?:"(?P<quoted>(?:[^"]|"")+)"|(?P<bracket>\[[^\]]+\]))\s*,\s*'
    r'(?P<nameof>NAMEOF\s*\((?:[^()]|\([^()]*\))*\))\s*,'
    r'\s*(?P<order>-?\d+)\s*,\s*"(?P<identifier>(?:[^"]|"")+)"'
    r'(?P<extras>(?:\s*,\s*"(?:[^"]|"")*")*)\s*\)'
)


def _commented(before: str) -> bool:
    """Does a line comment open before the row on this line?"""
    return "//" in before or "--" in before


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
        "order are distinct, and so are two spellings of the same NAMEOF "
        "call: the whole call is compared, whitespace run by whitespace run. "
        "Auto-fix keeps the first copy and removes later copies; a commented "
        "copy is a parked row and is never touched."
    )

    @staticmethod
    def _key(m) -> tuple:
        """The tuple two rows must agree on to be duplicates."""
        display = m.group("quoted")
        if display is None:
            display = m.group("bracket")
        extras = tuple(re.findall(r'"([^"]*)"', m.group("extras")))
        return (display, " ".join(m.group("nameof").split()), int(m.group("order")),
                m.group("identifier"), extras)

    @classmethod
    def _groups(cls, text: str):
        groups: dict[tuple, list] = {}
        for m in _DUP_ROW_RE.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            if _commented(text[line_start:m.start()]):
                continue
            groups.setdefault(cls._key(m), []).append(m)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in axis_tables(model, self.options.get("axis_globs")):
                tf = _lines_of(t)
                if tf is None:
                    continue
                for key, matches in sorted(self._groups(tf.text).items()):
                    first = matches[0]
                    out.append(self.violation(
                        f"{key[0]!r} -> {key[1]} (order={key[2]}, id={key[3]!r}) "
                        f"appears {len(matches)}x",
                        file=t.file, line=tf.text.count("\n", 0, first.start()) + 1,
                        obj=f"{t.name}[{key[0]}]",
                    ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            total = 0
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
                    search_from = survivor.end()
                    while True:
                        hit = text.find(piece, search_from)
                        if hit < 0:
                            break
                        ls = text.rfind("\n", 0, hit) + 1
                        if _commented(text[ls:hit]):
                            search_from = hit + len(piece)
                            continue
                        le = text.find("\n", hit + len(piece))
                        le = len(text) if le < 0 else le
                        if not text[ls:hit].strip() and not text[hit + len(piece):le].strip():
                            text = text[:ls] + text[le + 1:]
                            search_from = ls
                        else:
                            text = text[:hit] + text[hit + len(piece):]
                            search_from = hit
                        removed += 1
                if not removed:
                    continue
                try:
                    if verified_write(tf, text):
                        applied.append(f"{t.file.name}: removed {removed} duplicate row(s)")
                        total += removed
                except EditRefused:
                    continue
            if total:
                ctx.blocks.append(
                    f"removed {total} duplicate axis row(s) under {model.definition_path}")
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
                else:
                    # the LAST numbered plot-specific table in name order is
                    # "the second plot-specific table"
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
        "Auto-fix copies the missing rows from the numbered tables, removes "
        "date rows from the second plot-specific table, promotes "
        "plot-specific-only rows into the first numbered table, and annotates "
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
        family: dict[str, tuple[Table, Row]] = {}
        # the numbered tables come first, in name order: a field they offer is
        # the one a missing row is copied from
        for t in group:
            for r in rows[t.name]:
                if len(r.fields) > 1:
                    family.setdefault(identity(r.fields[1], measures), (t, r))
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
                    dates.append((fam.ps2, identity(r.fields[1], measures), r))
        if fam.ps1 is not None:
            for r in rows[fam.ps1.name]:
                if len(r.fields) > 1 and identity(r.fields[1], measures) not in family:
                    unique.append((fam.ps1, identity(r.fields[1], measures), r))
        return missing, dates, unique

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for axis, fam in self._families(model):
                missing, dates, unique = self._analyse(model, axis, fam)
                for t, ident, owner, _r in missing:
                    out.append(self.violation(
                        f"MISSING {ident} (offered by {owner.file.name})",
                        file=t.file, obj=f"{t.name}:{ident}",
                    ))
                for t, ident, r in dates:
                    out.append(self.violation(
                        f"date-named field {ident} must not be in Plot Specific 2",
                        file=t.file, line=r.index + 1, obj=f"{t.name}:{ident}",
                    ))
                for t, ident, r in unique:
                    out.append(self.violation(
                        f"{ident} is offered NOWHERE in the canonical set — Plot Specific 1 "
                        f"may not introduce fields",
                        file=t.file, line=r.index + 1, obj=f"{t.name}:{ident}",
                    ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            added = removed = 0
            for axis, fam in self._families(model):
                for step in ("dates", "unique", "missing"):
                    ctx.reload()
                    model = next(m for m in ctx.models
                                 if m.definition_path == model.definition_path)
                    fam = _Family(model, axis, dict(self.options["axes"])[axis])
                    missing, dates, unique = self._analyse(model, axis, fam)
                    if step == "dates":
                        for t, ident, r in dates:
                            if self._remove_row(t, r, ident):
                                applied.append(
                                    f"{t.file.name}:{r.index + 1}: removed {ident} (date-named)")
                                removed += 1
                    elif step == "unique":
                        for t, ident, r in unique:
                            target = fam.numbered[0]
                            status, note = self._insert(target, r, ident, [
                                f"-- {self.options['marker_promoted']}: {ident} was offered "
                                f"only by {t.file.name}; Plot Specific 1 may not introduce "
                                f"fields, so it is promoted here rather than dropped from "
                                f"the picker.",
                                "-- A BI developer MUST confirm it belongs in the canonical set.",
                            ])
                            if status == "added":
                                applied.append(
                                    f"{target.file.name}: promoted {ident} "
                                    f"(was only in {t.file.name})")
                                added += 1
                            elif note:
                                applied.append(note)
                    else:
                        for t, ident, owner, r in missing:
                            status, note = self._insert(t, r, ident, [
                                f"-- {self.options['marker_added']}: copied from "
                                f"{owner.file.name} — every table in this family must offer "
                                f"{ident}.",
                            ])
                            if status == "added":
                                applied.append(
                                    f"{t.file.name}: added {ident} (from {owner.file.name})")
                                added += 1
                            elif note:
                                applied.append(note)
            if added or removed:
                ctx.blocks.append(
                    f"  ⚠ {added} row(s) added, {removed} removed under "
                    f"{model.definition_path}.\n"
                    f"    Each carries a '{self.options['marker_added']}' / "
                    f"'{self.options['marker_removed']}' comment — these are automatic edits "
                    f"to a\n"
                    f"    user-facing picker and a BI developer must review them.")
        return applied

    def _remove_row(self, t: Table, r: Row, ident: str) -> bool:
        """Replace a date row with the two comment lines that explain it."""
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
        indent = target.indent
        lines[target.index:target.index + 1] = [
            f"{indent}-- {self.options['marker_removed']}: {ident} references a name "
            f"containing the word '{self.options['excluded_word']}'; {t.name} must not "
            f"offer those.",
            f"{indent}-- A BI developer MUST confirm this row was not wanted here.",
        ]
        try:
            return verified_write(tf, tf.join(lines))
        except EditRefused:
            return False

    def _insert(self, t: Table, r: Row, ident: str, notes: list[str]) -> tuple[str, str]:
        """Copy the row ``r`` into table ``t``.

        The row text is copied verbatim - its own indentation and its own
        trailing comma - and the separators around it are repaired
        afterwards. Returns ``("added", "")``, ``("arity", note)`` when the
        sibling row has a different width, or ``("failed", "")``.
        """
        tf = read_text_file(t.file)
        lines = tf.lines()
        rows = read_rows(lines)
        widths = Counter(len(x.fields) for x in rows)
        if widths:
            target_arity = max(widths, key=lambda w: widths[w])
            if len(r.fields) != target_arity:
                return ("arity", f"{t.file.name}: {ident} NOT added — the sibling row has "
                                 f"{len(r.fields)} fields, this table's rows have "
                                 f"{target_arity}. Re-shaping across arities is the "
                                 f"ragged-tuple fixer's job, not this one.")
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
        if at is None:
            at = rows[-1].index + 1 if rows else self._constructor_end(lines)
        indent = (lines[at][: len(lines[at]) - len(lines[at].lstrip())]
                  if at < len(lines) else "\t\t\t\t")
        new_lines = lines[:at] + [indent + n for n in notes] + [r.text] + lines[at:]
        text, _n = insert_missing_row_separators(tf.join(new_lines))
        text, _n = remove_trailing_row_commas(text)
        try:
            return ("added", "") if verified_write(tf, text) else ("failed", "")
        except EditRefused:
            return ("failed", "")

    @staticmethod
    def _constructor_end(lines: list[str]) -> int:
        """Index of the line that closes the table constructor."""
        span = source_span(lines)
        at = span[1] if span else len(lines)
        while at > 0 and lines[at - 1].strip() != "}":
            at -= 1
        return at
