"""Cost ratios over basis-aware counts blank outside the enhanced allocation
window (spec A-guarded-ratio-wrapper)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FIXTURES, run_check, violations

FLEET = "layer1_contract_fleet"
GROWTH_A = "spinout_12_db/Growth.SemanticModel"
GROWTH_E = "spinout_05_db/Growth.SemanticModel"
TEMPLATE = "universal/Performance.SemanticModel"
_MUTATIONS = json.loads((FIXTURES / f"{FLEET}.mutations.json").read_text(encoding="utf-8"))


def mutate(root: Path, name: str) -> None:
    """Apply one recorded stand-in mutation (the same edit the reference run used)."""
    for edit in _MUTATIONS[name]:
        rel, old, new = edit[:3]
        nth = edit[3] if len(edit) > 3 else None
        path = root / rel
        if old == "":
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            if text and not text.endswith("\n\n"):
                text += "\n"
            path.write_text(text + new, encoding="utf-8")
            continue
        text = path.read_text(encoding="utf-8")
        if nth is None:
            assert text.count(old) == 1, f"{name}: expected one match in {rel}"
            text = text.replace(old, new)
        else:
            idx = -1
            for _ in range(nth + 1):
                idx = text.index(old, idx + 1)
            text = text[:idx] + new + text[idx + len(old):]
        path.write_text(text, encoding="utf-8")


def mentioning(payload: dict, *needles: str) -> list[dict]:
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in violations(payload) if all(n in v["message"] for n in needles)]

pytestmark = [pytest.mark.layer1, pytest.mark.client]

RULE = "guarded-ratio-wrapper"
GUARD = "-helper Enhanced Window Unallocated"
START = "-helper Enhanced Allocation Start"
CONFIG = {"rules": {RULE: {
    "model": GROWTH_A,
    "host_table": "Client-a Measures",
    "selector_table": "'z-Selector Attribution Basis'",
    "numerators": ["Cost", "^Cost"],
    "guard": GUARD,
    "boundary": START,
    "measured_option": "00. Measured",
    "enhanced_option": "01. Enhanced (allocated)",
    "count_measure": "Accounts #",
    "min_measures": 100,
    "canary_counts": ["Accounts #", "New Clients #"],
    "canary_ratios": ["Cost/ New Client", "^Cost/ New Client", "Cost/ Account", "^Cost/ Account"],
}}}


def _run(stand_in, mutation=None):
    root = stand_in(FLEET)
    if mutation:
        mutate(root, mutation)
    return run_check(root, RULE, config=CONFIG)


@pytest.mark.p0
def test_recognizer_is_not_vacuous(stand_in):
    code, payload = _run(stand_in)
    assert not mentioning(payload, "recogni")
    assert code == 0


@pytest.mark.p0
def test_every_enhanced_cost_ratio_is_window_guarded(stand_in):
    _code, payload = _run(stand_in)
    assert mentioning(payload) == []


@pytest.mark.p0
def test_guard_is_inert_on_measured_basis(stand_in):
    _code, payload = _run(stand_in)
    assert not mentioning(payload, GUARD)


@pytest.mark.p0
def test_boundary_is_derived_not_hardcoded(stand_in):
    _code, payload = _run(stand_in)
    assert not mentioning(payload, START)


@pytest.mark.p0
def test_guard_helpers_are_not_themselves_cost_ratios(stand_in):
    _code, payload = _run(stand_in)
    assert mentioning(payload) == []


class TestNegativeControls:
    def test_every_enhanced_cost_ratio_is_window_guarded(self, stand_in):
        code, payload = _run(stand_in, "ratio_unguarded")  # guard replaced by FALSE ()
        assert code == 1
        assert mentioning(payload, "Cost/ Account")

    def test_boundary_is_derived_not_hardcoded(self, stand_in):
        code, payload = _run(stand_in, "boundary_hardcoded")  # DATE ( 2026, 6, 1 ) injected
        assert code == 1
        assert mentioning(payload, START)
