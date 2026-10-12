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
    """Delete each dangling run plus one adjacent blank line.

    Mid-file, the blank line that follows the run goes with it. At the end
    of the file, the blank line *before* the run goes instead, so the file
    keeps exactly one trailing newline.
    """
    found = find_dangling_descriptions(lines)
    if not found:
        return lines, 0
    drop: set[int] = set()
    n = len(lines)
    for d in found:
        drop.update(range(d.start, d.end + 1))
        after = d.end + 1
        if not d.at_eof:
            drop.add(after)  # the single blank line that orphaned the run
        elif d.start > 0 and not lines[d.start - 1].strip():
            drop.add(d.start - 1)
        elif after < n - 1 and not lines[after].strip():
            drop.add(after)
    return [ln for k, ln in enumerate(lines) if k not in drop], len(found)


# ---------------------------------------------------------------------------
# M011: simple property after a child block
# ---------------------------------------------------------------------------

SIMPLE_PROPERTIES = frozenset(
    {
        "isHidden", "isKey", "isNameInferred", "isDefaultLabel", "isDefaultImage",
        "isAvailableInMdx", "isNullable", "isDataTypeInferred", "displayFolder",
        "formatString", "summarizeBy", "sortByColumn", "dataType", "dataCategory",
        "displayOrdinal", "lineageTag", "sourceLineageTag", "sourceColumn",
    }
)
CHILD_BLOCKS = frozenset({"annotation", "changedProperty", "extendedProperty"})
_OBJECT_DECL_RE = re.compile(
    r"^[\t ]*(table|column|measure|partition|hierarchy|level|calculationItem|"
    r"calculationGroup|expression|relationship)\b"
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


def find_properties_after_child_blocks(lines: list[str]) -> list[MisorderedProperty]:
    """Simple properties (``isHidden``, ``displayFolder``...) written after
    one of their object's child blocks (``annotation``, ``changedProperty``,
    ``extendedProperty``). Lines inside fences and expression bodies are
    never considered: only the lines exactly one level under a declaration.
    """
    out: list[MisorderedProperty] = []
    # level -> [decl text, first child block index or None]
    owners: dict[int, list] = {}
    for idx, line in iter_unfenced(lines):
        if not line.strip() or line.lstrip().startswith("///"):
            continue
        level = indent_level(line)
        for lvl in [k for k in owners if k >= level]:
            del owners[lvl]
        if _OBJECT_DECL_RE.match(line):
            owners[level] = [line.strip(), None]
            continue
        parent = owners.get(level - 1)
        if parent is None:
            continue
        tok = first_token(line)
        if tok in CHILD_BLOCKS:
            if parent[1] is None:
                parent[1] = idx
        elif tok in SIMPLE_PROPERTIES and parent[1] is not None:
            target = parent[1]
            # land after the last property, before the blank line(s) that
            # usually separate properties from child blocks
            while target > 0 and not lines[target - 1].strip():
                target -= 1
            out.append(MisorderedProperty(idx, target, parent[0], tok))
    return out


def move_properties_before_child_blocks(lines: list[str]) -> tuple[list[str], int]:
    """Move every misordered property up to its object's property section."""
    moved = 0
    lines = list(lines)
    for _ in range(len(lines)):
        found = find_properties_after_child_blocks(lines)
        if not found:
            break
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
    return lines, moved


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


def leaked_property(line: str) -> Optional[str]:
    """The property keyword if ``line`` is a TMDL property line, else None."""
    s = line.strip()
    if _LEAK_RE.match(s):
        return first_token(s)
    return None
