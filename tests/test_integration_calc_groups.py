"""Integration pattern: required calculation-group tables (C-required-calc-groups).

Stand-in: ``universal`` carries both ``z-Selector Format`` and
``z-Selector Time Intelligence Function``; ``failing_db`` lacks the second.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"
RULE = "required-calc-groups"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"
def test_calculation_group_infrastructure_exists(stand_in):
    code, payload = run_check(_model(stand_in), RULE)
    assert code == 0, payload
    assert violations(payload) == []
def test_calculation_group_infrastructure_missing_table_fails(stand_in):
    code, payload = run_check(_model(stand_in, "failing_db"), RULE)
    assert code == 1
    found = violations(payload)
    assert len(found) == 1
    assert "z-Selector Time Intelligence Function" in found[0]["message"]
    assert found[0]["severity"] == "error"
def test_calculation_group_check_skipped_when_both_disabled(stand_in):
    model = _model(stand_in, "failing_db")
    code, payload = run_check(model, RULE, config={"rules": {RULE: {
        "format_selector": False, "time_intelligence_selector": False}}})
    assert code == 0
    assert violations(payload) == []
    assert RULE in payload.get("skipped", [])
def test_calculation_group_one_switch_off_still_checks_the_other(stand_in):
    model = _model(stand_in, "failing_db")
    code, payload = run_check(model, RULE, config={"rules": {RULE: {"format_selector": False}}})
    assert code == 1 and len(violations(payload)) == 1
def test_calculation_group_item_completeness(stand_in):
    """The z-Selector inventory is report output only, never a finding."""
    code, payload = run_check(_model(stand_in), RULE)
    assert code == 0
    assert violations(payload) == []
def test_calculation_group_format_inference(stand_in):
    """The SELECTEDMEASURENAME count is advisory: it never raises an error."""
    code, payload = run_check(_model(stand_in), RULE)
    assert [v for v in violations(payload) if v["severity"] == "error"] == []
