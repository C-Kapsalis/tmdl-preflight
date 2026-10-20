"""Field-parameter (and calculated-table) source hygiene. IDs F0xx."""

from __future__ import annotations

import re
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
        "source unparseable. The Desktop symptom is expected to match F001 "
        "(the model opens, visuals on the table fail), but it has not been "
        "observed for this defect on its own. Auto-fix inserts the comma "
        "after the previous row."
    )

    def _message(self, issue) -> str:
        return (
            "two rows of the table constructor have no comma between them, "
            "so the calculated partition source cannot be parsed (visuals on "
            "this table are expected to fail, as with F001; not observed for "
            "this defect alone). Add a comma after the previous row (the "
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
        "source unparseable; the Desktop symptom is expected to match F001 "
        "but has not been observed for this defect alone. Auto-fix deletes "
        "the comma."
    )

    def _message(self, issue) -> str:
        return (
            "the table constructor ends with a comma before its closing "
            "brace, so the calculated partition source cannot be parsed. "
            "Delete the trailing comma (the auto-fix does)."
        )

    def fix(self, ctx: Context) -> list[str]:
        return self._fix_with(ctx, remove_trailing_row_commas, "removed")


_THREE_FIELD_RE = re.compile(r'\(\s*"(?P<label>[^"]*)"\s*,\s*NAMEOF\s*\([^()]*\)\s*,\s*-?\d+\s*\)')
_FOUR_FIELD_RE = re.compile(
    r'\(\s*"(?P<label>[^"]*)"\s*,\s*NAMEOF\s*\([^()]*\)\s*,\s*-?\d+,\s*"[^"]*"\s*\)'
)


class FieldParameterCategoryColumnRule(Rule):
    id = "F005"
    name = "fieldparam-category-column"
    severity = Severity.ERROR
    option_defaults = {"category_column_tables": [], "category_position": 4}
    description = (
        "In field parameters that carry a category column (configure "
        "category_column_tables, names or globs), every row needs the "
        "category: a 3-field row (label, NAMEOF, order) whose label has no "
        "4-field twin in the same table silently drops out of every category "
        "filter. Only fenced calculated sources are read. Not auto-fixable: "
        "the category is a business decision. Inert until configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        from fnmatch import fnmatchcase

        patterns = self.options.get("category_column_tables") or []
        if not patterns:
            return []
        out: list[Violation] = []
        for model in ctx.models:
            for table in model.table_list:
                if not any(fnmatchcase(table.name, p) for p in patterns):
                    continue
                part = next((p for p in table.partitions if p.kind == "calculated" and p.source), None)
                if part is None or not _is_fenced(part):
                    continue
                four = {m.group("label") for m in _FOUR_FIELD_RE.finditer(part.source)}
                for m in _THREE_FIELD_RE.finditer(part.source):
                    if m.group("label") in four:
                        continue
                    # the fenced body starts on the line after 'source = ```'
                    line = (part.source_start_line or part.line) + 1 + part.source.count("\n", 0, m.start())
                    out.append(self.violation(
                        f"row \"{m.group('label')}\" of {table.name} has no category "
                        f"(value {self.options['category_position']}); add it so the row "
                        f"shows up under category filters.",
                        file=part.file, line=line, obj=f"{table.name}[{m.group('label')}]",
                    ))
        return out


def _is_fenced(part) -> bool:
    try:
        lines = part.file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    for idx in range(part.line - 1, min(len(lines), (part.source_start_line or part.line) + 1)):
        if lines[idx].strip().startswith("source") and "```" in lines[idx]:
            return True
    return False


# F001 and F004 moved to fp_rows (whole-file scope and row-level fixers);
# keep them importable from here.
from .fp_rows import FieldParameterCommaRunsRule, RaggedRowWidthRule  # noqa: E402,F401
