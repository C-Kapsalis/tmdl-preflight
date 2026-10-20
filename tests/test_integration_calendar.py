"""Integration pattern: calendar relationships.

* C-fact-calendar-coverage  (test_fact_tables_have_calendar_relationships)
* C-calendar-relationship-cardinality (test_calendar_relationship_cardinality)
* C-calendar-standard-columns (test_calendar_table_completeness, advisory)

Stand-in: ``universal`` has facts Orders (active link) and Visits (inactive
link) -> 100%; ``failing_db`` adds Refunds with no calendar link (2/3 = 66.7%),
sets ``toCardinality: many`` on Orders -> __Calendar, and drops ``Week``.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"
class TestFactCalendarCoverage:
    RULE = "fact-calendar-coverage"

    def test_fact_tables_have_calendar_relationships(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert violations(payload) == []

    def test_coverage_below_threshold_lists_uncovered_tables(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1  # one aggregate finding
        assert "Refunds" in found[0]["message"]
        assert "Visits" not in found[0]["message"]  # inactive link counts as covered

    def test_threshold_is_configurable(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True,
                                  config={"rules": {self.RULE: {"min_fact_coverage_percent": 60.0}}})
        assert code == 0 and violations(payload) == []

    def test_disabled_by_policy_is_skipped(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True,
                                  config={"rules": {self.RULE: {"require_fact_link": False}}})
        assert code == 0
        assert self.RULE in payload.get("skipped", [])
class TestCalendarRelationshipCardinality:
    RULE = "calendar-relationship-cardinality"

    def test_calendar_relationship_cardinality(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0, payload
        assert violations(payload) == []

    def test_to_cardinality_many_is_one_violation(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "Orders[order_date]" in found[0]["message"]
        assert "many" in found[0]["message"]
class TestCalendarStandardColumns:
    RULE = "calendar-standard-columns"

    def test_calendar_table_completeness(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0 and violations(payload) == []

    def test_missing_week_is_one_info_finding(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE)
        assert code == 0  # advisory: never fails (earlier versions asserted nothing)
        found = violations(payload)
        assert len(found) == 1
        assert found[0]["severity"] == "info"
        assert "Week" in found[0]["message"]

    def test_no_calendar_rule_does_not_apply(self, stand_in):
        model = _model(stand_in, "spinout_02_db").parent / "insights.SemanticModel"
        code, payload = run_check(model, self.RULE)
        assert code == 0 and violations(payload) == []
