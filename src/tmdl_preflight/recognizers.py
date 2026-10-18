"""Line-level TMDL recognizers shared by a rule's check and its fixer.

Each recognizer here answers one question about raw TMDL text ("where are
the dangling descriptions?", "which properties sit after a child block?").
The rule's ``check()`` reports what the recognizer finds and the rule's
``fix()`` repairs exactly those findings, so the detector and the fixer can
never disagree about what counts as a defect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Optional

from .parser import indent_level

# ---------------------------------------------------------------------------
# Fences
# ---------------------------------------------------------------------------


def iter_unfenced(lines: list[str]) -> Iterator[tuple[int, str]]:
    """Yield ``(index, line)`` for every line outside a ``` fenced block.

    The opening line of a fence (``measure X = ```) is yielded; the lines
    inside it and the closing fence are not.
    """
    in_fence = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if in_fence:
            if stripped.startswith("```"):
                in_fence = False
            continue
        yield idx, line
        if stripped.count("```") % 2 == 1:
            in_fence = True


_FENCE_OPEN_RE = re.compile(r"=\s*```")


def unpaired_fence(lines: list[str]) -> Optional[int]:
    """0-based index of a ``` fence that never pairs up, or None.

    A fence opens on a line whose text after ``=`` starts with three
    backticks and closes on the next line that starts with three backticks.
    Backticks anywhere else (inside a string literal of a fenced body, or in
    a one-line expression) are content, not fences. A line that starts with
    backticks outside any fence is a stray closing fence.
    """
    open_at: Optional[int] = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if open_at is not None:
            if stripped.startswith("```"):
                open_at = None
            continue
        m = _FENCE_OPEN_RE.search(line)
        if m:
            if line.count("```", m.end()) == 0:  # not opened and closed in one line
                open_at = idx
            continue
        if stripped.startswith("```"):
            return idx
    return open_at


# ---------------------------------------------------------------------------
# M013: dangling /// descriptions
# ---------------------------------------------------------------------------


def _is_description(line: str) -> bool:
    return line.lstrip().startswith("///")


@dataclass
class DanglingDescription:
    start: int  # 0-based index of the first /// line of the run
    end: int  # 0-based index of the last /// line of the run
    at_eof: bool  # nothing but blank lines follows the run


def find_dangling_descriptions(lines: list[str]) -> list[DanglingDescription]:
    """``///`` runs that are followed by a blank line or the end of the file
    instead of the declaration they are meant to describe."""
    out: list[DanglingDescription] = []
    i, n = 0, len(lines)
    while i < n:
        if not _is_description(lines[i]):
            i += 1
            continue
        j = i
        while j + 1 < n and _is_description(lines[j + 1]):
            j += 1
        nxt = lines[j + 1] if j + 1 < n else None
        if nxt is None or not nxt.strip():
            at_eof = all(not ln.strip() for ln in lines[j + 1 :])
            out.append(DanglingDescription(i, j, at_eof))
        i = j + 1
    return out


def remove_dangling_descriptions(lines: list[str]) -> tuple[list[str], int]:
    """Delete each dangling run plus the one blank line directly after it.

    The same rule holds at the end of the file: blank lines *before* a run
    are never touched. ``lines`` is the file split on its newline, so a file
    that ends with a newline has an empty last element; that element is the
    file's final newline, not a blank line, and is kept.
    """
    found = find_dangling_descriptions(lines)
    if not found:
        return lines, 0
    drop: set[int] = set()
    last = len(lines) - 1
    for d in found:
        drop.update(range(d.start, d.end + 1))
        after = d.end + 1
        if after <= last and not lines[after].strip():
            if after < last or lines[after] != "":
                drop.add(after)  # the single blank line that orphaned the run
    return [ln for k, ln in enumerate(lines) if k not in drop], len(found)


def attach_descriptions(lines: list[str]) -> tuple[list[str], int, int]:
    """Attach mode of the M013 fixer: delete every whitespace-only line that
    directly follows a ``///`` line, so the description sits on its object
    again. Returns ``(lines, occurrences, blank_lines_removed)``. The file's
    final newline (an empty last element) is kept."""
    out: list[str] = []
    occurrences = removed = 0
    last = len(lines) - 1
    i = 0
    while i < len(lines):
        out.append(lines[i])
        if lines[i].lstrip().startswith("///"):
            j = i + 1
            while j <= last and not lines[j].strip() and not (j == last and lines[j] == ""):
                j += 1
            if j > i + 1:
                occurrences += 1
                removed += j - i - 1
            i = j
            continue
        i += 1
    return out, occurrences, removed


# ---------------------------------------------------------------------------
# M011: simple property after a child block
# ---------------------------------------------------------------------------

SIMPLE_PROPERTIES = frozenset(
    {
        "dataCategory", "dataType", "displayFolder", "displayOrdinal", "formatString",
        "isAvailableInMdx", "isDataTypeInferred", "isDefaultImage", "isDefaultLabel",
        "isHidden", "isKey", "isNameInferred", "isNullable", "lineageTag",
        "sortByColumn", "sourceColumn", "sourceLineageTag", "summarizeBy",
    }
)
# Nested sections of an object. Once one has started, the object's simple
# properties may no longer follow.
CHILD_BLOCKS = frozenset(
    {
        "annotation", "changedProperty", "detailRows", "extendedProperty",
        "formatStringDefinition", "kpi", "relatedColumnDetails",
    }
)
_OBJECT_DECL_RE = re.compile(
    r"^[\t ]*(table|column|measure|partition|hierarchy|level|calculationItem|"
    r"calculationGroup|expression|relationship|role)\b"
)


def first_token(line: str) -> str:
    """The keyword a TMDL line starts with (up to ``:``, space or ``=``)."""
    s = line.strip()
    for sep in (":", " ", "=", "\t"):
        s = s.split(sep, 1)[0]
    return s


@dataclass
class MisorderedProperty:
    line: int  # 0-based index of the offending property line
    target: int  # 0-based index the line belongs in front of
    owner: str  # the declaration line it belongs to, stripped
    token: str


def _expression_end(lines: list[str], decl: int) -> int:
    """0-based index of the last line of the expression a declaration on line
    ``decl`` carries (``decl`` itself when it has none or it is inline)."""
    head = lines[decl]
    level = indent_level(head)
    if _FENCE_OPEN_RE.search(head) and head.count("```", _FENCE_OPEN_RE.search(head).end()) == 0:
        for j in range(decl + 1, len(lines)):
            if lines[j].strip().startswith("```"):
                return j
        return decl
    end = decl
    for j in range(decl + 1, len(lines)):
        text = lines[j]
        if text.strip() == "":
            continue
        if indent_level(text) < level + 2:
            break
        end = j
    return end


def find_properties_after_child_blocks(lines: list[str]) -> list[MisorderedProperty]:
    """Simple properties (``isHidden``, ``displayFolder``...) written after
    one of their object's nested sections (``annotation``, ``kpi``,
    ``formatStringDefinition`` ...). A nested section counts for the closest
    declaration above it; a property counts when it sits exactly one level
    under its declaration. Fenced bodies are skipped.

    ``target`` is the object's first property slot: the line right after its
    expression (or after the declaration when the expression is inline).
    """
    out: list[MisorderedProperty] = []
    # level -> [decl text, section started?, decl index]
    owners: dict[int, list] = {}
    for idx, line in iter_unfenced(lines):
        if not line.strip() or line.lstrip().startswith("///"):
            continue
        level = indent_level(line)
        tok = first_token(line)
        if _OBJECT_DECL_RE.match(line):
            for lvl in [k for k in owners if k >= level]:
                del owners[lvl]
            owners[level] = [line.strip(), False, idx]
            continue
        if tok in CHILD_BLOCKS:
            above = [k for k in owners if k < level]
            if above:
                owners[max(above)][1] = True
            continue
        parent = owners.get(level - 1)
        if parent is None:
            continue
        if tok in SIMPLE_PROPERTIES and parent[1]:
            target = _expression_end(lines, parent[2]) + 1
            out.append(MisorderedProperty(idx, target, parent[0], tok))
    return out


def move_properties_before_child_blocks(
    lines: list[str], limit: int = 200
) -> tuple[list[str], int]:
    """Move every misordered property to its object's first property slot.

    Returns ``(lines, moved)``; ``moved`` is -1 when ``limit`` moves did not
    clear the file (the caller then writes nothing).
    """
    moved = 0
    lines = list(lines)
    while True:
        found = find_properties_after_child_blocks(lines)
        if not found:
            return lines, moved
        if moved >= limit:
            return lines, -1
        f = found[0]
        prop = lines.pop(f.line)
        # removing the line may leave two blank lines in a row; keep one
        if (
            0 < f.line < len(lines)
            and not lines[f.line - 1].strip()
            and not lines[f.line].strip()
        ):
            lines.pop(f.line)
        lines.insert(f.target, prop)
        moved += 1


# ---------------------------------------------------------------------------
# M010: TMDL metadata leaked into an expression
# ---------------------------------------------------------------------------

_LEAK_RE = re.compile(
    r"^(?:"
    r"(?:lineageTag|formatString|displayFolder|dataType|summarizeBy|sortByColumn|"
    r"dataCategory|sourceColumn|sourceLineageTag|isAvailableInMdx|displayOrdinal)"
    r"\s*:\s*\S"
    r"|(?:isHidden|isKey|isNameInferred|isDefaultLabel|isDefaultImage|"
    r"isDataTypeInferred)\s*$"
    r"|(?:annotation|extendedProperty)\s+[^=\s][^=]*="
    r"|changedProperty\s*="
    r"|formatStringDefinition\s*="
    r")"
)

# Keywords that are TMDL metadata, never DAX: a DAX body line that starts
# with one of them, as a whole word, is a property that slipped into the
# expression.
METADATA_KEYWORDS = frozenset(
    {
        "annotation", "changedProperty", "dataCategory", "dataType", "detailRows",
        "displayFolder", "displayOrdinal", "extendedProperty", "formatString",
        "formatStringDefinition", "isAvailableInMdx", "isDataTypeInferred",
        "isDefaultImage", "isDefaultLabel", "isHidden", "isKey", "isNameInferred",
        "kpi", "lineageTag", "relatedColumnDetails", "sortByColumn", "sourceColumn",
        "sourceLineageTag", "summarizeBy",
    }
)
_KEYWORD_RE = re.compile(r"^([A-Za-z]+)(?=$|[\s:=])")


def leaked_property(line: str) -> Optional[str]:
    """The property keyword if ``line`` has the shape of a TMDL property line
    (``key: value``, a bare flag, ``annotation Name = ...``), else None. Used
    for M (Power Query) bodies, where a bare word can be a step name."""
    s = line.strip()
    if _LEAK_RE.match(s):
        return first_token(s)
    return None


def leaked_keyword(line: str) -> Optional[str]:
    """The metadata keyword a DAX body line starts with, whatever follows it
    (``kpi``, ``detailRows = x``, ``displayFolder``), else None."""
    m = _KEYWORD_RE.match(line.strip())
    if m and m.group(1) in METADATA_KEYWORDS:
        return m.group(1)
    return None
