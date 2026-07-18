"""A pragmatic, line-oriented TMDL reader.

TMDL (Tabular Model Definition Language) is the folder-of-text-files format
Power BI Desktop writes when a project is saved as PBIP. This module parses
just enough of it to power the preflight rules:

* table / column / measure / partition declarations and their key properties
* calculated-partition ``source =`` DAX blocks (calculated tables and
  field parameters)
* calculation items and dynamic format-string definitions
* relationships (``relationships.tmdl``)
* every ``lineageTag:`` occurrence, with file/line/context

Design notes
------------
* **Indentation carries structure.** The PBIP serializer indents one tab per
  nesting level, and a multi-line expression body is indented at least two
  levels deeper than its declaration header. Four spaces are accepted as one
  level for hand-edited files.
* **Legacy fences.** Older serializations wrap expressions in ``````` fences
  with inconsistent inner indentation; fence mode collects verbatim until the
  closing fence.
* **This is not a validator of TMDL itself.** Anything unrecognized is
  skipped; unreadable files are surfaced as ``ParseError`` so the
  well-formedness rule can report them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .model import (
    Column,
    LineageTagOccurrence,
    Measure,
    ParseError,
    Partition,
    Relationship,
    SemanticModel,
    Table,
)

_LINEAGE_RE = re.compile(r"^\s*lineageTag:\s*(\S+)")
_DECL_RE = re.compile(
    r"^(?P<indent>[\t ]*)(?P<kw>table|column|measure|partition|calculationItem|"
    r"calculationGroup|formatStringDefinition|hierarchy|level|relationship)\b(?P<rest>.*)$"
)


def indent_level(line: str) -> int:
    """Nesting level of a line: one tab (or four spaces) per level."""
    level = 0
    i = 0
    while i < len(line):
        if line[i] == "\t":
            level += 1
            i += 1
        elif line[i : i + 4] == "    ":
            level += 1
            i += 4
        else:
            break
    return level


def parse_object_name(rest: str) -> tuple[str, str]:
    """Parse the object name that follows a declaration keyword.

    Handles ``'quoted names'`` (with ``''`` escapes), ``"quoted"`` and bare
    names. Returns ``(name, remainder)`` where remainder is whatever follows
    the name (typically ``= <expression>`` or empty).
    """
    rest = rest.lstrip()
    if rest.startswith("'"):
        i = 1
        buf = []
        while i < len(rest):
            if rest[i] == "'":
                if i + 1 < len(rest) and rest[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                break
            buf.append(rest[i])
            i += 1
        return "".join(buf), rest[i:].strip()
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end == -1:
            return rest[1:], ""
        return rest[1:end], rest[end + 1 :].strip()
    # bare name: runs to '=' or end of line
    eq = rest.find("=")
    if eq == -1:
        return rest.strip(), ""
    return rest[:eq].strip(), rest[eq:].strip()


def _collect_expression(
    lines: list[str], start: int, decl_level: int, inline: str
) -> tuple[str, int, int, int]:
    """Collect a (possibly multi-line) expression body.

    ``inline`` is the text after ``=`` on the declaration line. Returns
    ``(expression, next_index, start_line, end_line)`` with 1-based inclusive
    line numbers covering the block (including the inline part's line when
    non-empty).
    """
    inline = inline.strip()
    first_line = start  # 1-based line number of the declaration is start
    if inline.startswith("```"):
        # fenced block: collect verbatim to the closing fence
        parts = []
        j = start
        end_line = start
        while j < len(lines):
            stripped = lines[j].strip()
            if stripped.startswith("```"):
                end_line = j + 1
                j += 1
                break
            parts.append(lines[j])
            end_line = j + 1
            j += 1
        return "\n".join(parts), j, first_line, end_line

    parts = [inline] if inline else []
    j = start
    pending_blanks: list[str] = []
    last_content = start
    while j < len(lines):
        ln = lines[j]
        if not ln.strip():
            pending_blanks.append("")
            j += 1
            continue
        if indent_level(ln) >= decl_level + 2:
            parts.extend(pending_blanks)
            pending_blanks = []
            parts.append(ln)
            last_content = j + 1
            j += 1
            continue
        break
    return "\n".join(parts), j, first_line, last_content


_PROPERTY_RE = re.compile(r"^\s*(?P<key>[A-Za-z][A-Za-z0-9]*)\s*:\s*(?P<value>.*)$")
_FLAG_RE = re.compile(r"^\s*(?P<flag>isHidden|isKey|isActive)\s*$")


def parse_table_file(path: Path) -> tuple[Optional[Table], list[ParseError]]:
    """Parse one ``tables/*.tmdl`` file into a Table (or None on failure)."""
    errors: list[ParseError] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return None, [ParseError(path, f"cannot read file: {exc}")]

    lines = text.splitlines()
    table: Optional[Table] = None
    current: Optional[object] = None  # Column | Measure | Partition
    current_level = 0
    in_calc_group = False

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _DECL_RE.match(line)
        level = indent_level(line)

        if m:
            kw = m.group("kw")
            rest = m.group("rest")
            if kw == "table" and level == 0:
                name, _ = parse_object_name(rest)
                table = Table(name=name, file=path, line=i + 1)
                current = table
                current_level = 0
                i += 1
                continue
            if table is None:
                i += 1
                continue

            if kw == "column" and level == 1:
                name, remainder = parse_object_name(rest)
                col = Column(name=name, table=table.name, file=path, line=i + 1)
                if remainder.startswith("="):
                    expr, i2, _s, _e = _collect_expression(lines, i + 1, level, remainder[1:])
                    col.expression = expr
                    i = i2
                else:
                    i += 1
                table.columns[name] = col
                current, current_level = col, level
                continue

            if kw == "measure" and level == 1:
                name, remainder = parse_object_name(rest)
                meas = Measure(name=name, table=table.name, file=path, line=i + 1)
                if remainder.startswith("="):
                    expr, i2, _s, _e = _collect_expression(lines, i + 1, level, remainder[1:])
                    meas.expression = expr
                    i = i2
                else:
                    i += 1
                table.measures[name] = meas
                current, current_level = meas, level
                continue

            if kw == "partition" and level == 1:
                name, remainder = parse_object_name(rest)
                kind = remainder.lstrip("=").strip().split()[0] if remainder.lstrip("=").strip() else "m"
                part = Partition(
                    name=name, table=table.name, file=path, line=i + 1, kind=kind.lower()
                )
                table.partitions.append(part)
                current, current_level = part, level
                i += 1
                continue

            if kw == "calculationGroup" and level == 1:
                in_calc_group = True
                current, current_level = table, level
                i += 1
                continue

            if kw == "calculationItem" and in_calc_group:
                name, remainder = parse_object_name(rest)
                decl_line = i + 1
                if remainder.startswith("="):
                    expr, i2, _s, _e = _collect_expression(lines, i + 1, level, remainder[1:])
                    i = i2
                else:
                    expr = ""
                    i += 1
                table.calculation_items.append((name, expr, decl_line))
                current, current_level = table, level
                continue

            if kw == "formatStringDefinition":
                _name, remainder = parse_object_name(rest)
                decl_line = i + 1
                owner = table.calculation_items[-1][0] if table.calculation_items else table.name
                if remainder.startswith("="):
                    expr, i2, _s, _e = _collect_expression(lines, i + 1, level, remainder[1:])
                    i = i2
                else:
                    expr = ""
                    i += 1
                table.format_string_definitions.append((owner, expr, decl_line))
                continue

            # hierarchies, levels, nested relationships: skip declaration line
            i += 1
            continue

        # Non-declaration lines: properties of the current object.
        stripped = line.strip()
        if table is not None and "ParameterMetadata" in stripped:
            table.is_field_parameter = True

        if isinstance(current, Partition) and stripped.startswith("source"):
            after = stripped[len("source") :].lstrip()
            if after.startswith("="):
                expr, i2, s, e = _collect_expression(
                    lines, i + 1, indent_level(line), after[1:]
                )
                current.source = expr
                current.source_start_line = i + 2 if not after[1:].strip() else i + 1
                current.source_end_line = e
                i = i2
                continue

        flag = _FLAG_RE.match(line)
        if flag and current is not None:
            name = flag.group("flag")
            if name == "isHidden" and hasattr(current, "is_hidden"):
                current.is_hidden = True
            elif name == "isKey" and hasattr(current, "is_key"):
                current.is_key = True
            i += 1
            continue

        prop = _PROPERTY_RE.match(line)
        if prop and current is not None:
            key, value = prop.group("key"), prop.group("value").strip()
            if key == "lineageTag" and hasattr(current, "lineage_tag"):
                current.lineage_tag = value
            elif key == "dataType" and isinstance(current, Column):
                current.data_type = value
            elif key == "sourceColumn" and isinstance(current, Column):
                current.source_column = value
            elif key == "formatString" and hasattr(current, "format_string"):
                current.format_string = value
        i += 1

    if table is None:
        errors.append(
            ParseError(
                path,
                "no table declaration found: a tables/*.tmdl file must "
                "declare one top-level 'table <name>' block. The file may be "
                "truncated or misplaced; restore it from source control or "
                "move it out of the tables/ folder.",
            )
        )
    return table, errors


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

def parse_endpoint(ref: str) -> tuple[str, str]:
    """Split ``Table.Column`` / ``'Table Name'.Column`` / ``'T'.'C name'``
    into ``(table, column)`` with quote unescaping."""
    ref = ref.strip()
    if ref.startswith("'"):
        i = 1
        buf = []
        while i < len(ref):
            if ref[i] == "'":
                if i + 1 < len(ref) and ref[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                break
            buf.append(ref[i])
            i += 1
        table = "".join(buf)
        column = ref[i:].lstrip(".")
    else:
        table, _, column = ref.partition(".")
    column = column.strip()
    if column.startswith("'") and column.endswith("'") and len(column) >= 2:
        column = column[1:-1].replace("''", "'")
    return table.strip(), column.strip()


def parse_relationships_file(path: Path) -> list[Relationship]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rels: list[Relationship] = []
    current: Optional[Relationship] = None

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if indent_level(line) == 0 and stripped.startswith("relationship "):
            rel_id = stripped[len("relationship ") :].strip()
            current = Relationship(rel_id=rel_id, file=path, line=idx)
            rels.append(current)
            continue
        if current is None or stripped.startswith("//"):
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "fromColumn":
            current.from_table, current.from_column = parse_endpoint(value)
        elif key == "toColumn":
            current.to_table, current.to_column = parse_endpoint(value)
        elif key == "fromCardinality":
            current.from_cardinality = value.lower()
        elif key == "toCardinality":
            current.to_cardinality = value.lower()
        elif key == "crossFilteringBehavior":
            current.cross_filtering = value
        elif key == "isActive":
            current.is_active = value.lower() == "true"

    # keep only relationships with both endpoints parsed
    return [r for r in rels if r.from_table and r.to_table]


# ---------------------------------------------------------------------------
# Lineage tags
# ---------------------------------------------------------------------------

_CONTEXT_RE = re.compile(
    r"^\s*(table|column|measure|partition|relationship|hierarchy)\b\s*(.*)$"
)


def collect_lineage_tags(path: Path) -> list[LineageTagOccurrence]:
    """All ``lineageTag:`` lines in a file, with nearest-declaration context."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []
    occurrences = []
    for idx, line in enumerate(lines):
        m = _LINEAGE_RE.match(line)
        if not m:
            continue
        context = "unknown"
        for back in range(idx - 1, max(-1, idx - 40), -1):
            cm = _CONTEXT_RE.match(lines[back])
            if cm:
                context = f"{cm.group(1)} {cm.group(2).split('=')[0].strip()}".strip()
                break
        occurrences.append(
            LineageTagOccurrence(tag=m.group(1), file=path, line=idx + 1, context=context)
        )
    return occurrences


# ---------------------------------------------------------------------------
# Whole-model entry point
# ---------------------------------------------------------------------------

def parse_model(definition_path: Path) -> SemanticModel:
    """Parse a ``definition/`` folder into a SemanticModel."""
    definition_path = Path(definition_path)
    model = SemanticModel(definition_path=definition_path)

    model.tmdl_files = sorted(definition_path.rglob("*.tmdl"))

    tables_dir = definition_path / "tables"
    if tables_dir.is_dir():
        for tmdl_file in sorted(tables_dir.glob("*.tmdl")):
            table, errors = parse_table_file(tmdl_file)
            model.parse_errors.extend(errors)
            if table is not None:
                model.tables[table.name] = table

    model.relationships = parse_relationships_file(definition_path / "relationships.tmdl")

    for tmdl_file in model.tmdl_files:
        model.lineage_tags.extend(collect_lineage_tags(tmdl_file))

    return model


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

def find_definition_dirs(root: Path) -> list[Path]:
    """Locate semantic-model ``definition/`` folders under (or at) ``root``.

    Accepts: a definition folder itself, a ``*.SemanticModel`` folder, or any
    ancestor folder (for example a PBIP project root) that contains one or more
    ``*.SemanticModel`` folders.
    """
    root = Path(root)
    if root.name == "definition" and (root / "tables").is_dir():
        return [root]
    if root.name.endswith(".SemanticModel"):
        d = root / "definition"
        return [d] if d.is_dir() else []
    found = []
    for sm in sorted(root.rglob("*.SemanticModel")):
        d = sm / "definition"
        if d.is_dir():
            found.append(d)
    return found


def find_report_dirs(root: Path) -> list[Path]:
    """Locate ``*.Report`` folders under (or at) ``root``."""
    root = Path(root)
    if root.name.endswith(".Report"):
        return [root]
    if root.name == "definition" and (root / "tables").is_dir():
        root = root.parent.parent  # definition -> X.SemanticModel -> project
    if root.name.endswith(".SemanticModel"):
        root = root.parent
    return sorted(p for p in root.rglob("*.Report") if p.is_dir())
