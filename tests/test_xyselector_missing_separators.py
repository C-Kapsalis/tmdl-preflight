"""Row separators in field-parameter tables must be exact: one comma between
every pair of rows, none after the last.

A MISSING separator (left by an append) and a
TRAILING comma before `}` ("Table constructor cannot have optional argument")
both leave the calculated table empty - silently at refresh time.

Rules: F002 fieldparam-missing-separator, F003 fieldparam-trailing-comma (rules +
fixers, whole-file scope limited to table-constructor rows). Script subprocess ->
`check/fix --select F002,F003`; `PBI_AUTOFIX=1` -> fix then clean re-check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations

pytestmark = [pytest.mark.p0]

FIX = "xyselector_axis_standins"
FIXTURES = Path(__file__).parent / "fixtures" / FIX
STANDINS = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())  # fp_* + template


def _model(stand_in, sid):
    sub = "Performance.SemanticModel" if sid == "template" else "Model.SemanticModel"
    return stand_in(FIX) / sid / sub


def _cases(fails=(), skips=(), overrides=None):
    overrides = overrides or {}
    return [(s, overrides.get(s, "skip" if s in skips else "fail" if s in fails else "pass"))
            for s in STANDINS]


@pytest.mark.parametrize(
    "sid, verdict",
    _cases(
        fails={"fp_sep_missing", "fp_sep_trailing"},
        overrides={
            # STRICTER: rows without NAMEOF are constructor rows too (earlier versions passed)
            "fp_sep_no_nameof_rows": "fail",
            # STRICTER: "), }" on one line is a trailing comma (earlier versions passed)
            "fp_sep_inline_close": "fail",
        },
    ),
)
def test_xyselector_tuple_separators_are_exact(stand_in, sid, verdict):
    model = _model(stand_in, sid)
    code, payload = run_check(model, "F002", "F003")
    found = violations(payload)
    if verdict == "pass":
        assert found == [], f"separator defect(s) in {sid}: {found}"
        return
    assert found and code == 1
    expected = {"fp_sep_missing": "F002", "fp_sep_trailing": "F003",
                "fp_sep_no_nameof_rows": "F002", "fp_sep_inline_close": "F003"}[sid]
    assert {v["rule"] for v in found} == {expected}
    fix_code, fixed = run_fix(model, "F002", "F003")
    assert fix_code == 0 and violations(fixed) == [], (
        f"auto-fix did NOT fully resolve the separator defects: {violations(fixed)}")
    snapshot = {p: p.read_bytes() for p in model.rglob("*.tmdl")}
    run_fix(model, "F002", "F003")
    assert {p: p.read_bytes() for p in model.rglob("*.tmdl")} == snapshot
