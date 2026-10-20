"""No stray structural commas in field-parameter axis tables.

Two or more commas separated only by whitespace
(a dangling `,` after a dropped row, or a doubled `,,`) make the calculated
table's source unparseable, so the axis table - and the analysis-category table
built from it - hold no data. Commas in `--`/`//` comments are parked rows and
exempt; commas inside string literals are masked.

Rule: F001 fieldparam-comma-runs (whole field-parameter file, rule + fixer).
The fixer-script subprocess becomes `check --select F001` / `fix --select F001`;
`PBI_AUTOFIX=1` semantics map to: fix, then the re-check must be clean.
Stand-ins: `tests/fixtures/xyselector_axis_standins/<id>` (fleet discovery).
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
        fails={"fp_comma_blank_line", "fp_comma_doubled", "fp_comma_in_calc_column"},
        # BUGFIX: fp_comma_in_label - a ", ," inside a display label was reported
        # by the earlier check (and its fixer rewrote the label); strings are masked now.
        overrides={"fp_comma_in_label": "pass"},
    ),
)
def test_xyselector_no_stray_commas(stand_in, sid, verdict):
    model = _model(stand_in, sid)
    code, payload = run_check(model, "F001")
    found = violations(payload, "F001")
    if verdict == "pass":
        assert found == [], f"stray field-parameter comma(s) in {sid}: {found}"
        assert code == 0
        return
    assert found and code == 1, "stray comma(s) must fail without auto-repair"
    # PBI_AUTOFIX=1 branch: repair, then the re-check must be clean
    fix_code, fixed = run_fix(model, "F001")
    assert fix_code == 0 and violations(fixed, "F001") == [], (
        f"auto-fix did NOT fully resolve the stray commas: {violations(fixed)}")
    code2, again = run_check(model, "F001")
    assert code2 == 0
    # second run changes nothing
    snapshot = {p: p.read_bytes() for p in model.rglob("*.tmdl")}
    run_fix(model, "F001")
    assert {p: p.read_bytes() for p in model.rglob("*.tmdl")} == snapshot


def test_comma_in_label_is_preserved_by_fix(stand_in):
    model = _model(stand_in, "fp_comma_in_label")
    run_fix(model)
    text = (model / "definition" / "tables" / "x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert '"Sessions, , Organic"' in text
