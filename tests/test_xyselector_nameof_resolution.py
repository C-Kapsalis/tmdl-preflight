"""Every ACTIVE NAMEOF row of the x-/y-Selector field-parameter tables resolves.

Ported from the layer-1 suite. Resolution rules: bare `[X]` -> a measure X in
some table; `'Table'[X]` / `Table[X]` -> the table exists and X is one of its
measures or columns; names compared case-insensitively with doubled quotes
unescaped; an unparseable reference is a failure ("invalid NAMEOF syntax").
Parked (`--`/`//`) rows are exempt. Models without axis tables are skipped.

Rule: D002 nameof-resolution. The growth merge script's row extractor, the
kernel index and model discovery -> `check --select D002` on stand-ins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

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
    _cases(fails={"fp_nameof_dangling", "fp_nameof_strict", "fp_nameof_wrong_table_column"},
           skips={"fp_no_axis_tables"}),
)
def test_xyselector_nameof_targets_resolve(stand_in, sid, verdict):
    code, payload = run_check(_model(stand_in, sid), "D002")
    dangling = [v for v in violations(payload, "D002") if v["severity"] == "error"]
    if verdict == "fail":
        assert dangling and code == 1
        msgs = " ".join(v["message"] for v in dangling)
        if sid == "fp_nameof_dangling":
            assert "Margin" in msgs
        if sid == "fp_nameof_strict":
            assert "Shops" in msgs and "Margin %" in msgs
        if sid == "fp_nameof_wrong_table_column":
            assert "Month" in msgs
        return
    assert dangling == [], "Active rows with unresolvable NAMEOF targets: " + str(dangling)
    if verdict == "skip":
        pytest.skip("model has no x-/y-Selector field-parameter tables")
