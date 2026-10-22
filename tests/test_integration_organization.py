"""Integration pattern: measure organization.

* B-helper-measure-placement, lenient profile (test_user_facing_measures_location)
* D-user-facing-measure-visible (test_user_facing_measures_visible)
* D-user-facing-display-folder (test_measure_display_folder_organization, info)
* D-user-facing-measure-description (test_user_facing_measure_descriptions, info)
* D-table-description-coverage (test_table_annotation_coverage, info)
* D-fact-table-filter-coverage (test_integration_component_completeness)

Writing the missing filter measure is the pbip-model-forge gap-fill
command's job (F-f-filter-gap-fill); this file tests the check.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"
LENIENT = {"rules": {"helper-measure-placement": {
    "profile": "lenient",
    "field_parameter_prefixes": ["x-Selector", "y-Selector", "x-Plot Specific", "y-Plot Specific"],
}}}


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"


def _add_measure(model, table, text):
    f = model / "definition" / "tables" / f"{table}.tmdl"
    f.write_text(f.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + text, encoding="utf-8")
class TestUserFacingMeasuresLocation:
    RULE = "helper-measure-placement"

    def test_user_facing_measures_location(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, config=LENIENT)
        assert code == 0
        assert violations(payload) == []

    def test_slicer_helper_on_a_measures_table_is_one_info_finding(self, stand_in):
        model = _model(stand_in)
        _add_measure(model, "Coffee Measures",
                     "\tmeasure 'f-Espresso' = 1\n\t\tisHidden\n"
                     "\t\tlineageTag: 5e3f4a6b-7c8d-4e9f-a0b1-2c3d4e5f6a7b\n")
        code, payload = run_check(model, self.RULE, config=LENIENT, strict=True)
        assert code == 0  # lenient findings are INFO: never fail
        found = violations(payload)
        assert len(found) == 1 and found[0]["severity"] == "info"
        assert "f-Espresso" in found[0]["message"]
class TestUserFacingMeasuresVisible:
    RULE = "user-facing-measure-visible"

    def test_user_facing_measures_visible(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert violations(payload) == []

    def test_hidden_user_facing_measure_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "Coffee Measures[Avg Ticket]" in found[0]["message"]
class TestMeasureDisplayFolderOrganization:
    RULE = "user-facing-display-folder"

    def test_measure_display_folder_organization(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0
        assert violations(payload) == []

    def test_user_facing_measure_without_folder_is_listed(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 0  # advisory
        text = "\n".join(v["message"] for v in violations(payload))
        assert "Avg Ticket" in text
        assert "-Base Cups" not in text  # helpers are ignored
class TestUserFacingMeasureDescriptions:
    RULE = "user-facing-measure-description"

    def test_user_facing_measure_descriptions(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0
        assert violations(payload) == []

    def test_hidden_user_facing_measure_without_description_is_listed(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 0
        text = "\n".join(v["message"] for v in violations(payload))
        assert "Avg Ticket" in text
        assert "-Base Cups" not in text

    def test_description_shorter_than_min_length_counts_as_missing(self, stand_in, replace_in):
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "Coffee Measures.tmdl",
                   "/// Revenue net of refunds", "/// Revenue")
        code, payload = run_check(model, self.RULE)
        assert code == 0
        assert any("Total Revenue" in v["message"] for v in violations(payload))

    def test_disabled_by_policy_is_skipped(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE,
                                  config={"rules": {self.RULE: {"enabled": False}}})
        assert code == 0 and violations(payload) == []
        assert self.RULE in payload.get("skipped", [])
class TestTableAnnotationCoverage:
    RULE = "table-description-coverage"

    def test_table_annotation_coverage(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0
        found = violations(payload)
        assert found and all(v["severity"] == "info" for v in found)
        summary = "\n".join(v["message"] for v in found)
        assert "3" in summary and "15" in summary  # 3 of 15 tables described
class TestIntegrationComponentCompleteness:
    RULE = "fact-table-filter-coverage"

    def test_integration_component_completeness(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert violations(payload) == []

    def test_consumed_fact_without_filter_measure_fails_without_writing(self, stand_in):
        model = _model(stand_in, "failing_db")
        before = {p: p.read_bytes() for p in (model / "definition").rglob("*.tmdl")}
        code, payload = run_check(model, self.RULE)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "Refunds" in found[0]["message"]
        assert {p: p.read_bytes() for p in (model / "definition").rglob("*.tmdl")} == before

    def test_filter_measure_covers_fact_through_the_measure_graph(self, stand_in):
        model = _model(stand_in, "failing_db")
        _add_measure(model, "f-Filters",
                     "\tmeasure 'f-Refund Probe' = IF(ISEMPTY(Refunds), 0, 1) + [Refund Total] * 0\n"
                     "\t\tisHidden\n\t\tlineageTag: 6f4a5b7c-8d9e-4fa0-b1c2-3d4e5f6a7b8c\n")
        code, payload = run_check(model, self.RULE)
        assert code == 0  # covered transitively through [Refund Total]
