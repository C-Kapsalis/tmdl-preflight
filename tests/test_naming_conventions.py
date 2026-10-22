"""Naming-convention checks.

Run on the stand-in fleet ``tests/fixtures/measure_organization_fleet``:
``universal`` (clean; every earlier test passed) and ``spinout_02_db``
(earlier check: the three blocking tests fail, the advisory tests pass and list
offenders).

Rules (new, selected by name): required-model-objects,
fieldparam-category-column, measures-in-fact-tables, empty-measure-tables,
measures-in-dimension-tables, format-inference-naming; the helper
description count is part of ``stats --measures``
(B-measure-organization-summary).
"""

from __future__ import annotations

import json

from conftest import run_check, run_cli, violations

FLEET = "measure_organization_fleet"
MODELS = {
    "universal": "universal/Performance.SemanticModel",
    "spinout-02": "spinout_02_db/Performance.SemanticModel",
}


def _model(stand_in, client):
    return stand_in(FLEET) / MODELS[client]


def _non_info(payload):
    return [v for v in violations(payload) if v["severity"] != "info"]


# The earlier check hard-coded these objects; the tool takes them from configuration.
REQUIRED = {"rules": {"required-model-objects": {
    "tables": ["z-Selector Format", "z-Selector Time Intelligence Function"],
    "measures": [{"table_prefix": "z-Selector", "contains": ["Currency", "Selector"], "advisory": True}],
}}}

CATEGORY = {"rules": {"fieldparam-category-column": {
    # earlier check: XREPORT_TABLE_RANGE = range(1, 10) over "x-Selector <i>"
    "category_column_tables": [f"x-Selector {i}" for i in range(1, 10)],
    "category_position": 4,
}}}

FACT_MEASURES = {"rules": {"measures-in-fact-tables": {
    "surfacing_tables": [f"x-Selector {i}" for i in range(1, 10)],
    "internal_name_tokens": ["ga4traf", "ga4users", "ga4convs", "related"],
}}}


class TestFormatInfrastructureExists:
    """test_format_infrastructure_exists (p0)."""

    def test_clean_model_passes(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "required-model-objects", config=REQUIRED)
        assert code == 0
        assert violations(payload) == []  # currency selector present: no advisory either

    def test_missing_format_group_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "required-model-objects", config=REQUIRED)
        assert code == 1
        errors = [v for v in violations(payload) if v["severity"] == "error"]
        assert len(errors) == 1
        assert "z-Selector Format" in errors[0]["message"]
        # the currency selector is advisory only: reported, never an error
        advisory = [v for v in violations(payload) if v["severity"] != "error"]
        assert len(advisory) == 1
        assert "Currency" in advisory[0]["message"]

    def test_both_groups_missing_names_both(self, stand_in):
        model = _model(stand_in, "spinout-02")
        (model / "definition" / "tables" / "z-Selector Time Intelligence Function.tmdl").unlink()
        code, payload = run_check(model, "required-model-objects", config=REQUIRED)
        assert code == 1
        msgs = " ".join(v["message"] for v in violations(payload) if v["severity"] == "error")
        assert "z-Selector Format" in msgs
        assert "z-Selector Time Intelligence Function" in msgs


class TestXSelectorMeasuresHaveAnalysisCategory:
    """test_x_selector_measures_have_analysis_category (p0): every 3-field axis
    row needs a 4-field (category) twin."""

    def test_clean_model_passes(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "fieldparam-category-column", config=CATEGORY)
        assert code == 0
        assert violations(payload) == []

    def test_row_without_category_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "fieldparam-category-column", config=CATEGORY)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "x-Selector 1" in found[0]["message"]
        assert '"Bags"' in found[0]["message"] or "Bags" in found[0]["message"]


class TestNoUserFacingMeasuresInFactTables:
    """test_no_user_facing_measures_in_fact_tables (p1, fails on blocking
    findings; advisory list otherwise)."""

    def test_clean_model_has_only_advisories(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "measures-in-fact-tables",
                                  config=FACT_MEASURES, strict=True)
        assert code == 0
        assert _non_info(payload) == []
        advisories = sorted(v["message"] for v in violations(payload))
        # earlier versions printed: Ads[countrows check] [diagnostic, lowercase]; Ads[Total Revenue] [hidden]
        assert len(advisories) == 2
        assert any("Ads[countrows check]" in m for m in advisories)
        assert any("Ads[Total Revenue]" in m and "hidden" in m for m in advisories)

    def test_visible_user_facing_measure_in_fact_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "measures-in-fact-tables",
                                  config=FACT_MEASURES, strict=True)
        assert code == 1
        blocking = _non_info(payload)
        assert len(blocking) == 1
        assert "Ads[Total Revenue]" in blocking[0]["message"]


class TestMeasureTableNamingConventions:
    """test_measure_table_naming_conventions (advisory, always passes)."""

    def test_clean_model_lists_nothing(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "empty-measure-tables")
        assert code == 0
        assert violations(payload) == []

    def test_empty_measures_table_is_listed(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "empty-measure-tables")
        assert code == 0
        found = violations(payload)
        assert [v["severity"] for v in found] == ["info"]
        assert "Old Measures" in found[0]["message"]


class TestDimensionTableConsistency:
    """test_dimension_table_consistency (advisory, always passes)."""

    def test_clean_model_lists_nothing(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "measures-in-dimension-tables")
        assert code == 0
        assert violations(payload) == []

    def test_dimension_with_measure_is_listed(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "measures-in-dimension-tables")
        assert code == 0
        found = violations(payload)
        assert len(found) == 1 and found[0]["severity"] == "info"
        assert "_Ads" in found[0]["message"] and "Store Count" in found[0]["message"]


class TestHelperMeasuresFollowConventions:
    """test_helper_measures_follow_conventions (advisory): dash helpers with
    and without a description."""

    def test_counts(self, stand_in):
        code, out, _ = run_cli("stats", _model(stand_in, "universal"), "--measures", "--json")
        assert code == 0
        s = json.loads(out)["measures"]
        assert s["dash_helpers"] == 4
        # BUGFIX: earlier versions printed 1 (its index dropped the `///` description
        # of the second consecutive measure); both helper measures carry one.
        assert s["dash_helpers_described"] == 2

    def test_counts_broken_model(self, stand_in):
        code, out, _ = run_cli("stats", _model(stand_in, "spinout-02"), "--measures", "--json")
        assert code == 0
        s = json.loads(out)["measures"]
        assert s["dash_helpers"] == 6
        assert s["dash_helpers_described"] == 2  # BUGFIX: earlier versions printed 1


class TestMeasureNamesEnableFormatInference:
    """test_measure_names_enable_format_inference (advisory, always passes)."""

    def test_clean_model_lists_unclear_names(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "format-inference-naming")
        assert code == 0
        found = violations(payload)
        assert len(found) == 1
        assert "#Report Measures[Bags]" in found[0]["message"]

    def test_broken_model_lists_unclear_names(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "format-inference-naming")
        assert code == 0
        msgs = sorted(v["message"] for v in violations(payload))
        assert len(msgs) == 2
        assert any("#Report Measures[Bags]" in m for m in msgs)
        assert any("Ads Measures[Footfall]" in m for m in msgs)
