"""Grain-guarded measures blank under every registered below-grain column
(spec A-grain-guard-coverage, variant B: below-grain guards)."""

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
    """Apply one recorded stand-in mutation (the same edit the parity run used)."""
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

pytestmark = [pytest.mark.p0, pytest.mark.layer1]

RULE = "grain-guard-coverage"
INSIGHTS = "spinout_02_db/insights.SemanticModel"
GRAIN_GUARDS = {
    "^Accounts #": ["_m Organizations", "_m Users"],
    "^ALL HS Companies #": ["_m Users"],
}
CONFIG = {"rules": {RULE: {"below": {
    "model": INSIGHTS,
    "host_table": "Backend Measures",
    "guards": GRAIN_GUARDS,
}}}}


@pytest.mark.parametrize(
    ("measure", "below_table"),
    [(m, t) for m, tables in GRAIN_GUARDS.items() for t in tables],
)
def test_grain_guard_covers_every_registered_column(stand_in, measure, below_table):
    root = stand_in(FLEET)
    code, payload = run_check(root, RULE, config=CONFIG)
    assert not mentioning(payload, measure, below_table)
    assert code == 0


class TestNegativeControls:
    def test_grain_guard_covers_every_registered_column(self, stand_in):
        root = stand_in(FLEET)
        mutate(root, "insights_guard_misses_signup")  # ^ALL HS Companies # drops signup_month
        code, payload = run_check(root, RULE, config=CONFIG)
        assert code == 1
        found = mentioning(payload, "^ALL HS Companies #", "signup_month")
        assert len(found) == 1
        # the commented-out (deregistered) row is never demanded
        assert not mentioning(payload, "legacy_flag")

    def test_model_file_absent_is_skipped(self, stand_in):
        root = stand_in(FLEET)
        (root / INSIGHTS / "definition" / "tables" / "Backend Measures.tmdl").unlink()
        code, payload = run_check(root, RULE, config=CONFIG)
        assert code == 0
        assert mentioning(payload) == []
        pytest.skip("guard host table not found: the below-grain check is skipped")
