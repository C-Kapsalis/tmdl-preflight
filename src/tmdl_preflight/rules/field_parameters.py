"""Field-parameter (and calculated-table) source hygiene. IDs F0xx."""

from __future__ import annotations

from pathlib import Path

from ..dax import collapse_comma_runs, find_comma_runs
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
        "not contain stray structural commas — two or more commas separated "
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
    text = file.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    lo, hi = start - 1, min(end, len(lines))
    block = newline.join(lines[lo:hi])
    new_block, removed = collapse_comma_runs(block)
    if not removed:
        return []
    lines[lo:hi] = new_block.split(newline)
    file.write_text(newline.join(lines), encoding="utf-8", newline="")
    return [
        f"{file.name}: removed {removed} orphan comma(s) from "
        f"'{table_name}' partition source"
    ]
