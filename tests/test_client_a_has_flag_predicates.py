"""Count flags (int64) are never compared to 1 or a boolean; boolean flags are
never compared to a number (spec A-typed-flag-predicates)."""

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

RULE = "typed-flag-predicates"
CONFIG = {"rules": {RULE: {
    "model": GROWTH_A,
    "table": "Subscriptions",
    "prefix": "has_",
    "measures_files": ["Client-a Measures"],
    "min_predicates": 25,
    "canaries": [["has_new", ">", "0"], ["has_churn", "=", "TRUE"]],
}}}


def _run(stand_in, mutation=None):
    root = stand_in(FLEET)
    if mutation:
        mutate(root, mutation)
    return run_check(root, RULE, config=CONFIG)


@pytest.mark.p0
def test_recognizer_is_not_vacuous(stand_in):
    code, payload = _run(stand_in)
    assert mentioning(payload) == []
    assert code == 0


@pytest.mark.p0
def test_countif_flags_are_never_compared_to_one(stand_in):
    _code, payload = _run(stand_in)
    assert not mentioning(payload, "has_return")
    assert not mentioning(payload, "has_new")


@pytest.mark.p0
def test_boolean_flags_are_never_compared_numerically(stand_in):
    _code, payload = _run(stand_in)
    assert not mentioning(payload, "has_limbo")
    assert not mentioning(payload, "has_churn")


class TestNegativeControls:
    def test_countif_flags_are_never_compared_to_one(self, stand_in):
        code, payload = _run(stand_in, "count_flag_eq_one")  # Subscriptions[has_return] = 1
        assert code == 1
        assert len(mentioning(payload, "has_return")) == 1

    def test_boolean_flags_are_never_compared_numerically(self, stand_in):
        code, payload = _run(stand_in, "boolean_flag_gt_zero")  # Subscriptions[has_limbo] > 0
        assert code == 1
        assert len(mentioning(payload, "has_limbo")) == 1
