"""Reference integrity of the x-axis field-parameter tables (x-Selector N).

* D-field-parameter-column-refs-resolve -> D004 (casing mismatches are errors)
* D-calculated-column-expression-present
* D-field-parameter-table-no-measures
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"
AXIS = "x-Selector 1"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"
class TestXSelectorReferencesValid:
    def test_xselector_references_valid(self, stand_in):
        code, payload = run_check(_model(stand_in), "D004", strict=True)
        assert code == 0, payload
        assert violations(payload, "D004") == []

    def test_broken_column_on_critical_table_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), "D004", strict=True)
        assert code == 1
        found = [v for v in violations(payload, "D004") if AXIS in v["message"]]
        assert len(found) == 1 and "Ordr" in found[0]["message"]

    def test_case_only_mismatch_is_a_casing_error(self, stand_in, replace_in):
        """STRICTER (project decision): the reference resolves in Power BI,
        which is case-insensitive, but D004 reports casing mismatches as errors."""
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "Coffee Measures.tmdl",
                   "'x-Selector 1'[x-Selector 1]", "'x-Selector 1'[x-selector 1]")
        code, payload = run_check(model, "D004")
        assert code == 1
        found = violations(payload, "D004")
        assert len(found) == 1 and found[0]["severity"] == "error"
        assert "casing" in found[0]["message"].lower()

    def test_reference_to_missing_axis_table_fails(self, stand_in, replace_in):
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "Coffee Measures.tmdl",
                   "'x-Selector 1'[x-Selector 1]", "'x-Selector 9'[x-Selector 9]")
        code, payload = run_check(model, "D004", strict=True)
        assert code == 1
        assert any("x-Selector 9" in v["message"] for v in violations(payload, "D004"))
class TestXSelectorCalculatedColumns:
    RULE = "calculated-column-expression-present"

    def test_xselector_calculated_columns(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert violations(payload) == []

    def test_calculated_column_with_empty_expression_fails(self, stand_in):
        """STRICTER: the earlier check parser did not see `column X =` followed by a
        property line as calculated, so it passed this stand-in."""
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1 and "Axis Label" in found[0]["message"]
class TestXSelectorNoMeasures:
    RULE = "field-parameter-table-no-measures"

    def test_xselector_no_measures(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert violations(payload) == []

    def test_measure_on_axis_table_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert AXIS in found[0]["message"] and "1" in found[0]["message"]


MEASURE_ON_AXIS = """table 'x-Selector 2'
\tmeasure Stray = 1
\t\tlineageTag: 7c6cd67a-9d37-5730-872a-78a386ad12c6

\tcolumn 'x-Selector 2'
\t\tsourceColumn: [Value1]

\tpartition 'x-Selector 2' = calculated
\t\tmode: import
\t\tsource = ```
\t\t\t\t{
\t\t\t\t\t("Cups", NAMEOF([Cups]), 1, "g_x")
\t\t\t\t}
\t\t\t\t```
"""

EMPTY_EXPRESSION = """table 'x-Selector 2'
\tcolumn 'x-Selector 2'
\t\tsourceColumn: [Value1]

\tcolumn 'Calc' =
\t\tdataType: string

\tpartition 'x-Selector 2' = calculated
\t\tmode: import
\t\tsource = ```
\t\t\t\t{
\t\t\t\t\t("Cups", NAMEOF([Cups]), 1, "g_x")
\t\t\t\t}
\t\t\t\t```
"""


def _axis_model(tmp_path, text):
    tables = tmp_path / "Roastery.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "x-Selector 2.tmdl").write_text(text, encoding="utf-8")
    return tmp_path / "Roastery.SemanticModel"


def test_measure_on_an_axis_table_is_named(tmp_path):
    model = _axis_model(tmp_path, MEASURE_ON_AXIS)
    code, payload = run_check(model, "field-parameter-table-no-measures")
    assert code == 1, payload
    found = violations(payload)
    assert len(found) == 1
    assert found[0]["message"] == (
        "x-Selector 2 unexpectedly contains 1 measures. x-Selector tables "
        "should be dimension tables with columns only.")


def test_calculated_column_with_an_empty_expression_is_named(tmp_path):
    model = _axis_model(tmp_path, EMPTY_EXPRESSION)
    code, payload = run_check(model, "calculated-column-expression-present")
    assert code == 1, payload
    found = violations(payload)
    assert len(found) == 1
    assert found[0]["message"] == "x-Selector 2[Calc] has empty expression"
