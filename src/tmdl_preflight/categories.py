"""Analysis categories: the encoded mapping table, the axis rows that feed
it, and which fact tables each category reaches.

The mapping table (by default ``z-Map Dimension-Measure Groupings``) is an
entered-data table. Desktop stores its rows in the M partition as a base64
string of raw-DEFLATE-compressed JSON (``Binary.FromText("...")`` inside
``Binary.Decompress``). Each row is ``[category, subcategory, group id]`` (or
``[category, group id]``): the group id is the category value written in
position 4 of the axis field-parameter rows. One group may belong to several
categories, so every map here is many-to-many.

This module is shared by the mapping-table rules, the ``f-All`` gate rule
and ``tmdl-preflight info --categories``.
"""

from __future__ import annotations

import base64
import json
import re
import zlib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Iterable, Optional

from .edits import TextFile, read_text_file
from .fieldparams import mask_line, source_span
from .model import Measure, SemanticModel, Table
from .roles import fact_tables

MAPPING_TABLE = "z-Map Dimension-Measure Groupings"
MAPPING_PREFIX = "z-Map"
#: The numbered x-axis tables alone: the category attribution and the
#: category-mechanism exemption read their axis rows from these by default.
NUMBERED_X_AXIS_GLOBS = ["x-Selector [1-9]"]
ALL_AXIS_GLOBS = ["x-Selector*", "x-Plot Specific*", "y-Selector*", "y-Plot Specific*"]
# axis spacers and the standard calendar groups attribute nothing
NON_ATTRIBUTING_GROUPS = ["Blank Measure_x", "Blank Dimension_y", "Date_y", "Date_day_y", "Date_week_y"]

_BLOB_RE = re.compile(r'Binary\.FromText\(\s*"(?P<blob>[A-Za-z0-9+/=\s]*)"')


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class MappingDecodeError(ValueError):
    """The table holds no readable encoded payload."""

    def __init__(self, message: str, *, no_payload: bool = False):
        super().__init__(message)
        self.no_payload = no_payload


def decode_rows(blob: str) -> list[list]:
    raw = base64.b64decode("".join(blob.split()))
    data = json.loads(zlib.decompress(raw, -zlib.MAX_WBITS).decode("utf-8"))
    if not isinstance(data, list) or not all(isinstance(r, list) for r in data):
        raise MappingDecodeError("payload is not a list of rows")
    return data


def encode_rows(rows: list[list]) -> str:
    """The payload as the table stores it: JSON with a comma and a space
    between items, a colon and a space between keys, non-ASCII escaped."""
    payload = json.dumps(rows, ensure_ascii=True, separators=(", ", ": ")).encode("utf-8")
    packer = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    return base64.b64encode(packer.compress(payload) + packer.flush()).decode("ascii")


@dataclass
class MappingTable:
    table: Table
    file: TextFile
    blob_start: int  # offset of the payload inside ``file.text``
    blob_end: int
    rows: list[list]

    @property
    def width(self) -> int:
        widths = [len(r) for r in self.rows if r]
        return max(set(widths), key=widths.count) if widths else 3

    def categories(self) -> list[str]:
        out: list[str] = []
        for row in self.rows:
            if row and isinstance(row[0], str) and row[0].strip() and row[0] not in out:
                out.append(row[0])
        return out

    def groups_of(self, category: str) -> set[str]:
        return {g for r in self.rows if len(r) >= 2 and _cell(r[0]) == category
                for g in [_cell(r[-1])] if g}

    def with_rows(self, rows: list[list]) -> str:
        text = self.file.text
        return text[: self.blob_start] + encode_rows(rows) + text[self.blob_end:]


def read_mapping(table: Table) -> MappingTable:
    """Decode the table's encoded payload (raises MappingDecodeError).

    The first payload in the file is the one that counts.
    """
    try:
        tf = read_text_file(table.file)
    except (OSError, UnicodeDecodeError) as exc:
        raise MappingDecodeError(str(exc)) from exc
    blobs = list(_BLOB_RE.finditer(tf.text))
    if not blobs:
        raise MappingDecodeError("no binary data found", no_payload=True)
    m = blobs[0]
    try:
        rows = decode_rows(m.group("blob"))
    except (ValueError, zlib.error, UnicodeDecodeError) as exc:
        raise MappingDecodeError(str(exc)) from exc
    return MappingTable(table, tf, m.start("blob"), m.end("blob"), rows)


def find_mapping_table(model: SemanticModel, name: Optional[str] = None,
                       prefix: Optional[str] = None) -> Optional[Table]:
    if name:
        return model.get_table(name)
    pre = prefix or MAPPING_PREFIX
    for t in sorted(model.table_list, key=lambda t: t.file.name):
        if t.name.startswith(pre):
            return t
    return None


def load_mapping(model: SemanticModel, name: Optional[str] = None,
                 prefix: Optional[str] = None) -> Optional[MappingTable]:
    table = find_mapping_table(model, name, prefix)
    if table is None:
        return None
    try:
        return read_mapping(table)
    except MappingDecodeError:
        return None


def _cell(value) -> str:
    """A cell's text; a null cell counts as empty."""
    if value is None:
        return ""
    return str(value).strip()


def category_map(rows: Iterable[list], excluded: Iterable[str] = NON_ATTRIBUTING_GROUPS) -> dict[str, set[str]]:
    """group id -> categories, skipping blank values and excluded groups.

    Only rows with three or more values count: the category is the first
    value and the group id the third.
    """
    skip = set(excluded)
    out: dict[str, set[str]] = {}
    for row in rows:
        if len(row) < 3:
            continue
        cat, group = _cell(row[0]), _cell(row[2])
        if not cat or not group or group in skip:
            continue
        out.setdefault(group, set()).add(cat)
    return out


# ---------------------------------------------------------------------------
# Axis rows
# ---------------------------------------------------------------------------


@dataclass
class AxisRow:
    table: str
    line: int  # 1-based
    label: str
    ref: str  # the NAMEOF field as written
    qualifier: Optional[str]
    target: str
    group: Optional[str]
    width: int


#: A row the attribution reader accepts:
#: ``("label", NAMEOF('Table'[Measure]) or NAMEOF([Measure]), order, "group")``.
_AXIS_ENTRY_RE = re.compile(
    r'\(\s*"(?P<label>[^"]+)"\s*,\s*(?P<ref>NAMEOF\s*\(\s*(?:'
    r"'(?P<qual>[^']+)'\[(?P<qname>[^\]]+)\]"
    r'|\[(?P<name>[^\]]+)\]'
    r')\s*\))\s*,\s*(?P<order>-?\d+)\s*,\s*"(?P<group>[^"]+)"')

#: A row of four or five values whose fourth (and fifth) value is a quoted
#: string: the shape the group inventory counts.
_AXIS_GROUP_RE = re.compile(
    r'\(\s*"[^"]+"\s*,\s*NAMEOF\s*\([^)]+\)\s*,\s*-?\d+\s*,\s*"(?P<group>[^"]+)"'
    r'(?:\s*,\s*"[^"]+")?\s*\)')


def _live_at(text: str, offset: int) -> bool:
    """Is the character at ``offset`` outside a comment marker?"""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    line = text[start:] if end < 0 else text[start:end]
    col = offset - start
    return mask_line(line)[col:col + 1] == "("


def _axis_sources(model: SemanticModel, globs: Iterable[str]):
    """(table, source text, first source line) for every table a glob names."""
    pats = list(globs)
    for t in model.table_list:
        if not any(fnmatchcase(t.name, p) for p in pats):
            continue
        try:
            lines = read_text_file(t.file).lines()
        except (OSError, UnicodeDecodeError):
            continue
        span = source_span(lines)
        if span is None:
            continue
        yield t, "\n".join(lines[span[0]:span[1]]), span[0]


def axis_rows(model: SemanticModel, globs: Iterable[str]) -> list[AxisRow]:
    """The live axis rows of every table a glob names.

    A row is ``("label", NAMEOF('Table'[Measure]) or NAMEOF([Measure]),
    <order>, "group")``; a row behind a ``//`` or ``--`` marker is not a row.
    """
    out: list[AxisRow] = []
    for t, source, first_line in _axis_sources(model, globs):
        for m in _AXIS_ENTRY_RE.finditer(source):
            if not _live_at(source, m.start()):
                continue
            qual = m.group("qual")
            target = m.group("qname") if qual is not None else m.group("name")
            line = first_line + source.count("\n", 0, m.start()) + 1
            out.append(AxisRow(t.name, line, m.group("label"), m.group("ref"),
                               qual, target.strip(), m.group("group"), 4))
    return out


def axis_group_ids(model: SemanticModel, globs: Iterable[str]) -> list[str]:
    """The group ids the axis rows carry: the fourth value of a row with
    four or five values."""
    out: list[str] = []
    for t, source, _first in _axis_sources(model, globs):
        for m in _AXIS_GROUP_RE.finditer(source):
            if not _live_at(source, m.start()):
                continue
            out.append(m.group("group"))
    return out


# ---------------------------------------------------------------------------
# Measure -> fact trace
# ---------------------------------------------------------------------------

#: A bracketed reference; the text may not span a line break.
_MEASURE_REF_RE = re.compile(r"\[([^\]\n]+)\]")


def _measure_refs(expr: str) -> set[str]:
    """The measure names an expression references.

    A bare ``[Name]`` and a qualified ``'Table'[Name]`` (or
    ``Table[Name]``) are the same reference when ``Name`` is a measure the
    model declares. The qualifier is how a model says which table owns the
    measure; it does not change what the reference means.
    """
    return {m.group(1).strip() for m in _MEASURE_REF_RE.finditer(expr)}


def _direct_facts(expr: str, facts: list[str]) -> set[str]:
    hits = set()
    for name in facts:
        quoted = "'" + name.replace("'", "''") + "'"
        if quoted in expr or f"[{name}]" in expr:
            hits.add(name)
        elif " " not in name and f"{name}[" in expr:
            hits.add(name)
    return hits


class FactTracer:
    """Transitive fact tables behind each measure (through ``[Measure]``
    references), memoised per model."""

    def __init__(self, model: SemanticModel, facts: Optional[list[str]] = None):
        self.model = model
        self.facts = facts if facts is not None else fact_tables(model)
        self.by_name: dict[str, Measure] = {}
        for m in model.all_measures():
            self.by_name[m.name] = m
        self._direct: dict[str, set[str]] = {}
        self._edges: dict[str, set[str]] = {}

    def _prepare(self, name: str) -> None:
        if name in self._direct:
            return
        expr = self.by_name[name].expression or ""
        self._direct[name] = _direct_facts(expr, self.facts)
        self._edges[name] = {r for r in _measure_refs(expr)
                             if r in self.by_name and r != name}

    def trace(self, name: str) -> set[str]:
        if name not in self.by_name:
            return set()
        seen, stack, out = {name}, [name], set()
        while stack:
            cur = stack.pop()
            self._prepare(cur)
            out |= self._direct[cur]
            for nxt in self._edges[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return out


def fact_table_categories(model: SemanticModel, mapping: Optional[MappingTable],
                          axis_globs: Iterable[str] = NUMBERED_X_AXIS_GLOBS,
                          excluded: Iterable[str] = NON_ATTRIBUTING_GROUPS) -> dict[str, set[str]]:
    """Every fact table -> the categories its measures are offered under."""
    tracer = FactTracer(model)
    out: dict[str, set[str]] = {f: set() for f in tracer.facts}
    if mapping is None:
        return out
    cmap = category_map(mapping.rows, excluded)
    for row in axis_rows(model, axis_globs):
        cats = cmap.get(row.group or "")
        if not cats or row.target not in tracer.by_name:
            continue
        for fact in tracer.trace(row.target):
            out.setdefault(fact, set()).update(cats)
    return out


def category_backing(model: SemanticModel, mapping: MappingTable,
                     axis_globs: Iterable[str] = NUMBERED_X_AXIS_GLOBS,
                     excluded: Iterable[str] = NON_ATTRIBUTING_GROUPS,
                     tracer: Optional[FactTracer] = None) -> dict[str, set[str]]:
    """category -> fact tables reached by the measures of its groups (only
    categories with at least one traceable measure appear)."""
    tracer = tracer or FactTracer(model)
    cmap = category_map(mapping.rows, excluded)
    out: dict[str, set[str]] = {}
    for row in axis_rows(model, axis_globs):
        cats = cmap.get(row.group or "")
        if not cats or row.target not in tracer.by_name:
            continue
        facts = tracer.trace(row.target)
        for cat in cats:
            out.setdefault(cat, set()).update(facts)
    return out


# ---------------------------------------------------------------------------
# f-All gate chains
# ---------------------------------------------------------------------------

#: A gate literal: ``CONTAINSSTRING(all_cats, "<literal>")``, spelled the way
#: the source tool spells it.
_GATE_LITERAL_RE = re.compile(r'CONTAINSSTRING\(all_cats,\s*"([^"]+)"\)')
#: A gate call: ``IF([f-X] > 0``.
_GATE_MEASURE_RE = re.compile(r"IF\(\[(f-[^\]]+)\]\s*>\s*0")
#: A declared filter measure: one tab of indentation, then the name.
_DECL_RE = re.compile(r"^\tmeasure\s+(?:'(f-[^']+)'|(f-[^\s=]+))\s*=")


def _live(line: str) -> bool:
    return not line.strip().startswith(("//", "--"))


def chain_body(text: str, var: str, stop: str) -> Optional[str]:
    """Text of ``VAR <var> =`` up to the next line that starts (after
    indentation) with ``stop`` (a regular expression).

    The source tool spells the chain in upper case and stops it at a line
    break; a lower-case ``var`` or a different spelling is not a chain.
    """
    m = re.search(r"VAR\s+" + re.escape(var) + r"\s*=\s*", text)
    if not m:
        return None
    rest = text[m.end():]
    end = re.search(r"\n\s*(?:" + stop + r")", rest)
    return rest[: end.start()] if end else rest


def gate_literals(body: str) -> list[str]:
    out: list[str] = []
    for line in body.split("\n"):
        if not _live(line):
            continue
        for m in _GATE_LITERAL_RE.finditer(line):
            lit = m.group(1)
            if lit not in out:
                out.append(lit)
    return out


def gate_measure_calls(text: str) -> list[tuple[int, str]]:
    """``(1-based line, measure)`` for each live ``IF([f-X] > 0`` in ``text``."""
    out = []
    for idx, line in enumerate(text.split("\n"), start=1):
        if _live(line):
            out.extend((idx, m.group(1)) for m in _GATE_MEASURE_RE.finditer(line))
    return out


def declared_gate_measures(text: str, prefix: str = "f-") -> list[str]:
    """Measures declared at one tab of indentation whose name starts with
    ``prefix`` (quoted or bare)."""
    out = []
    for line in text.split("\n"):
        m = _DECL_RE.match(line.rstrip("\r"))
        if not m:
            continue
        name = m.group(1) or m.group(2)
        if name.startswith(prefix):
            out.append(name)
    return out


def resolve_gate_measure(category: str, declared: Iterable[str], prefix: str = "f-") -> Optional[str]:
    names = set(declared)
    for candidate in (prefix + category, prefix + category.replace(" ", "_"),
                      prefix + category.replace(" ", "")):
        if candidate in names:
            return candidate
    return None
