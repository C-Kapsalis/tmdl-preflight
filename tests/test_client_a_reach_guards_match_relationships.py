"""The GA4 reach guard names exactly the tables that cannot reach the fact, and the
relationship graph still agrees (spec A-model-contract-relationships, reach guards)."""

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

pytestmark = [pytest.mark.layer1, pytest.mark.client]

RULE = "model-contract-relationships"
CONTROLS = ["_Landing Pages", "_Countries", "_Devices", "_Accounts", "_Campaigns"]
MODELS = {"spinout-12/Growth": GROWTH_A, "universal/Performance": TEMPLATE}
GUARDS = {
    "universal/Performance": {"fact": "GA4 Conversions", "guarded": ["_Queries", "_Keywords"]},
    "spinout-12/Growth": {"fact": "GA4 Conversions", "guarded": ["_Queries", "_Keywords", "_Offers"]},
}
GUARD_MEASURE = {"table": "Helper Measures", "measure": "-helper y-drilldown ga4 unreachable"}


def _config(label: str, **parts) -> dict:
    entry = {"model": MODELS[label], "fact": GUARDS[label]["fact"]}
    entry.update(parts)
    return {"rules": {RULE: {"reach_guards": [entry]}}}


@pytest.mark.p0
@pytest.mark.parametrize("model", sorted(MODELS))
def test_relationship_parser_is_not_vacuous(stand_in, model):
    root = stand_in(FLEET)
    code, payload = run_check(root, RULE, config=_config(model, min_active_edges=40))
    assert mentioning(payload) == []
    assert code == 0


@pytest.mark.p0
@pytest.mark.parametrize("label", sorted(GUARDS))
def test_guarded_tables_still_cannot_reach_the_fact(stand_in, label):
    root = stand_in(FLEET)
    _code, payload = run_check(root, RULE, config=_config(label, guarded=GUARDS[label]["guarded"]))
    assert mentioning(payload) == []


@pytest.mark.p0
@pytest.mark.parametrize("label", sorted(GUARDS))
def test_control_tables_still_reach_the_fact(stand_in, label):
    root = stand_in(FLEET)
    _code, payload = run_check(root, RULE, config=_config(label, controls=CONTROLS))
    assert mentioning(payload) == []


@pytest.mark.p0
@pytest.mark.parametrize("label", sorted(GUARDS))
def test_guard_expression_names_exactly_the_guarded_tables(stand_in, label):
    root = stand_in(FLEET)
    _code, payload = run_check(root, RULE, config=_config(
        label, guarded=GUARDS[label]["guarded"], guard_measure=GUARD_MEASURE))
    assert mentioning(payload) == []


class TestNegativeControls:
    @pytest.mark.parametrize("label", ["universal/Performance"])
    def test_guarded_tables_still_cannot_reach_the_fact(self, stand_in, label):
        root = stand_in(FLEET)
        mutate(root, "ga4_reaches_queries")  # active GA4 Conversions -> _Queries edge
        code, payload = run_check(root, RULE, config=_config(label, guarded=GUARDS[label]["guarded"]))
        assert code == 1
        assert mentioning(payload, "_Queries")
