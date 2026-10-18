"""The Daily calculation item keeps ratios at their period value and averages only
additive measures (spec A-calc-item-blind-average)."""

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

pytestmark = [pytest.mark.layer1]

RULE = "calc-item-blind-average"
MODELS = [TEMPLATE, "spinout_04_db/Performance.SemanticModel", GROWTH_E, GROWTH_A,
          "spinout_02_db/insights.SemanticModel"]
LEGACY = {"spinout_04_db/Performance.SemanticModel"}
NO_TOGGLE = {GROWTH_E, GROWTH_A, "spinout_02_db/insights.SemanticModel"}


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.replace(".SemanticModel", ""))
def test_daily_item_guards_ratios(stand_in, model):
    root = stand_in(FLEET)
    code, payload = run_check(root / model, RULE)
    if model in NO_TOGGLE:
        # no 'z-Toggle Daily Calculation' table: the check does not apply
        assert mentioning(payload) == [] and code == 0
        pytest.skip("model has no z-Toggle Daily Calculation table")
    if model in LEGACY:
        # legacy blind-average form: the original gate fails this model
        assert code == 1
        assert len(violations(payload)) >= 1
        assert "Daily" in violations(payload)[0]["message"]
        return
    assert mentioning(payload) == []
    assert code == 0
