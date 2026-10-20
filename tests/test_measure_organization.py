"""Measure organization (placement axis).

Placement of measures by NAME class (user-facing vs helper, and the helper
subcategory). The earlier check tests ran on every registered model; here they run
on the stand-in fleet ``tests/fixtures/measure_organization_fleet``:

* ``universal`` - every measure correctly placed (earlier verdict: pass);
* ``spinout_02_db``  - one helper in the ``#`` table, one measure helper in a
  domain measures table, one user-facing measure in a dimension table
  (earlier verdict: fail).

Rules (new, selected by name): user-only-table-purity,
helper-measure-placement, user-facing-in-helper-tables; the summary is the
``stats --measures`` report (B-measure-organization-summary).
The placement rules are WARNINGs; the earlier check tests failed on them, so the
verdict is taken with ``--strict``.
"""

from __future__ import annotations

import json

import pytest

from conftest import run_check, run_cli, violations

FLEET = "measure_organization_fleet"
MODELS = {
    "universal": "universal/Performance.SemanticModel",
    "spinout-02": "spinout_02_db/Performance.SemanticModel",
}

# The earlier check hard-coded the two axis field-parameter prefixes; the tool
# takes them from configuration (both axis families are exempt).
FIELD_PARAMETER_PREFIXES = ["x-Selector", "y-Selector", "x-Plot Specific", "y-Plot Specific"]


def _model(stand_in, client):
    return stand_in(FLEET) / MODELS[client]


def _placement_config():
    return {"rules": {
        "helper-measure-placement": {"field_parameter_prefixes": FIELD_PARAMETER_PREFIXES},
    }}


class TestHashPrefixedTablesPurity:
    """test_hash_prefixed_tables_purity: no helper-named measure in a `#` table."""

    def test_clean_model_passes(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "user-only-table-purity", strict=True)
        assert code == 0
        assert violations(payload) == []

    def test_helper_in_hash_table_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "user-only-table-purity", strict=True)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "#Report Measures" in found[0]["message"]
        assert "-helper Roast Window" in found[0]["message"]
        assert "measure_helper" in found[0]["message"]

    def test_model_without_hash_table_reports_nothing(self, stand_in):
        # earlier check: pytest.skip("No '#'-prefixed tables in this model")
        model = _model(stand_in, "spinout-02")
        (model / "definition" / "tables" / "#Report Measures.tmdl").unlink()
        code, payload = run_check(model, "user-only-table-purity", strict=True)
        assert code == 0
        assert violations(payload) == []


class TestHelperMeasuresInHelperTable:
    """test_helper_measures_in_helper_table: each helper sits in a table valid
    for its subcategory."""

    def test_clean_model_passes(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "helper-measure-placement",
                                  config=_placement_config(), strict=True)
        assert code == 0
        assert violations(payload) == []

    def test_misplaced_helpers_fail(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "helper-measure-placement",
                                  config=_placement_config(), strict=True)
        assert code == 1
        found = violations(payload)
        # "Found 2 helper measure(s) in wrong table(s)"
        assert len(found) == 2
        objs = " ".join(v["message"] for v in found)
        assert "#Report Measures[-helper Roast Window]" in objs
        assert "Ads Measures[-helper Basket]" in objs
        assert all("measure_helper" in v["message"] for v in found)


class TestNoUserFacingInForbiddenTables:
    """test_no_user_facing_in_forbidden_tables: no user-facing-named measure in
    `_*`, `f-*`, `w-*`, `i-*` tables."""

    def test_clean_model_passes(self, stand_in):
        code, payload = run_check(_model(stand_in, "universal"), "user-facing-in-helper-tables", strict=True)
        assert code == 0
        assert violations(payload) == []

    def test_user_facing_in_dimension_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout-02"), "user-facing-in-helper-tables", strict=True)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "_Ads[Store Count]" in found[0]["message"]


class TestOrganizationRulesSummary:
    """test_organization_rules_summary: informational; always passes. The
    numbers below are the ones the earlier check printed for the stand-ins."""

    @staticmethod
    def _summary(model):
        code, out, _err = run_cli("stats", model, "--measures", "--json")
        assert code == 0
        return json.loads(out)["measures"]

    def test_clean_model_summary(self, stand_in):
        s = self._summary(_model(stand_in, "universal"))
        assert s["total"] == 17
        assert s["user_facing"] == 9
        assert s["helpers"] == 8
        assert s["surfaced"] == 2
        assert s["surfaced_user_facing"] == 2
        assert s["not_surfaced"] == 7
        assert s["advisory"] is True  # 2 < 9 * 0.5
        assert s["subcategories"] == {
            "measure_helper": 3, "visual_helper": 2, "diagnostic_helper": 1,
            "slicer_helper": 1, "intermediary_helper": 1,
        }
        assert s["top_tables"][0] == ["Helper Measures", 5]

    def test_broken_model_summary_still_exits_zero(self, stand_in):
        s = self._summary(_model(stand_in, "spinout-02"))
        assert s["total"] == 20
        assert s["user_facing"] == 10
        assert s["helpers"] == 10
        assert s["surfaced"] == 3
        assert s["surfaced_user_facing"] == 3
        assert s["not_surfaced"] == 7
        assert s["subcategories"]["measure_helper"] == 5

    def test_model_without_measures(self, tmp_path):
        model = tmp_path / "Empty.SemanticModel" / "definition"
        (model / "tables").mkdir(parents=True)
        (model / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
        (model / "tables" / "Stores.tmdl").write_text(
            "table Stores\n\tlineageTag: 6a0f2f4e-1111-4c3b-9d1e-000000000001\n\n"
            "\tcolumn name\n\t\tdataType: string\n"
            "\t\tlineageTag: 6a0f2f4e-1111-4c3b-9d1e-000000000002\n\t\tsourceColumn: name\n",
            encoding="utf-8")
        code, out, _ = run_cli("stats", model.parent, "--measures")
        assert code == 0
        assert "No measures in model." in out
