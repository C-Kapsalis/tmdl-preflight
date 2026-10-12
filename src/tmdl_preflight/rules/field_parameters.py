"""Field-parameter (and calculated-table) source hygiene. IDs F0xx."""

from __future__ import annotations

from pathlib import Path

from typing import Callable

from ..dax import (
    check_balanced_delimiters,
    collapse_comma_runs,
    find_comma_runs,
    insert_missing_row_separators,
    remove_trailing_row_commas,
    scan_table_constructors,
)
from ..edits import EditRefused, read_text_file, verified_write
from .base import Context, Rule, Severity, Violation


def _calculated_partitions(model):
    for table in model.tables.values():
        for p in table.partitions:
            if p.kind == "calculated" and p.source:
                yield table, p


class FieldParameterCommaRunsRule(Rule):
    id = "F001"
    name = "fieldparam-comma-runs"
    severity = Severity.ERROR
    fixable = True
    description = (
        "Calculated-table sources (which include field-parameter tables) must "
        "not contain stray structural commas: two or more commas separated "
        "only by whitespace, typically left behind when a row was removed but "
        "its separator was not. One stray comma makes the whole source "
        "unparseable. Commas inside -- or // comments are exempt. Auto-fix "
        "keeps each run's first comma and deletes the orphans."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for table, part in _calculated_partitions(model):
                for rel_line, orphans in find_comma_runs(part.source):
                    line = (part.source_start_line or part.line) + rel_line - 1
                    out.append(
                        self.violation(
                            f"stray comma run ({orphans} orphan comma(s)) in "
                            f"calculated partition source",
                            file=part.file,
                            line=line,
                            obj=f"{table.name} (partition source)",
                        )
                    )
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for table, part in _calculated_partitions(model):
                if not find_comma_runs(part.source):
                    continue
                if part.source_start_line is None or part.source_end_line is None:
                    continue
                applied.extend(
                    _collapse_in_file(
                        part.file, part.source_start_line, part.source_end_line, table.name
                    )
                )
        return applied


def _collapse_in_file(file: Path, start: int, end: int, table_name: str) -> list[str]:
    """Collapse comma runs inside a 1-based inclusive line range of ``file``,
    leaving every other byte untouched."""
    original = read_text_file(file)
    lines = original.lines()
    lo, hi = start - 1, min(end, len(lines))
    block = original.join(lines[lo:hi])
    new_block, removed = collapse_comma_runs(block)
    if not removed:
        return []
    lines[lo:hi] = new_block.split(original.newline)

    def verify(old: str, new: str) -> None:
        if old.replace(",", "") != new.replace(",", ""):
            raise EditRefused("comma-run repair changed more than commas")

    try:
        verified_write(original, original.join(lines), verify)
    except EditRefused:
        return []
    return [
        f"{file.name}: removed {removed} orphan comma(s) from "
        f"'{table_name}' partition source"
    ]


def _repair_block(
    file: Path,
    start: int,
    end: int,
    repair: Callable[[str], tuple[str, int]],
    issue_kind: str,
) -> int:
    """Apply a comma-only ``repair`` to lines ``start..end`` (1-based,
    inclusive) of ``file`` and write it through ``verified_write``.

    The edit is refused unless the repaired block differs from the original
    only in commas, still balances, and no longer shows ``issue_kind``.
    """
    original = read_text_file(file)
    lines = original.lines()
    lo, hi = start - 1, min(end, len(lines))
    block = original.join(lines[lo:hi])
    new_block, changed = repair(block)
    if not changed:
        return 0
    new_lines = lines[:lo] + new_block.split(original.newline) + lines[hi:]

    def verify(old: str, new: str) -> None:
        if old.replace(",", "") != new.replace(",", ""):
            raise EditRefused("repair changed more than commas")
        if check_balanced_delimiters(new_block) != check_balanced_delimiters(block):
            raise EditRefused("repair changed delimiter balance")
        if any(i.kind == issue_kind for i in scan_table_constructors(new_block)):
            raise EditRefused("defect still present after repair")

    try:
        verified_write(original, original.join(new_lines), verify)
    except EditRefused:
        return 0
    return changed


class _ConstructorRuleBase(Rule):
    """Shared plumbing for the table-constructor rules F002-F004: one
    recognizer (``scan_table_constructors``) feeds both check and fix."""

    issue_kind = ""

    def _issues(self, ctx: Context):
        for model in ctx.models:
            for table, part in _calculated_partitions(model):
                for issue in scan_table_constructors(part.source):
                    if issue.kind == self.issue_kind:
                        yield table, part, issue

    def _message(self, issue) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for table, part, issue in self._issues(ctx):
            out.append(
                self.violation(
                    self._message(issue),
                    file=part.file,
                    line=(part.source_start_line or part.line) + issue.line - 1,
                    obj=f"{table.name} (partition source)",
                )
            )
        return out

    def _fix_with(self, ctx: Context, repair, label: str) -> list[str]:
        applied: list[str] = []
        done: set[tuple] = set()
        for table, part, _issue in list(self._issues(ctx)):
            key = (part.file, part.source_start_line)
            if key in done or part.source_start_line is None or part.source_end_line is None:
                continue
            done.add(key)
            changed = _repair_block(
                part.file, part.source_start_line, part.source_end_line, repair,
                self.issue_kind,
            )
            if changed:
                applied.append(f"{part.file.name}: {label} {changed} comma(s) in '{table.name}' partition source")
        return applied


class MissingRowSeparatorRule(_ConstructorRuleBase):
    id = "F002"
    name = "fieldparam-missing-separator"
    severity = Severity.ERROR
    fixable = True
    issue_kind = "missing_separator"
    description = (
        "Rows of a { (...), (...) } table constructor (field parameters, "
        "calculated tables) must be separated by commas. A row appended after "
        "the previous last row without adding its comma makes the whole "
        "source unparseable; the table then loads empty. Auto-fix inserts "
        "the comma after the previous row."
    )

    def _message(self, issue) -> str:
        return (
            "two rows of the table constructor have no comma between them, "
            "so the calculated partition source cannot be parsed and the "
            "table loads empty. Add a comma after the previous row (the "
            "auto-fix does)."
        )

    def fix(self, ctx: Context) -> list[str]:
        return self._fix_with(ctx, insert_missing_row_separators, "inserted")


class TrailingRowCommaRule(_ConstructorRuleBase):
    id = "F003"
    name = "fieldparam-trailing-comma"
    severity = Severity.ERROR
    fixable = True
    issue_kind = "trailing_comma"
    description = (
        "The last row of a { (...), (...) } table constructor must not be "
        "followed by a comma. A trailing comma before the closing brace, "
        "typically left behind when the last row is deleted, makes the "
        "source unparseable. Auto-fix deletes the comma."
    )

    def _message(self, issue) -> str:
        return (
            "the table constructor ends with a comma before its closing "
            "brace, so the calculated partition source cannot be parsed. "
            "Delete the trailing comma (the auto-fix does)."
        )

    def fix(self, ctx: Context) -> list[str]:
        return self._fix_with(ctx, remove_trailing_row_commas, "removed")


class RaggedRowWidthRule(_ConstructorRuleBase):
    id = "F004"
    name = "fieldparam-ragged-rows"
    severity = Severity.WARNING
    issue_kind = "ragged"
    description = (
        "Every row of a { (...), (...) } table constructor should have the "
        "same number of values. A row with one value too many or too few "
        "usually means a missing or extra comma inside the row, which "
        "shifts values into the wrong columns or fails the source. Not "
        "auto-fixable: only a human knows which value is wrong."
    )

    def _message(self, issue) -> str:
        widths = sorted(set(issue.widths))
        counts = {w: issue.widths.count(w) for w in widths}
        detail = ", ".join(f"{counts[w]} row(s) with {w}" for w in widths)
        return (
            f"rows of this table constructor have different widths ({detail}). "
            f"Check the odd row(s) for a missing or extra value."
        )
