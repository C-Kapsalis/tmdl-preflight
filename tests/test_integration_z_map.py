"""Integration pattern: the encoded mapping table (z-Map Dimension-Measure Groupings).

* D-mapping-table-required-columns (test_z_map_table_structure)
* D-mapping-table-info-reports (test_z_map_category_coverage,
  test_z_map_relationship_completeness): info only
* D-mapping-category-required-keys (test_z_map_account_service_assignments):
  every account-filterable category assigns Account_y and Service_y; repairs
  run only through the explicit ``fix`` verb.
"""
from __future__ import annotations

import base64
import json
import re
import zlib

import pytest

from conftest import run_check, run_fix, violations

STANDIN = "layer3_integration_standin"
ZMAP = "z-Map Dimension-Measure Groupings"


def _model(stand_in, client="universal", model="Performance.SemanticModel"):
    return stand_in(STANDIN) / client / model


def _rows(model):
    text = (model / "definition" / "tables" / f"{ZMAP}.tmdl").read_text(encoding="utf-8")
    blob = re.search(r'Binary\.FromText\("([^"]+)"', text).group(1)
    return json.loads(zlib.decompress(base64.b64decode(blob), -zlib.MAX_WBITS))
class TestMappingTableRequiredColumns:
    RULE = "mapping-table-required-columns"

    def test_z_map_table_structure(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert violations(payload) == []

    def test_missing_required_column_is_a_warning(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE)
        assert code == 0, payload
        found = violations(payload)
        assert len(found) == 1 and "Analysis Subcategory" in found[0]["message"]
        assert found[0]["severity"] == "warning"

    def test_strict_makes_the_missing_column_fail(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 1

    def test_the_missing_column_message_names_the_table_structure(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE)
        assert violations(payload)[0]["message"] == (
            "Z-Map Table Structure: table found: z-Map Dimension-Measure Groupings; "
            "total columns: 2; required columns present: 2/3; present required "
            "columns: ['category_x_id', 'Analysis Category']; missing required "
            "columns: ['Analysis Subcategory']. These columns are critical for "
            "dimension-measure grouping")

    def test_missing_table_fails_not_found(self, stand_in):
        model = _model(stand_in)
        (model / "definition" / "tables" / f"{ZMAP}.tmdl").unlink()
        code, payload = run_check(model, self.RULE)
        assert code == 0, payload
        assert violations(payload)[0]["message"] == (
            "P1 WARNING: z-Map Dimension-Measure Groupings table not found")

    def test_disabled_by_policy_is_skipped(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE,
                                  config={"rules": {self.RULE: {"enabled": False}}})
        assert code == 0 and violations(payload) == []
        assert self.RULE in payload.get("skipped", [])
class TestMappingTableInfoReports:
    RULE = "mapping-table-info-reports"

    def test_z_map_category_coverage(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0
        text = "\n".join(v["message"] for v in violations(payload))
        assert all(v["severity"] == "info" for v in violations(payload))
        assert "Sales_x" in text and "Traffic_x" in text

    def test_the_group_inventory_names_the_axis_groups(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        text = "\n".join(v["message"] for v in violations(payload))
        assert "Unique x-Selector categories found: 2" in text
        assert "  - Sales_x" in text
        assert "  - Traffic_x" in text
        assert "z-Map table provides category mapping infrastructure" in text

    def test_z_map_relationship_completeness(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0
        assert any("0" in v["message"] and "relationship" in v["message"].lower()
                   for v in violations(payload))

    def test_the_relationship_count_runs_without_the_mapping_table(self, stand_in):
        model = _model(stand_in)
        (model / "definition" / "tables" / f"{ZMAP}.tmdl").unlink()
        code, payload = run_check(model, self.RULE)
        text = "\n".join(v["message"] for v in violations(payload))
        assert "Relationships involving z-Map: 0" in text
        assert ("No relationships found involving z-Map. Note: z-Map may use "
                "calculated relationships or direct filtering") in text

class TestMappingCategoryRequiredKeys:
    RULE = "mapping-category-required-keys"

    def test_z_map_account_service_assignments(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0, payload
        assert [v for v in violations(payload) if v["severity"] == "error"] == []
        # Traffic's only backing fact (Visits) has no account_x_id: warning only
        warns = [v for v in violations(payload) if v["severity"] == "warning"]
        assert any("Traffic" in v["message"] for v in warns)

    def test_insights_model_assignments(self, stand_in):
        code, payload = run_check(_model(stand_in, "spinout_02_db", "insights.SemanticModel"), self.RULE)
        assert code == 0, payload

    def test_missing_service_key_fails_without_writing(self, stand_in):
        model = _model(stand_in, "failing_db")
        before = (model / "definition" / "tables" / f"{ZMAP}.tmdl").read_bytes()
        code, payload = run_check(model, self.RULE)
        assert code == 1
        errors = [v for v in violations(payload) if v["severity"] == "error"]
        assert len(errors) == 1
        assert "Sales" in errors[0]["message"] and "Service_y" in errors[0]["message"]
        assert (model / "definition" / "tables" / f"{ZMAP}.tmdl").read_bytes() == before

    def test_the_violation_names_the_category_and_the_missing_keys(self, stand_in):
        model = _model(stand_in, "failing_db")
        code, payload = run_check(model, self.RULE)
        errors = [v for v in violations(payload) if v["severity"] == "error"]
        assert errors[0]["message"] == (
            "[Sales] missing ['Service_y'] Each must assign both Account_y and Service_y.")

    def test_the_warning_names_the_backing_facts(self, stand_in):
        model = _model(stand_in, "failing_db")
        code, payload = run_check(model, self.RULE)
        warns = [v for v in violations(payload) if v["severity"] == "warning"]
        assert warns[0]["message"] == (
            "[Traffic] account-UNSUPPORTED — backing fact table(s) lack "
            "'account_x_id': ['Visits']. Not adding account dims; backfill "
            "'account_x_id' to enable account filtering.")

    def test_a_warning_is_never_tagged_auto_fixable(self, stand_in):
        model = _model(stand_in, "failing_db")
        code, payload = run_check(model, self.RULE)
        warns = [v for v in violations(payload) if v["severity"] == "warning"]
        assert warns and not any(v["fixable"] for v in warns)

    def test_the_key_column_is_matched_by_its_exact_name(self, stand_in):
        """A fact that spells the key differently does not carry it."""
        model = _model(stand_in, "failing_db")
        orders = model / "definition" / "tables" / "Orders.tmdl"
        orders.write_text(orders.read_text(encoding="utf-8").replace(
            "account_x_id", "Account_X_ID"), encoding="utf-8")
        code, payload = run_check(model, self.RULE)
        assert code == 0, payload
        warns = [v for v in violations(payload) if v["severity"] == "warning"]
        assert any("account-UNSUPPORTED" in v["message"] and "['Orders']" in v["message"]
                   for v in warns), warns
        assert not [v for v in violations(payload) if v["severity"] == "error"]

    def test_fix_appends_rows_then_recheck_is_clean_and_idempotent(self, stand_in):
        model = _model(stand_in, "failing_db")
        old = _rows(model)
        code, payload = run_fix(model, self.RULE)
        assert code == 0, payload
        new = _rows(model)
        assert new[:len(old)] == old
        assert new[len(old):] == [["Sales", "", "Service_y"]]
        first = (model / "definition" / "tables" / f"{ZMAP}.tmdl").read_bytes()
        run_fix(model, self.RULE)
        assert (model / "definition" / "tables" / f"{ZMAP}.tmdl").read_bytes() == first
        code, payload = run_check(model, self.RULE)
        assert code == 0

    def test_the_fix_reports_one_line_per_appended_row(self, stand_in):
        model = _model(stand_in, "failing_db")
        code, payload = run_fix(model, self.RULE)
        assert payload["fixes"] == ["A003:    wrote [Sales] += Service_y"], payload["fixes"]


class TestMappingPayloadErrors:
    """A mapping table whose payload cannot be read is an error, not a pass."""

    RULE = "mapping-category-required-keys"

    def _zmap(self, model):
        return model / "definition" / "tables" / f"{ZMAP}.tmdl"

    def test_a_table_without_a_payload_is_an_error(self, stand_in):
        model = _model(stand_in, "failing_db")
        text = self._zmap(model).read_text(encoding="utf-8")
        self._zmap(model).write_text(
            re.sub(r'Binary\.FromText\("[^"]*"', "Binary.FromText", text),
            encoding="utf-8")
        code, payload = run_check(model, self.RULE)
        assert code == 1
        errors = [v for v in violations(payload) if v["severity"] == "error"]
        assert len(errors) == 1
        assert errors[0]["message"].startswith("No binary data found in ")
        assert ZMAP in errors[0]["message"]

    def test_a_payload_that_does_not_decode_is_an_error(self, stand_in):
        model = _model(stand_in, "failing_db")
        text = self._zmap(model).read_text(encoding="utf-8")
        self._zmap(model).write_text(
            re.sub(r'Binary\.FromText\("[^"]*"', 'Binary.FromText("QUJDRA==")', text),
            encoding="utf-8")
        code, payload = run_check(model, self.RULE)
        assert code == 1
        errors = [v for v in violations(payload) if v["severity"] == "error"]
        assert len(errors) == 1
        assert errors[0]["message"].startswith("mapping payload does not decode: ")

    def test_the_fixer_writes_nothing_when_the_payload_cannot_be_read(self, stand_in):
        model = _model(stand_in, "failing_db")
        text = self._zmap(model).read_text(encoding="utf-8")
        self._zmap(model).write_text(
            re.sub(r'Binary\.FromText\("[^"]*"', 'Binary.FromText("QUJDRA==")', text),
            encoding="utf-8")
        before = self._zmap(model).read_bytes()
        code, payload = run_fix(model, self.RULE)
        assert self._zmap(model).read_bytes() == before
        assert payload["fixes"] == []

