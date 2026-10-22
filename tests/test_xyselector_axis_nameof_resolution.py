"""Every NAMEOF target inside a field-parameter axis partition must resolve.

A NAMEOF pointing at nothing makes the whole
calculated table fail to evaluate (and every table built from it). A MEASURE
resolves whatever table qualifies it in the earlier check axis gate; a COLUMN must
exist on the named table; doubled quotes are unescaped; parked rows are exempt.
No auto-fix: only a human knows whether the target was renamed or retired.

Rule: D002 nameof-resolution (stricter merged rule E-nameof-resolution). The
kernel axis helper and model discovery -> `check --select D002` on stand-ins.
"""

from __future__ import annotations

import shutil
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


def _errors(payload):
    return [v for v in violations(payload, "D002") if v["severity"] == "error"]


@pytest.mark.parametrize(
    "sid, verdict",
    _cases(
        fails={"fp_nameof_dangling", "fp_nameof_wrong_table_column"},
        # STRICTER: a measure qualified with a table that does not host it
        # ('Sales'[Margin %]) and a missing table ('Shops'[Units]) passed the
        # axis gate (measure found anywhere); D002 reports both as errors.
        overrides={"fp_nameof_strict": "fail"},
    ),
)
def test_axis_nameof_targets_exist(stand_in, sid, verdict):
    code, payload = run_check(_model(stand_in, sid), "D002")
    bad = _errors(payload)
    if verdict == "pass":
        assert bad == [], f"NAMEOF target(s) do not exist in {sid}: {bad}"
        return
    assert bad and code == 1
    assert all("not found" in v["message"].lower() for v in bad)


def test_instrument_detects_a_planted_dangling_reference(tmp_path):
    """The gate must actually fire: prove it on a copy of the template."""
    src = FIXTURES / "template" / "Performance.SemanticModel" / "definition"
    if not src.is_dir():
        pytest.skip("template model not present")
    model = tmp_path / "Planted.SemanticModel"
    dst = model / "definition"
    (dst / "tables").mkdir(parents=True)
    for f in (src / "tables").glob("*.tmdl"):
        shutil.copyfile(f, dst / "tables" / f.name)

    assert _errors(run_check(model, "D002")[1]) == [], "baseline copy should be clean"

    victim = dst / "tables" / "x-Selector 1.tmdl"
    text = victim.read_text(encoding="utf-8")
    marker = "NAMEOF ( '_Landing Pages'[Domain] )"
    if marker not in text:
        marker = next((l.strip() for l in text.split("\n") if "NAMEOF" in l and "[" in l), None)
        if marker is None:
            pytest.skip("no NAMEOF row to plant against")
    planted = text.replace(marker, "NAMEOF ( 'Table That Does Not Exist'[Nope] )", 1)
    assert planted != text, "failed to plant the dangling reference"
    victim.write_text(planted, encoding="utf-8")

    found = _errors(run_check(model, "D002")[1])
    assert found, "gate did NOT detect a planted dangling reference"
    assert any("Table That Does Not Exist" in (v["message"] + (v.get("object") or "")) for v in found), found
