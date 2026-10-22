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
* ``///`` descriptions, display folders, measure-level format-string
  definitions and ``refreshPolicy`` placement
* ``expressions.tmdl`` (names and ``meta`` records) and the model-level
  facts in ``model.tmdl`` (``ref table`` lines, ``discourageImplicitMeasures``)

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
* **Nothing is dropped silently.** Duplicate declarations are kept (the
  name-keyed dicts hold the first, the lists hold all), relationships with
  a missing endpoint are kept for R001, and a raw count of declaration lines
  is compared with what was parsed so a structural miss surfaces as M002.
* Files are read as ``utf-8-sig``, so a byte-order mark never hides the
  first declaration.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .model import (
    Column,
    Expression,
    LineageTagOccurrence,
    Measure,
    ModelInfo,
    ParseError,
    Partition,
    RefreshPolicy,
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
        return "".join(buf).strip(), rest[i:].strip()
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end == -1:
            return rest[1:].strip(), ""
        return rest[1:end].strip(), rest[end + 1 :].strip()
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
_DESC_RE = re.compile(r"^\s*///(?P<text>.*)$")

# Raw declaration lines, counted independently of the structural walk so the
# parser can notice when it failed to attach a declaration to its table (for
# example a mis-indented measure swallowed by the previous expression).
_RAW_TABLE_MEMBER_RE = re.compile(r"^[\t ]*(?:measure|column)[\t ]+\S")
_RAW_RELATIONSHIP_RE = re.compile(r"^[\t ]*relationship[\t ]+\S")


def read_tmdl_text(path: Path) -> str:
    """Read a TMDL file as UTF-8, tolerating a byte-order mark."""
    return path.read_text(encoding="utf-8-sig")


def _expression_start(decl_line: int, inline: str) -> int:
    """1-based line on which an expression's text starts."""
    inline = inline.strip()
    if inline and not inline.startswith("```"):
        return decl_line
    return decl_line + 1


def count_raw_declarations(text: str, pattern: "re.Pattern[str]") -> int:
    """Count lines matching ``pattern`` outside ``` fences."""
    count = 0
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_fence:
            if stripped.startswith("```"):
                in_fence = False
            continue
        if pattern.match(line):
            count += 1
        if stripped.endswith("```") and stripped.count("```") % 2 == 1:
            in_fence = True
    return count


def _name_problem(rest: str, name: str, remainder: str, kw: str) -> Optional[tuple[str, str]]:
    """Diagnose a declaration name the parser had to guess at.

    Returns ``(severity, message)`` or None. Text left over after a quoted
    name that is neither empty nor an ``=`` means the quoting is broken (a
    lone apostrophe inside ``'...'`` must be doubled); an empty name is legal
    to read but cannot be referenced.
    """
    stripped = rest.strip()
    if stripped.startswith(("'", '"')) and remainder and not remainder.startswith("="):
        return (
            "error",
            f"{kw} name {stripped.split(chr(10))[0][:60]!r} is not quoted correctly: "
            f"text follows the closing quote. Inside a quoted TMDL name an "
            f"apostrophe must be written twice ('Rider''s Name').",
        )
    if not name:
        return (
            "warning",
            f"{kw} has an empty name, so no DAX expression or visual can refer "
            f"to it. Give it a name or delete it.",
        )
    return None


def parse_table_file(path: Path) -> tuple[Optional[Table], list[ParseError]]:
    """Parse one ``tables/*.tmdl`` file into a Table (or None on failure)."""
    errors: list[ParseError] = []
    try:
        text = read_tmdl_text(path)
    except (UnicodeDecodeError, OSError) as exc:
        return None, [ParseError(path, f"cannot read file: {exc}")]

    lines = text.splitlines()
    table: Optional[Table] = None
    # owners[level] is the object whose properties sit at level + 1; None
    # marks a block the parser does not model (hierarchy, calculationGroup...)
    owners: dict[int, object] = {}
    in_calc_group = False
    calc_item_level: Optional[int] = None
    pending_desc: list[str] = []

    def set_owner(level: int, obj: object) -> None:
        for lvl in [k for k in owners if k >= level]:
            del owners[lvl]
        owners[level] = obj

    def take_description() -> Optional[str]:
        nonlocal pending_desc
        if not pending_desc:
            return None
        desc = "\n".join(d.strip() for d in pending_desc).strip()
        pending_desc = []
        return desc

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            pending_desc = []
            i += 1
            continue
        dm = _DESC_RE.match(line)
        if dm:
            pending_desc.append(dm.group("text"))
            i += 1
            continue
        m = _DECL_RE.match(line)
        level = indent_level(line)

        if m:
            kw = m.group("kw")
            rest = m.group("rest")
            desc = take_description()
            if kw == "table" and level == 0:
                name, remainder = parse_object_name(rest)
                problem = _name_problem(rest, name, remainder, "table")
                if problem:
                    errors.append(ParseError(path, problem[1], i + 1, problem[0]))
                table = Table(name=name, file=path, line=i + 1, description=desc)
                set_owner(0, table)
                i += 1
                continue
            if table is None:
                i += 1
                continue

            if kw == "column" and level == 1:
                name, remainder = parse_object_name(rest)
                problem = _name_problem(rest, name, remainder, "column")
                if problem:
                    errors.append(ParseError(path, problem[1], i + 1, problem[0]))
                col = Column(
                    name=name, table=table.name, file=path, line=i + 1, description=desc
                )
                if remainder.startswith("="):
                    expr, i2, _s, _e = _collect_expression(lines, i + 1, level, remainder[1:])
                    col.expression = expr
                    col.expression_line = _expression_start(i + 1, remainder[1:])
                    col.expression_missing = not remainder[1:].strip()
                    i = i2
                else:
                    i += 1
                table.add_column(col)
                set_owner(level, col)
                continue

            if kw == "measure" and level == 1:
                name, remainder = parse_object_name(rest)
                problem = _name_problem(rest, name, remainder, "measure")
                if problem:
                    errors.append(ParseError(path, problem[1], i + 1, problem[0]))
                meas = Measure(
                    name=name, table=table.name, file=path, line=i + 1, description=desc
                )
                if remainder.startswith("="):
                    expr, i2, _s, _e = _collect_expression(lines, i + 1, level, remainder[1:])
                    meas.expression = expr
                    meas.expression_line = _expression_start(i + 1, remainder[1:])
                    i = i2
                else:
                    i += 1
                table.add_measure(meas)
                set_owner(level, meas)
                continue

            if kw == "partition" and level == 1:
                name, remainder = parse_object_name(rest)
                kind = remainder.lstrip("=").strip().split()[0] if remainder.lstrip("=").strip() else "m"
                part = Partition(
                    name=name, table=table.name, file=path, line=i + 1, kind=kind.lower()
                )
                table.partitions.append(part)
                set_owner(level, part)
                i += 1
                continue

            if kw == "calculationGroup" and level == 1:
                in_calc_group = True
                table.is_calculation_group = True
                set_owner(level, None)
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
                table.calculation_item_starts.append(
                    _expression_start(decl_line, remainder[1:] if remainder.startswith("=") else "")
                )
                calc_item_level = level
                set_owner(level, None)
                continue

            if kw == "formatStringDefinition":
                _name, remainder = parse_object_name(rest)
                decl_line = i + 1
                parent = owners.get(level - 1)
                if isinstance(parent, Measure):
                    owner = parent.name
                elif (
                    calc_item_level is not None
                    and level == calc_item_level + 1
                    and table.calculation_items
                ):
                    owner = table.calculation_items[-1][0]
                    table.dynamic_format_items.append(owner)
                else:
                    owner = table.name
                inline = remainder[1:] if remainder.startswith("=") else ""
                if remainder.startswith("="):
                    expr, i2, _s, _e = _collect_expression(lines, i + 1, level, inline)
                    i = i2
                else:
                    expr = ""
                    i += 1
                if isinstance(parent, Measure):
                    parent.format_string_definition = expr
                table.format_string_definitions.append((owner, expr, decl_line))
                table.format_string_definition_starts.append(
                    _expression_start(decl_line, inline)
                )
                continue

            # hierarchies, levels, nested relationships: skip declaration line
            set_owner(level, None)
            i += 1
            continue

        pending_desc = []
        # Non-declaration lines: properties of the object one level up.
        stripped = line.strip()
        if table is not None and "ParameterMetadata" in stripped:
            table.is_field_parameter = True

        current = owners.get(level - 1)

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

        if table is not None and stripped == "refreshPolicy" and level == 1:
            policy = RefreshPolicy(file=path, line=i + 1, level=level)
            table.refresh_policy = policy
            set_owner(level, policy)
            i += 1
            continue

        if isinstance(current, RefreshPolicy):
            key, sep, value = stripped.partition(":")
            if not sep:
                key, sep, value = stripped.partition("=")
            if sep:
                current.properties[key.strip()] = value.strip()
            i += 1
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
            elif key == "displayFolder" and hasattr(current, "display_folder"):
                current.display_folder = value
        if stripped.split(" ", 1)[0] in ("annotation", "extendedProperty", "changedProperty"):
            # child blocks: their own (deeper) lines are not object properties
            set_owner(level, None)
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
    else:
        declared = count_raw_declarations(text, _RAW_TABLE_MEMBER_RE)
        parsed = len(table.column_list) + len(table.measure_list)
        if declared > parsed:
            errors.append(
                ParseError(
                    path,
                    f"parser dropped {declared - parsed} object(s): the file "
                    f"has {declared} 'column'/'measure' declaration lines but "
                    f"only {parsed} could be attached to table '{table.name}'. "
                    f"A declaration is usually mis-indented (one tab per "
                    f"level: columns and measures sit one level under the "
                    f"table) or buried inside the previous expression; fix "
                    f"the indentation so every object is visible to the model.",
                )
            )
    return table, errors


# ---------------------------------------------------------------------------
# expressions.tmdl and model.tmdl
# ---------------------------------------------------------------------------

_EXPRESSION_DECL_RE = re.compile(r"^expression\b(?P<rest>.*)$")
_META_RE = re.compile(r"\bmeta\s*\[(?P<body>.*)\]\s*$", re.DOTALL)


def _parse_meta(expression: str) -> dict[str, str]:
    """Parse the trailing ``meta [Key = value, ...]`` record of an M
    expression into a dict of raw values (quotes removed)."""
    m = _META_RE.search(expression.strip())
    if not m:
        return {}
    body = m.group("body")
    parts: list[str] = []
    buf: list[str] = []
    in_str = False
    for ch in body:
        if ch == '"':
            in_str = not in_str
        if ch == "," and not in_str:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    meta: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('""', '"')
        meta[key.strip()] = value
    return meta


def parse_expressions_file(path: Path) -> tuple[list[Expression], list[ParseError]]:
    """Parse ``expressions.tmdl``: shared expressions and parameters."""
    if not path.exists():
        return [], []
    try:
        lines = read_tmdl_text(path).splitlines()
    except (UnicodeDecodeError, OSError) as exc:
        return [], [ParseError(path, f"cannot read file: {exc}")]
    out: list[Expression] = []
    current: Optional[Expression] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _EXPRESSION_DECL_RE.match(line)
        if m:
            name, remainder = parse_object_name(m.group("rest"))
            current = Expression(name=name, file=path, line=i + 1)
            if remainder.startswith("="):
                expr, i2, _s, _e = _collect_expression(lines, i + 1, 0, remainder[1:])
                current.expression = expr
                current.meta = _parse_meta(expr)
                i = i2
            else:
                i += 1
            out.append(current)
            continue
        if current is not None and indent_level(line) == 1:
            lm = _LINEAGE_RE.match(line)
            if lm:
                current.lineage_tag = lm.group(1)
        i += 1
    return out, []


_REF_TABLE_LINE_RE = re.compile(r"^\s*ref\s+table\s+(?P<rest>.+?)\s*$")


def parse_model_file(path: Path) -> ModelInfo:
    """Read the model-level facts the rules need from ``model.tmdl``."""
    info = ModelInfo(file=path)
    try:
        lines = read_tmdl_text(path).splitlines()
    except (UnicodeDecodeError, OSError):
        return info
    in_model = False
    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        level = indent_level(line)
        stripped = line.strip()
        if level == 0:
            in_model = stripped.startswith("model ")
            if in_model:
                info.name, _ = parse_object_name(stripped[len("model "):])
            rm = _REF_TABLE_LINE_RE.match(line)
            if rm:
                name, _ = parse_object_name(rm.group("rest"))
                info.ref_tables.append((name, idx))
            continue
        if in_model and level == 1 and stripped == "discourageImplicitMeasures":
            info.discourage_implicit_measures = True
    return info


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


def parse_relationships(
    path: Path,
) -> tuple[list[Relationship], list[Relationship], list[ParseError]]:
    """Parse ``relationships.tmdl``.

    Returns ``(relationships, malformed, errors)``: well-formed relationships,
    the ones missing an endpoint (reported by R001, never dropped silently),
    and read/sanity errors (reported by M002).
    """
    if not path.exists():
        return [], [], []
    try:
        text = read_tmdl_text(path)
    except (UnicodeDecodeError, OSError) as exc:
        return [], [], [ParseError(path, f"cannot read file: {exc}")]
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

    good = [r for r in rels if r.from_table and r.to_table and r.from_column and r.to_column]
    malformed = [r for r in rels if r not in good]
    errors: list[ParseError] = []
    declared = count_raw_declarations(text, _RAW_RELATIONSHIP_RE)
    if declared > len(rels):
        errors.append(
            ParseError(
                path,
                f"parser dropped {declared - len(rels)} object(s): the file has "
                f"{declared} 'relationship' declaration lines but only "
                f"{len(rels)} start at the top level. Relationship "
                f"declarations must not be indented; fix the indentation so "
                f"every relationship is part of the model.",
            )
        )
    return good, malformed, errors


def parse_relationships_file(path: Path) -> list[Relationship]:
    """Well-formed relationships only (kept for API compatibility)."""
    return parse_relationships(path)[0]


# ---------------------------------------------------------------------------
# Lineage tags
# ---------------------------------------------------------------------------

_CONTEXT_RE = re.compile(
    r"^\s*(table|column|measure|partition|relationship|hierarchy|level|expression|"
    r"calculationItem|role|culture|perspective)\b\s*(.*)$"
)


def collect_lineage_tags(path: Path) -> list[LineageTagOccurrence]:
    """All ``lineageTag:`` lines in a file, with nearest-declaration context."""
    try:
        lines = read_tmdl_text(path).splitlines()
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
                model.add_table(table)

    rels, malformed, rel_errors = parse_relationships(
        definition_path / "relationships.tmdl"
    )
    model.relationships = rels
    model.malformed_relationships = malformed
    model.parse_errors.extend(rel_errors)

    expressions, expr_errors = parse_expressions_file(definition_path / "expressions.tmdl")
    model.expressions = expressions
    model.parse_errors.extend(expr_errors)

    model.info = parse_model_file(definition_path / "model.tmdl")

    for tmdl_file in model.tmdl_files:
        model.lineage_tags.extend(collect_lineage_tags(tmdl_file))

    return model


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

def is_definition_dir(folder: Path) -> bool:
    """A ``definition/`` folder holds ``tables/``, ``model.tmdl`` or
    ``expressions.tmdl`` (a partial export still counts, so the rules can say
    what is missing)."""
    folder = Path(folder)
    return (
        (folder / "tables").is_dir()
        or (folder / "model.tmdl").is_file()
        or (folder / "expressions.tmdl").is_file()
    )


def find_definition_dirs(root: Path) -> list[Path]:
    """Locate semantic-model ``definition/`` folders under (or at) ``root``.

    Accepts: a definition folder itself, a ``*.SemanticModel`` folder, or any
    ancestor folder (for example a PBIP project root) that contains one or more
    ``*.SemanticModel`` folders.
    """
    root = Path(root)
    if root.name == "definition" and is_definition_dir(root):
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
    if root.name == "definition" and is_definition_dir(root):
        root = root.parent.parent  # definition -> X.SemanticModel -> project
    if root.name.endswith(".SemanticModel"):
        root = root.parent
    return sorted(p for p in root.rglob("*.Report") if p.is_dir())
