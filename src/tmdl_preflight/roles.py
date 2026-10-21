"""Table roles: which tables are facts, dimensions, selectors or measure
containers.

One shared definition for every rule that needs to know the facts (dead
facts, the conformed-dimension join, refresh-policy coverage, measures on
facts, calendar coverage). It is derived from the model itself, never from a
curated list:

*Name law* (first match wins): a name starting with ``_`` is a *distinct*
table (dimension, calendar, scaffolding); one letter followed by ``-``
(``x-``, ``z-``, ``f-``) is a *selector*; a first character that is not
alphanumeric, or the whole word ``Measure``/``Measures``, makes a *measures
container*; anything else is a *fact candidate*.

*Structure law*: a fact candidate is a fact only if it has at least one
column, is not a calculation group, is not a field parameter, its first
partition is an M partition, and its file does not author rows inline
(``Table.FromRows`` or ``#table(``).
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from .dax import extract_nameof_references
from .model import SemanticModel, Table

_SELECTOR_RE = re.compile(r"^[A-Za-z]-")
_MEASURES_WORD_RE = re.compile(r"\bmeasures?\b", re.IGNORECASE)
_FIELD_PARAM_SOURCE_RE = re.compile(r"sourceColumn:\s*\[Value\d+\]")
_INLINE_ROWS_RE = re.compile(r"Table\.FromRows|#table\s*\(", re.IGNORECASE)

DISTINCT = "distinct"
SELECTOR = "selector"
CONTAINER = "container"
FACT_CANDIDATE = "fact_candidate"


def name_role(name: str) -> str:
    """Role of a table by its name alone."""
    if name.startswith("_"):
        return DISTINCT
    if _SELECTOR_RE.match(name):
        return SELECTOR
    if not name[:1].isalnum() or _MEASURES_WORD_RE.search(name):
        return CONTAINER
    return FACT_CANDIDATE


def _file_text(table: Table) -> Optional[str]:
    try:
        return table.file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def is_field_parameter_file(text: str) -> bool:
    return "groupByColumn" in text and bool(_FIELD_PARAM_SOURCE_RE.search(text))


def is_fact(table: Table, exclusions: Iterable[str] = ()) -> bool:
    """Name law plus structure law (see the module docstring)."""
    if name_role(table.name) != FACT_CANDIDATE:
        return False
    if any(re.search(p, table.name) for p in exclusions):
        return False
    if not table.column_list or table.is_calculation_group:
        return False
    if not table.partitions or table.partitions[0].kind != "m":
        return False
    text = _file_text(table)
    if text is None:
        return True  # an unreadable file is not disqualified
    if is_field_parameter_file(text):
        return False
    return not _INLINE_ROWS_RE.search(text)


def fact_tables(model: SemanticModel, exclusions: Iterable[str] = ()) -> list[str]:
    """Names of the model's fact tables, in table order."""
    return [t.name for t in model.table_list if is_fact(t, exclusions)]


# ---------------------------------------------------------------------------
# Field-parameter tables and the measures they surface
# ---------------------------------------------------------------------------


def is_field_parameter_table(table: Table) -> bool:
    """A table built as a field parameter: Desktop's ParameterMetadata
    marker, or a calculated table whose source lists NAMEOF tuples."""
    if table.is_field_parameter:
        return True
    for p in table.partitions:
        if p.kind == "calculated" and p.source and "NAMEOF" in p.source.upper():
            return True
    return False


def _matches(name: str, patterns: Iterable[str]) -> bool:
    from fnmatch import fnmatchcase

    return any(fnmatchcase(name, p) or name == p for p in patterns)


def field_parameter_tables(model: SemanticModel, patterns: Optional[Iterable[str]] = None) -> list[Table]:
    """Field-parameter tables of the model; with ``patterns`` (names or
    globs), exactly the tables those name."""
    if patterns:
        pats = list(patterns)
        return [t for t in model.table_list if _matches(t.name, pats)]
    return [t for t in model.table_list if is_field_parameter_table(t)]


def surfaced_measures(model: SemanticModel, patterns: Optional[Iterable[str]] = None) -> set[str]:
    """Distinct measure names referenced as bare ``NAMEOF([Name])`` in the
    text of the field-parameter tables (comments excluded).

    With no ``patterns`` the set comes from the NUMBERED x-axis tables
    (``x-Selector 1`` to ``x-Selector 9``) only: those are the tables that
    surface a fact measure to the report. A y-axis or a plot-specific
    table does not make a fact measure user-facing by default.
    """
    out: set[str] = set()
    for t in field_parameter_tables(model, patterns):
        if patterns is None and not _numbered_x_axis(t.name):
            continue
        text = _file_text(t)
        if text is None:
            continue
        for table, member, _line in extract_nameof_references(text):
            if table is None:
                out.add(member)
    return out


def axis_surfaced_measures(model: SemanticModel,
                           patterns: Optional[Iterable[str]] = None) -> set[str]:
    """The measures the NUMBERED x-axis and y-axis tables surface.

    With no ``patterns`` the set comes from ``x-Selector 1`` to
    ``x-Selector 9`` and ``y-Selector 1`` to ``y-Selector 9``: the summary
    of the measure organisation asks what the report offers on either
    axis. A plot-specific table is not one of them.
    """
    out: set[str] = set()
    for t in field_parameter_tables(model, patterns):
        if patterns is None and not _numbered_axis(t.name):
            continue
        text = _file_text(t)
        if text is None:
            continue
        for table, member, _line in extract_nameof_references(text):
            if table is None:
                out.add(member)
    return out


def _numbered_x_axis(name: str) -> bool:
    """Is this table one of ``x-Selector 1`` … ``x-Selector 9``?"""
    m = re.fullmatch(r"x-Selector ([1-9])", name.strip())
    return m is not None


def _numbered_axis(name: str) -> bool:
    """Is this table one of ``x-Selector 1`` … ``x-Selector 9`` or
    ``y-Selector 1`` … ``y-Selector 9``?"""
    m = re.fullmatch(r"[xy]-Selector ([1-9])", name.strip())
    return m is not None
