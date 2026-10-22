"""The field-parameter FAMILY rule: which row is copied, which is removed and
what the fixer writes into the file.

The numbered tables of an axis must offer the same fields. A missing field is
copied from a sibling that has it, a date-named field is removed from the
second plot-specific table, and a field only the first plot-specific table
offers is promoted into the numbered set. Every edit is annotated in place.

Rule: F007 fieldparam-family-consistency.
Stand-ins: `tests/fixtures/xyselector_axis_standins/<id>`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations

FIX = "xyselector_axis_standins"
FIXTURES = Path(__file__).parent / "fixtures" / FIX

pytestmark = [pytest.mark.p0]


def _model(stand_in, sid):
    sub = "Performance.SemanticModel" if sid == "template" else "Model.SemanticModel"
    return stand_in(FIX) / sid / sub


def _table(model, name):
    return model / "definition" / "tables" / name


# ---------------------------------------------------------------------------
# the messages
# ---------------------------------------------------------------------------


def test_f007_missing_field_message(stand_in):
    model = _model(stand_in, "fp_family_missing_field")
    code, payload = run_check(model, "F007")
    found = violations(payload, "F007")
    assert found
    assert found[0]["message"] == "MISSING _Stores[Region] (offered by x-Selector 1.tmdl)"


def test_f007_date_field_message(stand_in):
    model = _model(stand_in, "fp_family_ps2_date")
    code, payload = run_check(model, "F007")
    found = violations(payload, "F007")
    assert found
    messages = [v["message"] for v in found]
    assert "date-named field Calendar[Order Date] must not be in Plot Specific 2" in messages


def test_f007_plot_specific_only_field_message(stand_in):
    model = _model(stand_in, "fp_family_ps1_unique")
    code, payload = run_check(model, "F007")
    found = violations(payload, "F007")
    assert found
    assert found[0]["message"] == (
        "Margin % is offered NOWHERE in the canonical set — Plot Specific 1 may not "
        "introduce fields")


# ---------------------------------------------------------------------------
# the row is copied from the numbered tables, not from the second
# plot-specific table
# ---------------------------------------------------------------------------


def test_missing_field_is_offered_by_a_numbered_table(stand_in):
    model = _model(stand_in, "fp_family_ps2_also_offers")
    code, payload = run_check(model, "F007")
    messages = [v["message"] for v in violations(payload, "F007")]
    assert "MISSING _Stores[Region] (offered by x-Selector 1.tmdl)" in messages


def test_missing_field_is_copied_from_the_numbered_table(stand_in):
    model = _model(stand_in, "fp_family_ps2_also_offers")
    code, payload = run_fix(model, "F007")
    assert code == 0
    text = _table(model, "x-Selector 2.tmdl").read_text(encoding="utf-8")
    assert '"store_x"' in text
    assert '"ps2_x"' not in text


# ---------------------------------------------------------------------------
# the LAST numbered plot-specific table is "the second" one
# ---------------------------------------------------------------------------


def test_the_last_plot_specific_table_is_the_second_one(stand_in):
    model = _model(stand_in, "fp_family_ps2_and_ps3")
    code, payload = run_check(model, "F007")
    found = violations(payload, "F007")
    dates = [v for v in found if v["message"].startswith("date-named field")]
    assert len(dates) == 1
    assert dates[0]["file"].endswith("x-Plot Specific 3.tmdl")


# ---------------------------------------------------------------------------
# the comment lines the fixer writes
# ---------------------------------------------------------------------------


def test_added_row_carries_the_added_marker(stand_in):
    model = _model(stand_in, "fp_family_missing_field")
    run_fix(model, "F007")
    text = _table(model, "x-Selector 2.tmdl").read_text(encoding="utf-8")
    assert ('\t\t\t\t    -- AUTO-ADDED: copied from x-Selector 1.tmdl — every table in '
            "this family must offer _Stores[Region].\n") in text


def test_promoted_row_carries_the_promoted_marker(stand_in):
    model = _model(stand_in, "fp_family_ps1_unique")
    run_fix(model, "F007")
    text = _table(model, "x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert ('\t\t\t\t-- AUTO-PROMOTED: Margin % was offered only by '
            "x-Plot Specific 1.tmdl; Plot Specific 1 may not introduce fields, so it "
            "is promoted here rather than dropped from the picker.\n") in text
    assert ("\t\t\t\t-- A BI developer MUST confirm it belongs in the canonical "
            "set.\n") in text


def test_removed_row_is_replaced_by_the_removed_marker(stand_in):
    model = _model(stand_in, "fp_family_ps2_date")
    run_fix(model, "F007")
    text = _table(model, "x-Plot Specific 2.tmdl").read_text(encoding="utf-8")
    assert ('\t\t\t\t    -- AUTO-REMOVED: Calendar[Order Date] references a name containing '
            "the word 'date'; x-Plot Specific 2 must not offer those.\n") in text
    assert ("\t\t\t\t    -- A BI developer MUST confirm this row was not wanted here.\n") in text
    assert '("Order Date", NAMEOF(\'Calendar\'[Order Date]), 9, "date_x")' not in text


# ---------------------------------------------------------------------------
# removing the last date row leaves no trailing comma behind
# ---------------------------------------------------------------------------


def test_removed_last_row_leaves_no_trailing_comma(stand_in):
    model = _model(stand_in, "fp_family_ps2_date")
    run_fix(model, "F007")
    code, payload = run_check(model, "F003")
    assert violations(payload, "F003") == []


# ---------------------------------------------------------------------------
# the copied row keeps its own text, and the separators are repaired
# ---------------------------------------------------------------------------


def test_promoted_row_keeps_the_source_indentation(stand_in):
    model = _model(stand_in, "fp_family_ps1_indent")
    run_fix(model, "F007")
    text = _table(model, "x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert '\t\t\t    ("Margin", NAMEOF([Margin %]), 8, "other_x")\n' in text


def test_promoted_row_leaves_no_separator_defect(stand_in):
    model = _model(stand_in, "fp_family_ps1_indent")
    run_fix(model, "F007")
    code, payload = run_check(model, "F002", "F003")
    assert violations(payload, "F002") == []
    assert violations(payload, "F003") == []


# ---------------------------------------------------------------------------
# a row of a different width is not copied, and says so
# ---------------------------------------------------------------------------


def test_row_of_another_width_is_not_copied(stand_in):
    model = _model(stand_in, "fp_family_arity_mismatch")
    before = _table(model, "x-Selector 2.tmdl").read_bytes()
    code, payload = run_fix(model, "F007")
    fixes = payload["fixes"]
    assert any(f == "F007: x-Selector 2.tmdl: Margin % NOT added — the sibling row has 5 "
                   "fields, this table's rows have 4. Re-shaping across arities is the "
                   "ragged-tuple fixer's job, not this one." for f in fixes), fixes
    assert _table(model, "x-Selector 2.tmdl").read_bytes() == before
    code, payload = run_check(model, "F007")
    assert any(v["message"] == "MISSING Margin % (offered by x-Selector 1.tmdl)"
               for v in violations(payload, "F007"))
