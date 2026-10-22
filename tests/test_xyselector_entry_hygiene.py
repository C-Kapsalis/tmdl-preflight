"""Row hygiene for field-parameter axis tables: no fully duplicated rows, and a
uniform row width per table.

A duplicated row shows the same item twice in the
picker; a ragged row ("Each tuple in table constructor must have the same number
of columns") fails the whole calculated table. Offering the SAME measure under a
different identifier/category is legal: the duplicate key is the full row.

Rules: fieldparam-duplicate-rows (new, error + fixer) and F004
fieldparam-ragged-rows (error + fixer: pads short rows with the column's most
frequent value under an AUTO-PADDED comment; long rows are realigned only when
unambiguous). Fixer scripts -> `check/fix --select`; models without axis tables
are skipped as in the earlier check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations

pytestmark = [pytest.mark.p0]

FIX = "xyselector_axis_standins"
FIXTURES = Path(__file__).parent / "fixtures" / FIX
# These stand-ins carry a duplicate group of their own shape and are covered
# by tests/test_fieldparam_row_parity.py.
ELSEWHERE = {"fp_dup_commented_and_live", "fp_dup_two_groups"}
STANDINS = sorted(p.name for p in FIXTURES.iterdir()
                   if p.is_dir() and p.name not in ELSEWHERE)  # fp_* + template


def _model(stand_in, sid):
    sub = "Performance.SemanticModel" if sid == "template" else "Model.SemanticModel"
    return stand_in(FIX) / sid / sub


def _cases(fails=(), skips=(), overrides=None):
    overrides = overrides or {}
    return [(s, overrides.get(s, "skip" if s in skips else "fail" if s in fails else "pass"))
            for s in STANDINS]


@pytest.mark.parametrize(
    "sid, verdict",
    _cases(fails={"fp_dup_three_copies"}, skips={"fp_no_axis_tables"}),
)
def test_no_duplicate_axis_entries(stand_in, sid, verdict):
    model = _model(stand_in, sid)
    rule = "fieldparam-duplicate-rows"
    code, payload = run_check(model, rule)
    found = violations(payload)
    if verdict != "fail":
        assert found == []
        if verdict == "skip":
            pytest.skip("model has no axis tables")
        return
    assert len(found) == 1 and code == 1
    assert "PF Orders" in found[0]["message"] and "3" in found[0]["message"]
    # PBI_AUTOFIX=1 branch. Earlier verdict with autofix: FAIL - the surviving
    # copy is matched by its exact text (trailing comma included), so the last
    # copy of the constructor (no trailing comma) is not removed and is still
    # reported. The tool's fixer specifies the same behaviour.
    run_fix(model, rule)
    text = (model / "definition" / "tables" / "x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert text.count('("PF Orders", NAMEOF([Units]), 905, "pf_x")') == 2
    code2, again = run_check(model, rule)
    assert code2 == 1, "duplicates survived the auto-fix"


@pytest.mark.parametrize(
    "sid, verdict",
    _cases(fails={"fp_ragged_short_row", "fp_ragged_long_ambiguous"}, skips={"fp_no_axis_tables"}),
)
def test_axis_entries_have_uniform_arity(stand_in, sid, verdict):
    model = _model(stand_in, sid)
    code, payload = run_check(model, "F004")
    found = violations(payload, "F004")
    if verdict != "fail":
        assert found == []
        if verdict == "skip":
            pytest.skip("model has no axis tables")
        return
    assert len(found) == 1 and code == 1
    assert found[0]["severity"] == "error"
    # PBI_AUTOFIX=1 branch (earlier verdicts: short row -> pass, long ambiguous -> fail)
    run_fix(model, "F004")
    code2, again = run_check(model, "F004")
    if sid == "fp_ragged_short_row":
        assert code2 == 0 and violations(again) == []
        text = (model / "definition" / "tables" / "x-Selector 1.tmdl").read_text(encoding="utf-8")
        assert "AUTO-PADDED" in text
        assert '("CPM", NAMEOF([CPM]), 3, "ads_x", "g", "Other"' in text
    else:
        assert code2 == 1, "rows longer than the norm are not auto-fixable when ambiguous"
