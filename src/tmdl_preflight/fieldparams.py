"""Field-parameter tables: which files they are, how to read their rows,
and the text edits their fixers make.

A field parameter is a calculated table built from a ``{ (label,
NAMEOF(...), order, ...), ... }`` constructor. Its rows are written one per
line by Desktop and by the scripts that maintain axis tables, so the row
reader here is line-based: it reads only the source body of the first
calculated partition and never mistakes a calculated column or a comment
for a row.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Iterable, Optional

from .model import SemanticModel, Table
from .roles import is_field_parameter_table

AXIS_GLOBS = ["x-Selector*", "x-Plot Specific*", "y-Selector*", "y-Plot Specific*"]
_TAIL_RE = re.compile(r"^\t(?:annotation|partition|column|measure)\b")


def axis_tables(model: SemanticModel, globs: Optional[Iterable[str]] = None) -> list[Table]:
    pats = list(globs) if globs is not None else AXIS_GLOBS
    return [t for t in model.table_list if any(fnmatchcase(t.name, p) for p in pats)]


def field_parameter_files(model: SemanticModel, globs: Optional[Iterable[str]] = None) -> list[Table]:
    """Detected field parameters plus every table the axis globs name."""
    named = {t.name for t in axis_tables(model, globs)}
    return [t for t in model.table_list if t.name in named or is_field_parameter_table(t)]


# ---------------------------------------------------------------------------
# Masking: comments and string contents become spaces
# ---------------------------------------------------------------------------


def mask_line(line: str) -> str:
    """Blank the line comment (``--``/``//`` outside quotes) and the content
    of double-quoted strings; positions are preserved."""
    out = list(line)
    quote: Optional[str] = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                if quote == '"' and line[i + 1:i + 2] == '"':
                    out[i] = out[i + 1] = " "
                    i += 2
                    continue
                quote = None
            elif quote == '"':
                out[i] = " "
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif line.startswith(("--", "//"), i):
            for k in range(i, len(line)):
                out[k] = " "
            break
        i += 1
    return "".join(out)


def mask_text(text: str) -> str:
    return "\n".join(mask_line(ln) for ln in text.split("\n"))


_RUN_RE = re.compile(r",(?:\s*,)+")


def comma_runs(text: str) -> list[tuple[int, list[int]]]:
    """``(line, surplus comma offsets)`` for every run of commas."""
    masked = mask_text(text)
    runs = []
    for m in _RUN_RE.finditer(masked):
        offsets = [m.start() + k for k, ch in enumerate(m.group(0)) if ch == ","]
        runs.append((masked.count("\n", 0, m.start()) + 1, offsets[1:]))
    return runs


def drop_offsets(text: str, offsets: Iterable[int]) -> str:
    gone = set(offsets)
    return "".join(ch for k, ch in enumerate(text) if k not in gone)


# ---------------------------------------------------------------------------
# Row reader
# ---------------------------------------------------------------------------


@dataclass
class Row:
    index: int  # 0-based line index in the file
    text: str  # the full line
    open_at: int  # index of the first '(' in the line
    close_at: int  # index of the last ')' in the line
    fields: list[str] = field(default_factory=list)

    @property
    def indent(self) -> str:
        return self.text[: len(self.text) - len(self.text.lstrip())]

    @property
    def trailing_comma(self) -> bool:
        return self.text[self.close_at + 1:].strip().startswith(",")


def split_fields(body: str) -> list[str]:
    parts, buf, level = [], [], 0
    quote: Optional[str] = None
    for ch in body:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "[":
            quote = "]"
        elif ch in "({":
            level += 1
        elif ch in ")}":
            level -= 1
        if ch == "," and level == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf).strip())
    return parts


def source_span(lines: list[str]) -> Optional[tuple[int, int]]:
    """Line range [start, end) of the first calculated partition's source."""
    in_calc = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("partition ") and stripped.endswith("= calculated"):
            in_calc = True
            continue
        if in_calc and stripped.startswith("source") and "=" in stripped:
            end = idx + 1
            while end < len(lines) and not _TAIL_RE.match(lines[end]):
                end += 1
            return idx + 1, end
    return None


def _groups(line: str) -> list[tuple[int, int]]:
    """Top-level ``( ... )`` groups of a line, quotes and brackets skipped."""
    out, level, start = [], 0, -1
    quote: Optional[str] = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "[":
            quote = "]"
        elif ch == "(":
            if level == 0:
                start = i
            level += 1
        elif ch == ")" and level:
            level -= 1
            if level == 0:
                out.append((start, i))
    return out


def read_rows(lines: list[str]) -> list[Row]:
    """Rows of the first calculated partition's source. A row is a
    top-level ``( "label" | [ref], ... )`` group mentioning NAMEOF with at
    least two fields; comment lines are never rows."""
    span = source_span(lines)
    if span is None:
        return []
    return _rows_in(lines[span[0]:span[1]], span[0])


def source_rows(source: str) -> list[Row]:
    """The field-parameter rows of a partition source text.

    A row is a top-level ``( "label", NAMEOF(...), ... )`` group that
    mentions NAMEOF and carries at least two fields; a comment line is
    never a row.
    """
    return _rows_in(source.split("\n"), 0)


def _rows_in(lines: list[str], offset: int) -> list[Row]:
    rows = []
    for idx, line in enumerate(lines):
        if line.strip().startswith(("--", "//")):
            continue
        for open_at, close_at in _groups(line):
            inner = line[open_at + 1:close_at]
            if "nameof" not in inner.lower() or not inner.lstrip().startswith(('"', "[")):
                continue
            fields = split_fields(inner)
            if len(fields) >= 2:
                rows.append(Row(idx + offset, line, open_at, close_at, fields))
    return rows


def rows_alone(rows: list[Row]) -> list[Row]:
    """Rows that are the only row on their line (safe to edit by line)."""
    per_line = Counter(r.index for r in rows)
    return [r for r in rows if per_line[r.index] == 1]


def expected_width(rows: list[Row]) -> Optional[int]:
    if not rows:
        return None
    counts = Counter(len(r.fields) for r in rows)
    top = max(counts.values())
    return next(len(r.fields) for r in rows if counts[len(r.fields)] == top)


# ---------------------------------------------------------------------------
# Field identity (family consistency)
# ---------------------------------------------------------------------------

_BRACKET_END_RE = re.compile(r"\[([^\]]*)\]\s*$")


def nameof_parts(arg_field: str) -> tuple[Optional[str], str]:
    """``(qualifier or None, object)`` of a row's NAMEOF field."""
    inner = re.sub(r"^\s*NAMEOF\s*\(", "", arg_field, flags=re.IGNORECASE)
    inner = re.sub(r"\)\s*$", "", inner).strip()
    m = _BRACKET_END_RE.search(inner)
    if not m:
        return None, inner
    qual = inner[: m.start()].strip()
    if len(qual) >= 2 and qual[0] == qual[-1] == "'":
        qual = qual[1:-1]
    return (qual.replace("''", "'") or None), m.group(1).strip()


def identity(arg_field: str, measures: set[str]) -> str:
    qual, obj = nameof_parts(arg_field)
    inner = re.sub(r"^\s*NAMEOF\s*\(|\)\s*$", "", arg_field, flags=re.IGNORECASE)
    if not _BRACKET_END_RE.search(inner.strip()):
        return re.sub(r"[\s']", "", inner)
    if obj in measures:
        return obj
    obj_norm = re.sub(r"\s+", " ", obj)
    return (re.sub(r"\s", "", qual) if qual else "") + f"[{obj_norm}]"


def field_spans(line: str, open_at: int, close_at: int) -> list[tuple[int, int]]:
    """``(start, end)`` offsets in ``line`` of each top-level field of the row
    group ``line[open_at:close_at + 1]``, whitespace trimmed."""
    spans, start, level = [], open_at + 1, 0
    quote: Optional[str] = None
    for i in range(open_at + 1, close_at):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "[":
            quote = "]"
        elif ch in "({":
            level += 1
        elif ch in ")}":
            level -= 1
        elif ch == "," and level == 0:
            spans.append((start, i))
            start = i + 1
    spans.append((start, close_at))
    out = []
    for s, e in spans:
        while s < e and line[s].isspace():
            s += 1
        while e > s and line[e - 1].isspace():
            e -= 1
        out.append((s, e))
    return out


def row_label(line: str) -> Optional[str]:
    """The first value of the first top-level group on the line.

    A field-parameter row starts with its label: ``("Revenue", NAMEOF(...))``.
    """
    for open_at, close_at in _groups(line):
        fields = split_fields(line[open_at + 1:close_at])
        if not fields:
            continue
        value = fields[0].strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        return value.replace('""', '"')
    return None


def is_live_row(row: Row) -> bool:
    """False when a comment marker precedes the row on its line."""
    return mask_line(row.text)[row.open_at] == "("
