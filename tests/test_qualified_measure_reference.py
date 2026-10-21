"""PA20: the fact trace follows a qualified measure reference.

A reference of the form `'Table'[Name]` or `Table[Name]`, where `Name` is
a measure the model declares, is an edge — exactly like a bare `[Name]`.
The qualifier says which table owns the measure; it does not change what
the reference means.

Without this, a filter measure that reaches a fact through a qualified
measure reference is not counted as coverage, and the filter-coverage rule
reports a false error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

FACT = (
    "table Sales\n"
    "\tlineageTag: 00000000-0000-4000-8000-000000000001\n\n"
    "\tcolumn amount\n"
    "\t\tdataType: double\n"
    "\t\tlineageTag: 00000000-0000-4000-8000-000000000002\n"
    "\t\tsourceColumn: amount\n\n"
    "\tpartition Sales = m\n"
    "\t\tmode: import\n"
    "\t\tsource = x\n"
)

HELPERS = (
    "table 'Helper Measures'\n"
    "\tlineageTag: 00000000-0000-4000-8000-000000000010\n\n"
    "\tmeasure '-helper Basket' = SUM(Sales[amount])\n"
    "\t\tlineageTag: 00000000-0000-4000-8000-000000000011\n\n"
    "\tmeasure 'Revenue' = SUM(Sales[amount])\n"
    "\t\tlineageTag: 00000000-0000-4000-8000-000000000012\n"
)

FILTERS_QUALIFIED = (
    "table 'f-Filters'\n"
    "\tlineageTag: 00000000-0000-4000-8000-000000000020\n\n"
    "\tmeasure 'f-Sales' = int(not ISEMPTY('Helper Measures'[-helper Basket]))\n"
    "\t\tlineageTag: 00000000-0000-4000-8000-000000000021\n"
)

FILTERS_BARE = (
    "table 'f-Filters'\n"
    "\tlineageTag: 00000000-0000-4000-8000-000000000020\n\n"
    "\tmeasure 'f-Sales' = int(not ISEMPTY([-helper Basket]))\n"
    "\t\tlineageTag: 00000000-0000-4000-8000-000000000021\n"
)


def _model(tmp_path: Path, filters: str) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n\nref table Sales\nref table 'Helper Measures'\n"
        "ref table 'f-Filters'\n", encoding="utf-8")
    (definition / "tables" / "Sales.tmdl").write_text(FACT, encoding="utf-8")
    (definition / "tables" / "Helper Measures.tmdl").write_text(
        HELPERS, encoding="utf-8")
    (definition / "tables" / "f-Filters.tmdl").write_text(
        filters, encoding="utf-8")
    return definition


def test_a_qualified_reference_is_an_edge(tmp_path):
    """PA20: the filter measure covers the fact it reaches through the
    qualified reference."""
    model = _model(tmp_path, FILTERS_QUALIFIED)
    code, payload = run_check(model, "fact-table-filter-coverage")
    found = violations(payload, "O015")
    assert found == [], found


def test_a_bare_reference_is_an_edge_too(tmp_path):
    """PA20: the other side of the rule."""
    model = _model(tmp_path, FILTERS_BARE)
    code, payload = run_check(model, "fact-table-filter-coverage")
    found = violations(payload, "O015")
    assert found == [], found
