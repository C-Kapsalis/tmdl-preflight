"""The Performance Max guard sits on the search_term arm of [CPC] only, with exactly
the two PMAX spellings (spec A-measure-arm-scoped-filter)."""

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

RULE = "measure-arm-scoped-filter"
MODELS = [TEMPLATE, GROWTH_E]  # the fixture fleet: template plus every model declaring [CPC]
IDS = [m.replace(".SemanticModel", "") for m in MODELS]
CONFIG = {"rules": {RULE: {
    "template": TEMPLATE,
    "measure": "CPC",
    "host_table": "#Report Measures",
    "column": "_Campaigns[Campaign Type]",
    "target_arm": "search_term",
    "literals": ["performance_max", "performance max"],
    "forbidden_literal": "search & content",
}}}


def _findings(payload, model):
    folder = model.split("/")[0]
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in violations(payload) if folder in (v.get("path") or "") or folder in (v.get("file") or "")]


def test_universe_is_the_fleet(stand_in):
    """Discovery must find the template plus at least one more model declaring [CPC]."""
    root = stand_in(FLEET)
    code, payload = run_check(root, RULE, config=CONFIG)
    assert not [v for v in violations(payload) if "discover" in v["message"] or "universe" in v["message"]]
    assert code == 0
    declaring = [m for m in MODELS
                 if "measure CPC" in (root / m / "definition" / "tables" / "#Report Measures.tmdl").read_text(encoding="utf-8")]
    assert len(declaring) >= 2 and TEMPLATE in declaring


@pytest.mark.parametrize("model", MODELS, ids=IDS)
def test_pmax_guard_present_on_search_term_arm(stand_in, model):
    root = stand_in(FLEET)
    _code, payload = run_check(root, RULE, config=CONFIG)
    assert _findings(payload, model) == []


@pytest.mark.parametrize("model", MODELS, ids=IDS)
def test_pmax_guard_absent_from_other_arms(stand_in, model):
    root = stand_in(FLEET)
    _code, payload = run_check(root, RULE, config=CONFIG)
    assert _findings(payload, model) == []


@pytest.mark.parametrize("model", MODELS, ids=IDS)
def test_pmax_literal_set_is_exactly_the_two_spellings(stand_in, model):
    root = stand_in(FLEET)
    _code, payload = run_check(root, RULE, config=CONFIG)
    assert _findings(payload, model) == []


class TestNegativeControls:
    def test_pmax_guard_moved_to_keyword_arm(self, stand_in):
        """Original: present_on_search_term_arm and absent_from_other_arms both fail."""
        root = stand_in(FLEET)
        mutate(root, "cpc_guard_on_keyword")
        code, payload = run_check(root, RULE, config=CONFIG)
        assert code == 1
        found = _findings(payload, GROWTH_E)
        assert any("search_term" in v["message"] for v in found)
        assert any("keyword" in v["message"] for v in found)
        assert _findings(payload, TEMPLATE) == []

    def test_pmax_literal_set_is_exactly_the_two_spellings(self, stand_in):
        root = stand_in(FLEET)
        mutate(root, "cpc_extra_literal")  # "search & content" added to the guard
        code, payload = run_check(root, RULE, config=CONFIG)
        assert code == 1
        assert any("search & content" in v["message"] for v in _findings(payload, GROWTH_E))
