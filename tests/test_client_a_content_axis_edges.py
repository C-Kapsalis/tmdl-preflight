"""The `_Content` axis of the client-a Growth model carries exactly its recorded
edges and never a `'_Landing Pages'` -> `_Content` edge (spec A-model-contract-relationships,
axis contract). Runs on the fictional stand-in fleet."""

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

pytestmark = [pytest.mark.p0, pytest.mark.layer1]

RULE = "model-contract-relationships"
SANCTIONED_EDGES = [
    {"table": "_Campaigns", "column": "content_group_id", "active": True},
    {"table": "Queries Paid", "column": "content_group_id", "active": False},
    {"table": "_Assets", "column": "content_report_group_id", "active": True},
    {"table": "_Users", "column": "first_view_content_group_id", "active": False},
    {"table": "_Users", "column": "first_landing_content_group_id", "active": False},
]
FORBIDDEN_TABLE = "_Landing Pages"
CONFIG = {"rules": {RULE: {"axes": [{
    "model": GROWTH_A,
    "dimension": "_Content",
    "forbidden": [FORBIDDEN_TABLE],
    "sanctioned": SANCTIONED_EDGES,
}]}}}


def test_no_landing_pages_edge_on_the_content_axis(stand_in):
    root = stand_in(FLEET)
    _code, payload = run_check(root, RULE, config=CONFIG)
    assert not mentioning(payload, FORBIDDEN_TABLE)


def test_content_axis_carries_exactly_the_recorded_edges(stand_in):
    root = stand_in(FLEET)
    code, payload = run_check(root, RULE, config=CONFIG)
    assert mentioning(payload) == []
    assert code == 0


class TestNegativeControls:
    """The same assertions on mutated stand-ins (the earlier check fails on each)."""

    def test_no_landing_pages_edge_on_the_content_axis(self, stand_in):
        root = stand_in(FLEET)
        mutate(root, "landing_edge")  # inactive '_Landing Pages'.content_group_id -> _Content
        code, payload = run_check(root, RULE, config=CONFIG)
        assert code == 1
        assert mentioning(payload, FORBIDDEN_TABLE)

    def test_content_axis_carries_exactly_the_recorded_edges(self, stand_in):
        root = stand_in(FLEET)
        mutate(root, "queries_paid_active")  # the sanctioned inactive edge turned active
        code, payload = run_check(root, RULE, config=CONFIG)
        assert code == 1
        assert mentioning(payload, "Queries Paid")
