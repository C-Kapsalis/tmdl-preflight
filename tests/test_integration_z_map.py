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

    def test_missing_required_column_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1 and "Analysis Subcategory" in found[0]["message"]

    def test_missing_table_fails_not_found(self, stand_in):
        model = _model(stand_in)
        (model / "definition" / "tables" / f"{ZMAP}.tmdl").unlink()
        code, payload = run_check(model, self.RULE)
        assert code == 1
        assert "not found" in violations(payload)[0]["message"]

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

    def test_z_map_relationship_completeness(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0
        assert any("0" in v["message"] and "relationship" in v["message"].lower()
                   for v in violations(payload))
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
