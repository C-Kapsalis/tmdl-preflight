"""Reference integrity of the y-axis field-parameter tables (y-Selector N).

* D-field-parameter-column-refs-resolve -> D004 (casing mismatches are errors)
* D-calculated-column-expression-present
* D-field-parameter-table-no-measures
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"
AXIS = "y-Selector 1"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"
class TestYSelectorReferencesValid:
    def test_yselector_references_valid(self, stand_in):
        code, payload = run_check(_model(stand_in), "D004", strict=True)
        assert code == 0, payload
        assert violations(payload, "D004") == []

    def test_broken_column_on_critical_table_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), "D004", strict=True)
        assert code == 1
        found = [v for v in violations(payload, "D004") if AXIS in v["message"]]
        assert len(found) == 1 and "Nope" in found[0]["message"]

    def test_case_only_mismatch_is_a_casing_error(self, stand_in, replace_in):
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "Coffee Measures.tmdl",
                   "'y-Selector 1'[y-Selector 1]", "'y-Selector 1'[Y-SELECTOR 1]")
        code, payload = run_check(model, "D004")
        assert code == 1
        found = violations(payload, "D004")
        assert len(found) == 1 and found[0]["severity"] == "error"
        assert "casing" in found[0]["message"].lower()
class TestYSelectorCalculatedColumns:
    def test_yselector_calculated_columns(self, stand_in):
        code, payload = run_check(_model(stand_in), "calculated-column-expression-present")
        assert code == 0, payload
        assert violations(payload) == []
class TestYSelectorNoMeasures:
    RULE = "field-parameter-table-no-measures"

    def test_yselector_no_measures(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert violations(payload) == []

    def test_measure_on_axis_table_fails(self, stand_in):
        model = _model(stand_in)
        f = model / "definition" / "tables" / "y-Selector 2.tmdl"
        text = f.read_text(encoding="utf-8")
        i = text.index("\tcolumn ")
        f.write_text(text[:i] + "\tmeasure Stray = 1\n\t\tlineageTag: 7a5b6c8d-9eaf-4b01-c2d3-4e5f6a7b8c9d\n\n"
                     + text[i:], encoding="utf-8")
        code, payload = run_check(model, self.RULE)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1 and "y-Selector 2" in found[0]["message"]


UNREAD_AXIS = """table 'y-Selector 1'
\tcolumn 'y-Selector 1'
\t\tsourceColumn: [Value1]

\tpartition 'y-Selector 1' = calculated
\t\tmode: import
\t\tsource = ```
\t\t\t\t{
\t\t\t\t\t("Shop", NAMEOF('_Shops'[shop_name]), 0, "Shops_y")
\t\t\t\t}
\t\t\t\t```
"""

SHOPS = """table _Shops
\tcolumn shop_name
\t\tdataType: string

\tpartition _Shops = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t    Source = Sql.Database("example-server", "roastery")
\t\t\t\tin
\t\t\t\t    Source
"""


def test_an_axis_table_no_measure_reads_is_not_a_defect(tmp_path):
    """No measure reads the axis table: there is no reference to check, and
    that is not a failure."""
    tables = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "y-Selector 1.tmdl").write_text(UNREAD_AXIS, encoding="utf-8")
    (tables / "_Shops.tmdl").write_text(SHOPS, encoding="utf-8")
    code, payload = run_check(tmp_path / "Shop.SemanticModel", "D004")
    assert code == 0, payload
    assert violations(payload, "D004") == []

