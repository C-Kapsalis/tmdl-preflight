"""The exact words the field-parameter row rules print.

The check messages, the fix output and the comments a fixer writes into the
model are part of the contract: a reader must be able to tell which row is
meant, and a reviewer must recognise the annotation the tool left behind.
These tests pin the wording, not the layout.

Rules: F001 fieldparam-comma-runs, F002 fieldparam-missing-separator,
F003 fieldparam-trailing-comma, F004 fieldparam-ragged-rows,
F006 fieldparam-duplicate-rows, F007 fieldparam-family-consistency.
Stand-ins: `tests/fixtures/xyselector_axis_standins/<id>`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations
from tmdl_preflight.fieldparams import Row
from tmdl_preflight.rules.base import Context
from tmdl_preflight.rules.fp_rows import RaggedRowWidthRule

FIX = "xyselector_axis_standins"
FIXTURES = Path(__file__).parent / "fixtures" / FIX

pytestmark = [pytest.mark.p0]


def _model(stand_in, sid):
    sub = "Performance.SemanticModel" if sid == "template" else "Model.SemanticModel"
    return stand_in(FIX) / sid / sub


def _table(model, name):
    return model / "definition" / "tables" / name


# ---------------------------------------------------------------------------
# F001
# ---------------------------------------------------------------------------


def test_f001_message_leads_with_the_orphan_count(stand_in):
    model = _model(stand_in, "fp_comma_two_runs")
    code, payload = run_check(model, "F001")
    found = violations(payload, "F001")
    assert code == 1 and len(found) == 2
    assert found[0]["message"].startswith("1 orphan comma(s).")
    assert found[1]["message"].startswith("2 orphan comma(s).")


def test_f001_whole_file_finding_is_not_a_partition_source(stand_in):
    model = _model(stand_in, "fp_comma_in_calc_column")
    code, payload = run_check(model, "F001")
    found = violations(payload, "F001")
    assert found
    for v in found:
        assert "partition source" not in v["object"]
        assert v["object"] == "x-Selector 1 (field-parameter file)"


def test_f001_fix_says_what_it_removed(stand_in):
    model = _model(stand_in, "fp_comma_two_runs")
    code, payload = run_fix(model, "F001")
    assert code == 0
    fixes = payload["fixes"]
    assert any(f.startswith("F001: x-Selector 1.tmdl: removed 3 orphan comma(s)")
               for f in fixes), fixes
    blocks = payload["blocks"]
    assert any(b == "Removed 3 orphan comma(s) across 1 file(s). Commit the changes "
                   "and re-sync the affected workspace(s)." for b in blocks), blocks


# ---------------------------------------------------------------------------
# F002 / F003
# ---------------------------------------------------------------------------


def test_f002_message_names_the_missing_separator(stand_in):
    model = _model(stand_in, "fp_sep_missing")
    code, payload = run_check(model, "F002")
    found = violations(payload, "F002")
    assert found
    assert found[0]["message"].startswith("tuple closes with no ',' before the next tuple.")


def test_f003_message_names_the_dax_error(stand_in):
    model = _model(stand_in, "fp_sep_trailing")
    code, payload = run_check(model, "F003")
    found = violations(payload, "F003")
    assert found
    assert found[0]["message"].startswith(
        "last row before '}' has a trailing ',' -> DAX: \"Table constructor cannot have "
        "optional argument\".")


def test_separator_fixes_say_what_they_changed(stand_in):
    model = _model(stand_in, "fp_sep_missing")
    code, payload = run_fix(model, "F002")
    assert code == 0
    fixes = payload["fixes"]
    assert any(f == "F002: x-Selector 1.tmdl: added 1 separator comma(s)" for f in fixes), fixes
    blocks = payload["blocks"]
    assert any(b.startswith("Repaired 1 separator defect(s) across 1 file(s). ")
               for b in blocks), blocks


def test_trailing_comma_fix_says_what_it_changed(stand_in):
    model = _model(stand_in, "fp_sep_trailing")
    code, payload = run_fix(model, "F003")
    assert code == 0
    fixes = payload["fixes"]
    assert any(f == "F003: x-Selector 1.tmdl: removed 1 trailing comma(s)" for f in fixes), fixes
    blocks = payload["blocks"]
    assert any(b.startswith("Repaired 1 separator defect(s) across 1 file(s). ")
               for b in blocks), blocks


# ---------------------------------------------------------------------------
# F004
# ---------------------------------------------------------------------------


def test_f004_message_names_the_width_and_the_norm(stand_in):
    model = _model(stand_in, "fp_ragged_short_row")
    code, payload = run_check(model, "F004")
    found = violations(payload, "F004")
    assert found
    assert found[0]["message"] == '"CPM" has 5 fields, norm is 6'


def test_f004_pads_a_short_row_and_says_so(stand_in):
    model = _model(stand_in, "fp_ragged_short_row")
    code, payload = run_fix(model, "F004")
    assert code == 0
    fixes = payload["fixes"]
    assert any(f.startswith('F004: x-Selector 1.tmdl:') and
               f.endswith('"CPM" padded 5 -> 6 (field 6 set to "Other") — ANNOTATED IN PLACE, '
                          "needs BI review.")
               for f in fixes), fixes


def test_f004_writes_the_two_comment_lines(stand_in):
    model = _model(stand_in, "fp_ragged_short_row")
    run_fix(model, "F004")
    text = _table(model, "x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert ('\t\t\t\t    -- AUTO-PADDED: field 6 set to "Other" (modal value of this '
            'column).\n') in text
    assert ("\t\t\t\t    -- A BI developer MUST confirm this is correct for this row.\n") in text


def test_f004_realigns_a_long_row_and_says_so(stand_in):
    model = _model(stand_in, "fp_ragged_long_ambiguous")
    code, payload = run_fix(model, "F004")
    fixes = payload["fixes"]
    assert any("AMBIGUOUS" in f for f in fixes), fixes
    assert any("has 7 fields (norm 6) and the surplus field is AMBIGUOUS" in f
               for f in fixes), fixes


def test_f004_long_row_note_is_reported(stand_in):
    model = _model(stand_in, "fp_ragged_long_ambiguous")
    code, payload = run_fix(model, "F004")
    blocks = payload["blocks"]
    assert any("over-long row(s) left untouched" in b for b in blocks), blocks


def test_f004_no_modal_value_note(stand_in):
    """The note is unreachable through a table (every expected-width row has
    the position), so the message function is exercised directly."""
    rule = RaggedRowWidthRule()
    line = '    ("CPM", NAMEOF([CPM]), 3, "ads_x", "g")'
    row = Row(0, line, line.index("("), line.rindex(")"),
              ['"CPM"', "NAMEOF([CPM])", "3", '"ads_x"', '"g"'])
    kind, _text, _notes, report = rule._repair(row, 6, [])
    assert kind == "no_modal"
    assert report == ('"CPM" has 5 fields (norm 6) but no modal value could be derived '
                      "— skipped.")


# ---------------------------------------------------------------------------
# F006
# ---------------------------------------------------------------------------


def test_f006_message_names_the_row(stand_in):
    model = _model(stand_in, "fp_dup_three_copies")
    code, payload = run_check(model, "F006")
    found = violations(payload, "F006")
    assert found
    assert found[0]["message"] == "'PF Orders' -> NAMEOF([Units]) (order=905, id='pf_x') appears 3x"


def test_f006_two_spellings_of_the_same_call_are_not_duplicates(stand_in):
    model = _model(stand_in, "fp_dup_nameof_spelling")
    code, payload = run_check(model, "F006")
    assert violations(payload, "F006") == []


def test_f006_findings_are_ordered_by_the_row(stand_in):
    model = _model(stand_in, "fp_dup_two_groups")
    code, payload = run_check(model, "F006")
    found = violations(payload, "F006")
    assert len(found) == 2
    assert found[0]["message"].startswith("'A Widget'")
    assert found[1]["message"].startswith("'B Widget'")


def test_f006_fix_leaves_a_commented_copy_alone(stand_in):
    model = _model(stand_in, "fp_dup_commented_and_live")
    code, payload = run_fix(model, "F006")
    assert code == 0
    text = _table(model, "x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert ('\t\t\t\t    -- ("PF Orders", NAMEOF([Units]), 905, "pf_x"),\n') in text
    live = [ln for ln in text.splitlines() if '("PF Orders", NAMEOF([Units]), 905, "pf_x")' in ln
            and not ln.lstrip().startswith("--")]
    assert len(live) == 1, live
    code, payload = run_check(model, "F006")
    assert violations(payload, "F006") == []


def test_f006_fix_says_what_it_removed(stand_in):
    model = _model(stand_in, "fp_dup_three_copies")
    code, payload = run_fix(model, "F006")
    fixes = payload["fixes"]
    assert any(f == "F006: x-Selector 1.tmdl: removed 1 duplicate row(s)" for f in fixes), fixes
    blocks = payload["blocks"]
    assert any(b.startswith("removed 1 duplicate axis row(s) under ")
               for b in blocks), blocks


# ---------------------------------------------------------------------------
# F007
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
# PB21 - a model without field-parameter tables says so and passes
# ---------------------------------------------------------------------------


def test_no_axis_files_line(stand_in):
    model = _model(stand_in, "fp_no_axis_tables")
    code, payload = run_check(model, "F001")
    assert code == 0
    lines = [n for n in payload["notes"]
             if n.startswith("No x-/y-Selector field-parameter files found under ")]
    assert len(lines) == 1, payload["notes"]


def test_no_axis_files_line_is_printed_once(stand_in):
    model = _model(stand_in, "fp_no_axis_tables")
    code, payload = run_check(model, "F002", "F003")
    assert code == 0
    lines = [n for n in payload["notes"]
             if n.startswith("No x-/y-Selector field-parameter files found under ")]
    assert len(lines) == 1, payload["notes"]


def test_a_model_with_axis_tables_says_nothing(stand_in):
    model = _model(stand_in, "fp_clean")
    code, payload = run_check(model, "F001")
    assert code == 0
    assert not [n for n in payload["notes"] if n.startswith("No x-/y-Selector")]


# ---------------------------------------------------------------------------
# PB17 - the byte-order mark and the line endings survive a repair
# ---------------------------------------------------------------------------


def test_a_file_with_a_bom_and_crlf_keeps_both(stand_in):
    model = _model(stand_in, "fp_ragged_short_row")
    path = _table(model, "x-Selector 1.tmdl")
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    path.write_bytes(b"\xef\xbb\xbf" + raw.replace(b"\n", b"\r\n"))
    run_fix(model, "F004")
    after = path.read_bytes()
    assert after.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in after
    assert b"\n" not in after.replace(b"\r\n", b"")
    assert b"AUTO-PADDED" in after
