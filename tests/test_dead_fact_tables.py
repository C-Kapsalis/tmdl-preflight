"""Ratcheted gate: no NEW dead fact tables (spec A-dead-fact-tables).

A DEAD fact table is one no measure actually READS: its only DAX mentions are
filter-context sensors (ISFILTERED / ISEMPTY / ISINSCOPE / ...) or nothing at
all. That is the residue an incomplete category drop leaves behind, and sensing
looks like ownership to anything that derives categories by containment, so the
table survives forever.

Ratcheted, not hard: some models carry legitimately measure-free data-only
tables. A baseline (same shape as the earlier check floor file:
``{"<folder>/<Model>.SemanticModel": [table, ...]}``) records the known
population; the rule fails only on GROWTH. A baseline entry that is no longer
dead prints a tighten hint and does not fail. A missing baseline file fails.

Stand-in (tests/fixtures/b3-a2/dead_fact_tables/roastery): ``Orders`` is read
by SUM (alive), ``Returns`` is referenced only inside ISFILTERED (dead),
``Shipments`` only inside a comment (dead).
"""
from __future__ import annotations

import json

import pytest

from conftest import run_check, violations

RULE = "dead-fact-tables"
MODEL = "df_db/Roastery.SemanticModel"

# baseline content -> earlier verdict (recorded on the stand-in)
FLOORS = [
    pytest.param({}, "fail", ["Returns", "Shipments"], id="empty-floor"),
    pytest.param({MODEL: ["Returns", "Shipments"]}, "pass", [], id="full-floor"),
    pytest.param({MODEL: ["Returns"]}, "fail", ["Shipments"], id="partial-floor"),
    pytest.param({MODEL: ["Orders", "Returns", "Shipments"]}, "pass", [], id="over-floor"),
]


def _run(stand_in, tmp_path, floor):
    root = stand_in("b3-a2/dead_fact_tables/roastery")
    cfg = {"rules": {RULE: {}}}
    if floor is not None:
        base = tmp_path / "dead_fact_tables_floor.json"
        base.write_text(json.dumps(floor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        cfg["rules"][RULE]["baseline"] = str(base)
    else:
        cfg["rules"][RULE]["baseline"] = str(tmp_path / "missing-floor.json")
    return run_check(root, RULE, config=cfg)


@pytest.mark.parametrize("floor,verdict,new", FLOORS)
def test_no_new_dead_fact_tables(stand_in, tmp_path, floor, verdict, new):
    code, payload = _run(stand_in, tmp_path, floor)
    assert "summary" in payload, payload
    found = violations(payload)
    assert sorted(v["object"] for v in found) == sorted(new)
    assert (code == 0) == (verdict == "pass")
    if floor.get(MODEL) and "Orders" in floor[MODEL]:
        # Orders is alive again: tighten hint, never a failure
        assert "tighten" in json.dumps(payload).lower()


def test_missing_floor_fails(stand_in, tmp_path):
    code, payload = _run(stand_in, tmp_path, None)
    assert code != 0
    assert "baseline" in json.dumps(payload).lower() or "floor" in json.dumps(payload).lower()
