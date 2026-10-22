"""The x-/y-Selector FAMILY must offer a consistent set of fields.

Convention:
  R1 x-Selector 1..N and x-Plot Specific 2 offer the same fields ...
  R2 ... except x-Plot Specific 2 carries no field whose object name contains
     the whole word "date";
  R3 x-Plot Specific 1 may offer fewer fields, but none unique to it;
  R4/R5 the same for y-Selector 1..N and y-Plot Specific 1.
Identity is canonical: spacing is ignored, a measure's table qualifier is
dropped (measures are model-global), "Update Events" does not contain "date".

Rule: fieldparam-family-consistency (new, error + fixer: copies missing rows,
removes date rows from Plot Specific 2, promotes PS1-only rows). The family
helper and the fixer script -> `check/fix --select fieldparam-family-consistency`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations

pytestmark = [pytest.mark.p0]

FIX = "xyselector_axis_standins"
FIXTURES = Path(__file__).parent / "fixtures" / FIX
# The arity stand-in keeps its finding after the fix (a row of another width
# is never copied) and has its own tests in test_fieldparam_family_parity.py.
ELSEWHERE = {"fp_family_arity_mismatch"}
STANDINS = sorted(p.name for p in FIXTURES.iterdir()
                   if p.is_dir() and p.name not in ELSEWHERE)  # fp_* + template


def _model(stand_in, sid):
    sub = "Performance.SemanticModel" if sid == "template" else "Model.SemanticModel"
    return stand_in(FIX) / sid / sub


def _cases(fails=(), skips=(), overrides=None):
    overrides = overrides or {}
    return [(s, overrides.get(s, "skip" if s in skips else "fail" if s in fails else "pass"))
            for s in STANDINS]

RULE = "fieldparam-family-consistency"


@pytest.mark.parametrize(
    "sid, verdict",
    [c for c in _cases(
        fails={"fp_family_missing_field", "fp_family_ps1_unique", "fp_family_ps2_date",
               "fp_family_ps1_indent", "fp_family_ps2_also_offers",
               "fp_family_ps2_and_ps3"},
        skips={"fp_no_axis_tables", "template"},
    ) if c[0] != "fp_sep_no_nameof_rows"],  # stand-in for the separator rule only
)
def test_xyselector_family_offers_consistent_fields(stand_in, sid, verdict):
    model = _model(stand_in, sid)
    code, payload = run_check(model, RULE)
    found = violations(payload)
    if verdict != "fail":
        assert found == [], f"family inconsistency in {sid}: {found}"
        if verdict == "skip":
            pytest.skip("model has no x-/y-Selector family to compare")
        return
    assert found and code == 1
    # PBI_AUTOFIX=1 branch: earlier verdict pass for all three
    run_fix(model, RULE)
    code2, again = run_check(model, RULE)
    assert code2 == 0 and violations(again) == [], (
        f"family inconsistency survived the auto-fix: {violations(again)}")
    tables = model / "definition" / "tables"
    if sid == "fp_family_missing_field":
        assert "NAMEOF('_Stores'[Region])" in (tables / "x-Selector 2.tmdl").read_text(encoding="utf-8")
    if sid == "fp_family_ps1_unique":
        ps1 = (tables / "x-Plot Specific 1.tmdl").read_text(encoding="utf-8")
        assert "NAMEOF([Margin %])" in ps1  # promoted, never dropped from PS1
        assert "NAMEOF([Margin %])" in (tables / "x-Selector 1.tmdl").read_text(encoding="utf-8")
