"""N020 dimension-prefix-floor: the count, the wording and the severity.

The rule is opt-in and disabled by default: select it and set
``enabled = true``. It counts the table FILES whose name starts with the
prefix -- the convention is a naming convention, so the file name is what
counts -- and fails the run when there are fewer than the floor.

The stand-in is the fictional coffee roastery (three dimension tables) and
the same model with twenty.
"""
from __future__ import annotations

import shutil

import pytest

from conftest import FIXTURES, run_check, violations

MODELS = FIXTURES / "live" / "models"
RULE = "N020"
CONFIG = {"rules": {RULE: {"enabled": True, "min_dimension_tables": 20}}}


@pytest.fixture
def roastery(tmp_path):
    target = tmp_path / "coffee"
    shutil.copytree(MODELS / "coffee", target)
    return target


def test_the_floor_not_met_fails_the_run(roastery):
    code, payload = run_check(roastery, RULE, config=CONFIG)
    found = violations(payload, "N020")
    assert len(found) == 1
    assert found[0]["message"] == (
        "Expected at least 20 dimension tables starting with '_', found 3")
    assert found[0]["severity"] == "error"
    assert code == 1


def test_the_count_is_the_file_name_not_the_declared_table(roastery):
    """The convention is about the file name, so a renamed file counts."""
    tables = roastery / "Coffee.SemanticModel" / "definition" / "tables"
    (tables / "Sales.tmdl").rename(tables / "_Sales.tmdl")
    code, payload = run_check(roastery, RULE, config=CONFIG)
    assert violations(payload, "N020")[0]["message"] == (
        "Expected at least 20 dimension tables starting with '_', found 4")


def test_the_floor_met_says_how_many_and_shows_a_sample(tmp_path):
    target = tmp_path / "coffee-20-dims"
    shutil.copytree(MODELS / "coffee-20-dims", target)
    code, payload = run_check(target, RULE, config=CONFIG)
    found = violations(payload, "N020")
    assert len(found) == 1
    assert found[0]["severity"] == "info"
    lines = found[0]["message"].split("\n")
    assert lines[0] == "✅ Found 20 dimension tables starting with '_'"
    assert lines[1] == "Sample dimension tables:"
    assert lines[2:] == [f"  - {name}" for name in sorted(
        p.stem for p in (target / "Coffee.SemanticModel" / "definition" / "tables").glob("_*.tmdl")
    )[:10]]
    assert code == 0


def test_the_rule_is_off_until_it_is_asked_for(roastery):
    code, payload = run_check(roastery, RULE)
    assert violations(payload, "N020") == []
    assert "dimension-prefix-floor" in payload.get("skipped", [])
