"""Field-parameter file layout: rows that carry a double slash, and the
blank lines and indentation a fenced source accumulates.

Both rules read the first fenced source of a table file: the block between
the ``source = ``` `` line and the next line that is a fence. A table
without one is left alone.
"""

from __future__ import annotations

import re
import shutil
from fnmatch import fnmatchcase
from typing import Optional

from ..edits import EditRefused, read_text_file, verified_write
from ..model import SemanticModel, Table
from .base import Context, Rule, Severity, Violation

#: The field-parameter family files, by file name.
AXIS_FILE_GLOBS = ("*-Selector*", "*-Plot Specific*")

_FENCE_OPEN_RE = re.compile(r"^\t\tsource\s*=\s*```[ \t]*$")
_FENCE_CLOSE_RE = re.compile(r"^\t+```[ \t]*$")
_CALCULATED_RE = re.compile(r"^\s*partition\s+.*=\s*calculated\s*$")
_MODE_RE = re.compile(r"^\s*mode:\s*import\s*$")
_SOURCE_INDENT_RE = re.compile(r"^(\t+)source\s*=\s*```")
_ANY_FENCE_OPEN_RE = re.compile(r"^(\t+)source\s*=\s*```[ \t]*$")


def fenced_source(lines: list[str]) -> Optional[tuple[int, int, str]]:
    """``(first line, last line, indent)`` of the first fenced source.

    The opening line is indented by exactly two tabs; the block ends at the
    next line that is one or more tabs followed by a fence. ``indent`` is
    the indentation of the opening line plus two tabs, or four tabs when it
    cannot be told. ``None`` when the file holds no fenced source.
    """
    for idx, line in enumerate(lines):
        if not _FENCE_OPEN_RE.match(line):
            continue
        for end in range(idx + 1, len(lines)):
            if _FENCE_CLOSE_RE.match(lines[end]):
                m = _SOURCE_INDENT_RE.match(line)
                indent = (m.group(1) + "\t\t") if m else "\t\t\t\t"
                return idx + 1, end, indent
        return None
    return None


def calculated_fenced_source(lines: list[str]) -> Optional[tuple[int, int, str]]:
    """The fenced source of a calculated partition that imports its data.

    The partition header, the ``mode: import`` line and the fence have to
    follow each other; a table without them holds no fenced source. The
    indentation of the fence decides the canonical indentation of the
    block: the fence's own indentation plus two tabs.
    """
    for idx, line in enumerate(lines):
        if not _CALCULATED_RE.match(line):
            continue
        mode = None
        for probe in range(idx + 1, min(idx + 4, len(lines))):
            if _MODE_RE.match(lines[probe]):
                mode = probe
                break
        if mode is None:
            continue
        for probe in range(mode + 1, min(mode + 4, len(lines))):
            m = _ANY_FENCE_OPEN_RE.match(lines[probe])
            if not m:
                continue
            for end in range(probe + 1, len(lines)):
                if _FENCE_CLOSE_RE.match(lines[end]):
                    return probe + 1, end, m.group(1) + "\t\t"
            return None
    return None


def is_entry_line(line: str) -> bool:
    """An entry line of a field-parameter source: it has a row on it."""
    return "(" in line and "NAMEOF" in line and ")" in line


class FieldParameterDoubleSlashRowsRule(Rule):
    id = "F016"
    name = "fieldparam-double-slash-rows"
    severity = Severity.INFO
    fixable = True
    # the repair deletes rows from a user-facing picker: it is opt-in
    safe = False
    option_defaults = {"file_globs": list(AXIS_FILE_GLOBS)}
    description = (
        "A field-parameter row that carries '//' is either a row that was "
        "commented out (dead residue that makes later merges and row counts "
        "lie) or a label with a double slash in it, which some editors read "
        "as the start of a comment and truncate the row. The rule reads the "
        "first fenced source of every axis table. The repair deletes the "
        "offending rows, keeps a backup of the file and is opt-in, because "
        "it removes text from a picker a user sees."
    )

    def _tables(self, model: SemanticModel) -> list[Table]:
        globs = self.options.get("file_globs") or []
        return [t for t in model.table_list
                if any(fnmatchcase(t.file.name, p) for p in globs)]

    @staticmethod
    def _offenders(lines: list[str]) -> tuple[list[tuple[int, str]], int]:
        """``([(line number, text)], total entry lines)`` of one file."""
        span = fenced_source(lines)
        if span is None:
            return [], 0
        start, end, _indent = span
        entries = [(idx, lines[idx]) for idx in range(start, end)
                   if is_entry_line(lines[idx])]
        return [(idx, text) for idx, text in entries if "//" in text], len(entries)

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in self._tables(model):
                try:
                    lines = read_text_file(t.file).lines()
                except (OSError, UnicodeDecodeError):
                    continue
                offenders, _total = self._offenders(lines)
                for idx, text in offenders:
                    out.append(self.violation(
                        f"the row carries '//' and would be read as a comment: {text.strip()}",
                        file=t.file, line=idx + 1, obj=f"{t.name}:{idx + 1}",
                    ))
        if ctx.options.get("_dry_run"):
            self._dry_run_report(ctx)
        return out

    def _dry_run_report(self, ctx: Context) -> None:
        """What the repair would do, printed when the run writes nothing."""
        for model in ctx.models:
            per_line: list[str] = []
            per_file: list[str] = []
            files = removed = 0
            for t in self._tables(model):
                try:
                    lines = read_text_file(t.file).lines()
                except (OSError, UnicodeDecodeError):
                    continue
                offenders, total = self._offenders(lines)
                if not offenders:
                    continue
                for _idx, text in offenders:
                    per_line.append(f"Removing: {text.strip()[:80]}...")
                per_file.append(f"✓ {t.file.name}: Removed {len(offenders)}/{total} entries")
                files += 1
                removed += len(offenders)
            if not files:
                continue
            ctx.blocks.append("\n".join(per_line + per_file))
            ctx.blocks.append(self._summary(files, removed))
            ctx.blocks.append(f"ℹ️  Would remove {removed} entries (dry run)")

    @staticmethod
    def _summary(files: int, removed: int) -> str:
        return ("=" * 80 + "\n"
                "SUMMARY\n"
                + "=" * 80 + "\n"
                f"Files modified: {files}\n"
                f"Entries removed: {removed}")

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        files = removed_total = 0
        for model in ctx.models:
            for t in self._tables(model):
                try:
                    tf = read_text_file(t.file)
                except (OSError, UnicodeDecodeError):
                    continue
                lines = tf.lines()
                offenders, total = self._offenders(lines)
                if not offenders:
                    continue
                for _idx, text in offenders:
                    applied.append(f"Removing: {text.strip()[:80]}...")
                drop = {idx for idx, _text in offenders}
                keep = [ln for i, ln in enumerate(lines) if i not in drop]
                new_text = tf.join(keep)
                backups = t.file.parent / "backups"
                try:
                    backups.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(t.file, backups / f"{t.file.name}.double_slash_backup")
                except OSError:
                    pass

                def verify(old: str, new: str) -> None:
                    if len(new.splitlines()) != len(old.splitlines()) - len(offenders):
                        raise EditRefused("the repair removed a different number of lines")

                try:
                    if not verified_write(tf, new_text, verify):
                        continue
                except EditRefused:
                    continue
                applied.append(f"✓ {t.file.name}: Removed {len(offenders)}/{total} entries")
                files += 1
                removed_total += len(offenders)
        if not files:
            ctx.blocks.append("✓ No entries with // found")
            return applied
        ctx.blocks.append(self._summary(files, removed_total))
        ctx.blocks.append(
            f"✓ Removed {removed_total} entries\n"
            f"  Backups in tables/backups/*.double_slash_backup")
        return applied


class FieldParameterBlankLinesRule(Rule):
    id = "F017"
    name = "fieldparam-blank-lines"
    severity = Severity.INFO
    fixable = True
    option_defaults = {}
    description = (
        "A fenced field-parameter source that scripts keep rewriting "
        "accumulates blank lines and a drifted indentation, so the file "
        "grows, the diff noise hides real changes and two copies of the same "
        "table stop comparing equal. The rule reports a source that is not "
        "in its canonical form - a blank line, the indented brace, the rows "
        "with their blank runs collapsed, the indented closing brace - and "
        "the repair rewrites the block to that form."
    )

    @staticmethod
    def _canonical(text: str, lines: list[str], newline: str) -> Optional[tuple[int, int, str, int]]:
        """``(open at, close at, canonical block, lines removed)`` of a file.

        ``None`` when the file holds no fenced calculated source.
        """
        span = calculated_fenced_source(lines)
        if span is None:
            return None
        start, end, indent = span
        offset = 0
        for line in lines[:start - 1]:
            offset += len(line) + len(newline)
        open_at = offset + len(lines[start - 1])
        close_at = text.index("```", open_at)
        raw = text[open_at:close_at]
        inner = re.search(r"\{(.*)\}", raw, re.DOTALL)
        if inner is None:
            return None
        body = inner.group(1).split("\n")
        kept: list[str] = []
        previous_blank = False
        for line in body:
            blank = line.strip(" \t\r") == ""
            if blank:
                if previous_blank:
                    continue
                previous_blank = True
                kept.append("")
                continue
            previous_blank = False
            kept.append(line)
        while kept and kept[-1].strip(" \t\r") == "":
            kept.pop()
        while kept and kept[0].strip(" \t\r") == "":
            kept.pop(0)
        removed = len(body) - len(kept)
        block = ("\n" + indent + "\n"
                 + indent + "{\n"
                 + "\n".join(kept) + "\n"
                 + indent + "}\n"
                 + indent)
        return open_at, close_at, block, removed

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in model.table_list:
                try:
                    tf = read_text_file(t.file)
                except (OSError, UnicodeDecodeError):
                    continue
                found = self._canonical(tf.text, tf.lines(), tf.newline)
                if found is None:
                    continue
                open_at, close_at, block, removed = found
                if tf.text[open_at:close_at] == block:
                    continue
                out.append(self.violation(
                    f"the fenced source is not in its canonical form "
                    f"({removed} blank line(s) to remove)",
                    file=t.file, obj=f"{t.name} (fenced source)",
                ))
        return out

    def pending_repairs(self, ctx: Context) -> bool:
        """The repair says something even when no file needs it: a model
        without a tables folder is worth a word."""
        return any(not (m.definition_path / "tables").is_dir() for m in ctx.models)

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        changed = 0
        missing = False
        for model in ctx.models:
            if not (model.definition_path / "tables").is_dir():
                ctx.blocks.append("⚠️  No tables directory")
                missing = True
                continue
            for t in model.table_list:
                try:
                    tf = read_text_file(t.file)
                except (OSError, UnicodeDecodeError):
                    continue
                found = self._canonical(tf.text, tf.lines(), tf.newline)
                if found is None:
                    continue
                open_at, close_at, block, removed = found
                if tf.text[open_at:close_at] == block:
                    continue
                new_text = tf.text[:open_at] + block + tf.text[close_at:]
                try:
                    if not verified_write(tf, new_text):
                        continue
                except EditRefused:
                    continue
                what = f"removed {removed} blank lines" if removed else "normalized indentation"
                applied.append(f"✓ {t.file.name}: {what}")
                changed += 1
        if not changed and not missing:
            ctx.blocks.append("✓ No whitespace issues found in field parameter files")
        return applied
