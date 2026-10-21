"""``report nameof``: the field-parameter tables and the references they hold.

The report groups the field-parameter tables into two families (the x axis
and the y axis), counts the NAMEOF references each table holds, and lists
the broken ones with the reason each broke.

The reference's reasons are the ones a reader needs: a measure that is not
found, an ambiguous measure, a table that is not found, a measure used where
a column was meant, a column that is not found, and a reference the parser
could not read.
"""
from __future__ import annotations

import json

from conftest import run_cli

TREE = "rp_reports"


def _model(stand_in):
    return stand_in(TREE) / "Growth.SemanticModel"


def test_the_family_report_has_the_reference_layout(stand_in):
    code, out, _err = run_cli("report", "nameof", str(_model(stand_in)))
    assert code == 0
    lines = out.splitlines()
    start = lines.index("REPORT TABLE ANALYSIS")
    block = lines[start - 1:]
    assert block[0] == "=" * 80
    assert block[1] == "REPORT TABLE ANALYSIS"
    assert block[2] == "=" * 80
    assert block[4] == "🔍 Parsing model..."
    assert block[5] == "✅ Model parsed successfully"
    assert block[7] == "📊 REPORT TABLES FOUND"
    assert block[8] == "-" * 80
    assert block[9] == "x-Selector tables: 1"
    assert block[10] == "  • x-Selector 1"
    assert block[12] == "y-Selector tables: 1"
    assert block[13] == "  • y-Selector 1"
    assert block[15] == "=" * 80
    assert block[16] == "X-SELECTOR TABLE ANALYSIS"
    assert block[17] == "=" * 80
    assert block[19] == "📋 x-Selector 1"
    assert block[20] == "-" * 80
    assert block[21] == "  Columns: 1"
    assert block[22] == "  Measures: 1"
    assert block[23] == "  NAMEOF references: 5"
    assert block[24] == "  Sample NAMEOF references:"
    assert block[25] == "    • Sales[Revenue] (in Lbl)"
    assert block[26] == "    • Ghost[x] (in Lbl)"
    assert block[27] == "    • Sales[nope] (in Lbl)"
    assert block[28] == "  Broken references: 5 (Errors: 3, Warnings: 2)"
    assert block[30] == "=" * 80
    assert block[31] == "Y-SELECTOR TABLE ANALYSIS"
    assert block[32] == "=" * 80
    assert block[34] == "📋 y-Selector 1"
    assert block[38] == "  NAMEOF references: 1"
    assert block[39] == "  Sample NAMEOF references:"
    assert block[40] == "    • _Products[product_id] (in YL)"
    assert block[41] == "  Broken references: 0 (Errors: 0, Warnings: 0)"
    assert block[43] == "=" * 80
    assert block[44] == "SUMMARY"
    assert block[45] == "=" * 80
    assert block[47] == "x-Selector Tables:"
    assert block[48] == "  Total NAMEOF references: 5"
    assert block[49] == "  Total broken: 5"
    assert block[51] == "y-Selector Tables:"
    assert block[52] == "  Total NAMEOF references: 1"
    assert block[53] == "  Total broken: 0"
    assert block[55] == "Combined:"
    assert block[56] == "  Total NAMEOF references: 6"
    assert block[57] == "  Total broken: 5"


def test_the_family_report_json_has_the_reference_layout(stand_in):
    code, out, _err = run_cli("report", "nameof", str(_model(stand_in)), "--json")
    assert code == 0
    data = json.loads(out)
    assert list(data) == ["x_selector", "y_selector", "summary"]
    assert data["x_selector"]["x-Selector 1"] == {
        "columns": 1, "measures": 1, "nameof_refs": 5,
        "broken_refs": 5, "errors": 3, "warnings": 2,
    }
    assert data["y_selector"]["y-Selector 1"] == {
        "columns": 1, "measures": 1, "nameof_refs": 1,
        "broken_refs": 0, "errors": 0, "warnings": 0,
    }
    assert data["summary"] == {
        "x_selector_refs": 5, "x_selector_broken": 5,
        "y_selector_refs": 1, "y_selector_broken": 0,
        "total_refs": 6, "total_broken": 5,
    }


def test_the_validation_block_has_the_reference_layout(stand_in):
    code, out, _err = run_cli("report", "nameof", str(_model(stand_in)))
    assert code == 0
    lines = out.splitlines()
    start = lines.index("NAMEOF REFERENCE VALIDATION REPORT")
    block = lines[start - 1:]
    assert block[0] == "=" * 80
    assert block[1] == "NAMEOF REFERENCE VALIDATION REPORT"
    assert block[2] == "=" * 80
    assert block[3] == ""
    assert block[4] == "Total References: 6"
    assert block[5] == "  Measure References: 2"
    assert block[6] == "  Column References: 4"
    assert block[7] == "  Unique Tables: 3"
    assert block[8] == "  Unique Objects: 6"
    assert block[9] == ""
    assert block[10] == "❌ Found 5 issues:"
    assert block[11] == "   Errors: 3"
    assert block[12] == "   Warnings: 2"
    assert block[13] == ""
    assert block[14] == "ERRORS:"
    assert block[15] == "-" * 80
    assert block[16] == "[ERROR] Broken reference in x-Selector 1[Lbl]:"
    assert block[17] == "  Reference: Ghost[x]"
    assert block[18] == "  Reason: Table 'Ghost' not found"
    assert block[19] == (
        "  Context: NAMEOF('Sales'[Revenue]) & NAMEOF([Revenue]) & NAMEOF(Sales[nope]) & "
        "NAMEOF([Mis...")
    assert block[20] == ""
    assert block[21] == "[ERROR] Broken reference in x-Selector 1[Lbl]:"
    assert block[22] == "  Reference: Sales[nope]"
    assert block[23] == "  Reason: Column 'nope' not found in table 'Sales'"
    assert block[24] == (
        "  Context: NAMEOF('Sales'[Revenue]) & NAMEOF([Revenue]) & NAMEOF(Sales[nope]) & "
        "NAMEOF([Mis...")
    assert block[25] == ""
    assert block[26] == "[ERROR] Broken reference in x-Selector 1[Lbl]:"
    assert block[27] == "  Reference: [Missing]"
    assert block[28] == "  Reason: Measure 'Missing' not found in any table"
    assert block[31] == "WARNINGS:"
    assert block[32] == "-" * 80
    assert block[33] == "[WARNING] Broken reference in x-Selector 1[Lbl]:"
    assert block[34] == "  Reference: Sales[Revenue]"
    assert block[35] == "  Reason: 'Revenue' is a measure, not a column. Use NAMEOF([Revenue]) instead"
    assert block[38] == "[WARNING] Broken reference in x-Selector 1[Lbl]:"
    assert block[39] == "  Reference: [Revenue]"
    assert block[40] == (
        "  Reason: Ambiguous: measure 'Revenue' exists in multiple tables: "
        "['Report Helpers', 'Sales']")
    assert block[-1] == "=" * 80


def test_the_validation_block_starts_the_report(stand_in):
    code, out, _err = run_cli("report", "nameof", str(_model(stand_in)))
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "=" * 80
    assert lines[1] == "NAMEOF REFERENCE VALIDATION REPORT"
    assert lines[2] == "=" * 80
