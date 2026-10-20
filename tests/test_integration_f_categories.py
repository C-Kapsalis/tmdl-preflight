"""Integration pattern: f-measure shapes (C-f-measure-pattern).

Every ``f-`` measure must be STANDARD (ISEMPTY / ISINSCOPE / ISFILTERED),
AGGREGATOR (two or more ``[f-...]`` joined by + - *), SWITCH-ROUTER
(``SWITCH(TRUE()``), DISPLAY-STRING (hosted in a ``w-`` table, or
CONCATENATEX), or the exempt ``f-Analysis Category``. The earlier check's
"template f-measures present in the client" half is a template comparison
owned by tmdl-drift-doctor (detect ``measure.missing``), not covered here.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"
RULE = "f-measure-pattern"


def _model(stand_in, client="universal", model="Performance.SemanticModel"):
    return stand_in(STANDIN) / client / model
def test_f_measure_pattern_validation(stand_in):
    code, payload = run_check(_model(stand_in), RULE, strict=True)
    assert code == 0, payload
    assert violations(payload) == []
def test_f_measure_pattern_unclassified_fails(stand_in):
    code, payload = run_check(_model(stand_in, "failing_db"), RULE, strict=True)
    assert code == 1
    found = violations(payload)
    assert len(found) == 1
    assert "f-Filters[f-Odd]" in found[0]["message"]
def test_f_measure_exemption_list_is_configurable(stand_in):
    code, payload = run_check(_model(stand_in, "failing_db"), RULE, strict=True,
                              config={"rules": {RULE: {"exempt": ["f-Analysis Category", "f-Odd"]}}})
    assert code == 0 and violations(payload) == []
def test_f_measure_coverage_analytics(stand_in):
    """Inventory only (earlier versions asserted nothing)."""
    code, payload = run_check(_model(stand_in), RULE)
    assert code == 0
def test_f_measure_coverage_analytics_zero_f_measures(stand_in):
    """BUGFIX: the earlier check divided by the f-measure count and errored on a
    model with none; the tool reports nothing and exits 0."""
    code, payload = run_check(_model(stand_in, "spinout_02_db", "insights.SemanticModel"), RULE)
    assert code == 0
    assert violations(payload) == []
