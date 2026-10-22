"""Integration pattern: f-measure shapes (C-f-measure-pattern).

Every ``f-`` measure must be STANDARD (ISEMPTY / ISINSCOPE / ISFILTERED),
AGGREGATOR (two or more ``[f-...]`` joined by + - *), SWITCH-ROUTER
(``SWITCH(TRUE()``), DISPLAY-STRING (hosted in a ``w-`` table, or
CONCATENATEX), or the exempt ``f-Analysis Category``. The earlier check's
"template f-measures present in the client" half is a template comparison
owned by tmdl-drift-doctor (detect ``measure.missing``), not covered here.

The rule also reports the inventory of the filter measures as info
findings: how many there are, how they classify, where they live.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"
RULE = "f-measure-pattern"


def _model(stand_in, client="universal", model="Performance.SemanticModel"):
    return stand_in(STANDIN) / client / model


def _findings(payload, severity=None):
    return [v for v in violations(payload)
            if severity is None or v["severity"] == severity]


def test_f_measure_pattern_validation(stand_in):
    code, payload = run_check(_model(stand_in), RULE, strict=True)
    assert code == 0, payload
    assert _findings(payload, "error") == []
    assert _findings(payload, "warning") == []


def test_f_measure_pattern_unclassified_fails(stand_in):
    code, payload = run_check(_model(stand_in, "failing_db"), RULE, strict=True)
    assert code == 1
    found = _findings(payload, "warning")
    assert len(found) == 1
    assert "f-Filters[f-Odd]" in found[0]["message"]


def test_f_measure_exemption_list_is_configurable(stand_in):
    code, payload = run_check(_model(stand_in, "failing_db"), RULE, strict=True,
                              config={"rules": {RULE: {"exempt": ["f-Analysis Category", "f-Odd"]}}})
    assert code == 0
    assert _findings(payload, "warning") == []


def test_f_measure_coverage_analytics(stand_in):
    """The inventory: how many filter measures there are, and how they classify."""
    code, payload = run_check(_model(stand_in), RULE)
    assert code == 0
    text = "\n".join(v["message"] for v in _findings(payload, "info"))
    assert "F-Measure Pattern Classification: Total f-measures: 5" in text
    assert ("STANDARD      :    2  0/1 filter flag — ISEMPTY/ISINSCOPE/ISFILTERED "
            "check on a fact table") in text
    assert ("AGGREGATOR    :    1  rolls up two or more f-measures via + or * into a "
            "parent integration filter") in text
    assert ("SWITCH-ROUTER :    1  SWITCH(TRUE(), ...) dispatching across "
            "integrations by analysis category") in text
    assert ("DISPLAY-STRING:    1  returns a label string for visual titles/headers "
            "(lives in w-* tables)") in text
    assert ("EXEMPTED      :    0  named carve-out; legitimate exception to the "
            "f-measure pattern rules") in text
    assert ("UNCLASSIFIED  :    0  doesn't fit any bucket — review for bugs, or "
            "extend the taxonomy") in text


def test_f_measure_coverage_analytics_counts_where_the_measures_live(stand_in):
    code, payload = run_check(_model(stand_in), RULE)
    assert code == 0
    text = "\n".join(v["message"] for v in _findings(payload, "info"))
    assert ("F-Measure Coverage Analytics: Total f- measures: 5; In f-Filters table: "
            "4 (80.0%); In other tables: 1; Visible: 2 (40.0%); Hidden: 3") in text
    assert "f-Matrix Title (in w-Titles)" in text
    assert "Recommendation: Move to f-Filters table for consistency" in text


def test_f_measure_coverage_analytics_zero_f_measures(stand_in):
    """A model with no filter measures reports the inventory and no percentages."""
    code, payload = run_check(_model(stand_in, "spinout_02_db", "insights.SemanticModel"), RULE)
    assert code == 0
    text = "\n".join(v["message"] for v in _findings(payload, "info"))
    assert "F-Measure Pattern Classification: Total f-measures: 0" in text
    assert ("F-Measure Coverage Analytics: Total f- measures: 0; In f-Filters table: 0; "
            "In other tables: 0; Visible: 0; Hidden: 0") in text
    assert "%" not in text
