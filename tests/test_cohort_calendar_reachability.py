"""Cohort calendars reach every subject-bearing fact within two active hops
(spec A-cohort-calendar-reach); no anchor calendar reaches nothing, ratcheted by
a baseline (spec A-dead-anchor-calendar). Runs on the fictional stand-in fleet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FIXTURES, run_check, run_cli, violations

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

REACH = "cohort-calendar-reach"
DEAD = "dead-anchor-calendar"
REACH_CONFIG = {"rules": {REACH: {"cohort_date_suffix": "Cohort Date", "max_hops": 2}}}
DEAD_CONFIG = {"rules": {DEAD: {"template": TEMPLATE}}}


def test_cohort_calendars_reach_every_subject_bearing_fact(stand_in):
    root = stand_in(FLEET)
    code, payload = run_check(root, REACH, config=REACH_CONFIG)
    assert mentioning(payload) == []
    assert code == 0


def test_cohort_calendar_discovery_is_column_keyed_not_name_keyed(stand_in):
    """A cohort calendar without "Cohort" in its table name is still checked.

    The stand-in's `__Registration Calendar` owns `Registration Cohort Date`. Cutting
    its subject edge must produce a finding naming it; a name-keyed discovery would
    stay silent.
    """
    root = stand_in(FLEET)
    tables = root / GROWTH_A / "definition" / "tables"
    owners = [p.stem for p in tables.glob("*.tmdl")
              if "\tcolumn 'Registration Cohort Date'" in p.read_text(encoding="utf-8")]
    assert owners and all("Cohort" not in name for name in owners)
    mutate(root, "registration_calendar_cut")
    code, payload = run_check(root, REACH, config=REACH_CONFIG)
    assert code == 1
    assert mentioning(payload, "__Registration Calendar")


def test_no_new_dead_anchor_calendars(stand_in):
    """Empty floor (the committed baseline is `{}`): no dead anchor calendar today."""
    root = stand_in(FLEET)
    code, payload = run_check(root, DEAD, config=DEAD_CONFIG)
    assert mentioning(payload) == []
    assert code == 0


class TestNegativeControls:
    def test_cohort_calendars_reach_every_subject_bearing_fact(self, stand_in):
        root = stand_in(FLEET)
        mutate(root, "offer_cohort_calendar")  # '__Offer Cohort Calendar' -> Subscriptions only
        code, payload = run_check(root, REACH, config=REACH_CONFIG)
        assert code == 1
        found = mentioning(payload, "__Offer Cohort Calendar")
        assert found and any("User Views" in v["message"] for v in found)

    def test_no_new_dead_anchor_calendars(self, stand_in):
        root = stand_in(FLEET)
        mutate(root, "dead_anchor_calendar")  # '__First Order Calendar' with no relationship
        code, payload = run_check(root, DEAD, config=DEAD_CONFIG)
        assert code == 1
        assert mentioning(payload, "__First Order Calendar")
        # the template's own calendars are never anchors
        assert not mentioning(payload, "'__Calendar'")

    def test_no_new_dead_anchor_calendars_accepted_in_baseline(self, stand_in, tmp_path):
        """A dead calendar recorded in the floor (here: the tool baseline) does not fail."""
        root = stand_in(FLEET)
        mutate(root, "dead_anchor_calendar")
        cfg = tmp_path / "dead.json"
        cfg.write_text(json.dumps(DEAD_CONFIG), encoding="utf-8")
        baseline = tmp_path / "floor.json"
        code, _out, _err = run_cli("baseline", root, "--output", baseline, "--config", cfg)
        assert code == 0
        code, payload = run_check(root, DEAD, config=cfg, args=("--baseline", str(baseline)))
        assert code == 0
        assert mentioning(payload) == []
