"""Engine reach helpers carry one identical (table, key) list that covers every
`_` dimension with its slicer key (spec A-reach-guard-helper-consistency)."""

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

RULE = "reach-guard-helper-consistency"
REBASED = ["-helper Slicer Cannot Reach Users", "-helper Slicer Cannot Reach Transactions"]
FILTER_MISSES = [
    "-helper Filter Misses User Views",
    "-helper Filter Misses GA4 Traffic Acquisition",
    "-helper Filter Misses GA4 Conversions",
    "-helper Filter Misses Email Campaigns",
    "-helper Filter Misses Email Lists",
    "-helper Filter Misses Content",
]
CONFIG = {"rules": {RULE: {
    "model": GROWTH_A,
    "host_table": "Client-a Measures",
    "helpers": REBASED + FILTER_MISSES,
    "min_filter_misses": len(FILTER_MISSES),
    "reference_helper": REBASED[1],
    "canary": ["_Campaigns", "ad_group_x_id"],
    "exclusions": {"_Analysis Category": "field-parameter registry, never a row filter on a fact"},
    "natural_keys": {"_Cluster Mappings": "Cluster Value"},
}}}


def _clean(stand_in):
    root = stand_in(FLEET)
    code, payload = run_check(root, RULE, config=CONFIG)
    return code, payload


def test_helpers_are_present_and_parse(stand_in):
    code, payload = _clean(stand_in)
    assert not [v for v in violations(payload) if any(h in v["message"] for h in REBASED + FILTER_MISSES)
                and "not found" in v["message"]]
    assert code == 0


def test_every_helper_carries_the_identical_dimension_list(stand_in):
    code, payload = _clean(stand_in)
    assert mentioning(payload) == []


def test_dimension_list_covers_every_underscore_table(stand_in):
    code, payload = _clean(stand_in)
    assert mentioning(payload) == []


def test_each_key_is_the_slicer_key_never_the_whole_table(stand_in):
    code, payload = _clean(stand_in)
    assert mentioning(payload) == []


class TestNegativeControls:
    def test_every_helper_carries_the_identical_dimension_list(self, stand_in):
        root = stand_in(FLEET)
        mutate(root, "helper_drops_offers")  # one Filter Misses helper loses its _Offers term
        code, payload = run_check(root, RULE, config=CONFIG)
        assert code == 1
        assert mentioning(payload, "_Offers")
