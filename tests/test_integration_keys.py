"""Integration pattern: keys.

* C-dimension-key-columns (test_dimension_tables_have_primary_keys): each
  ``_`` dimension has a key-pattern column (info, advisory).
* B-relationship-endpoints / R001 (test_relationship_key_columns_valid): the
  earlier versions printed the invalid relationships and never failed; the tool
  reports each as an R001 ERROR (stricter wins). 
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"
class TestDimensionKeyColumns:
    RULE = "dimension-key-columns"

    def test_dimension_tables_have_primary_keys(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE)
        assert code == 0
        assert violations(payload) == []

    def test_dimension_without_key_is_one_info_finding(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 0  # advisory despite the earlier check P1 label
        found = violations(payload)
        assert len(found) == 1
        assert found[0]["severity"] == "info"
        assert "_Cluster Notes" in found[0]["message"] and "label" in found[0]["message"]

    def test_disabled_by_policy_is_skipped(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE,
                                  config={"rules": {self.RULE: {"require_dimension_keys": False}}})
        assert code == 0 and violations(payload) == []
        assert self.RULE in payload.get("skipped", [])
class TestRelationshipKeyColumnsValid:
    def test_relationship_key_columns_valid(self, stand_in):
        code, payload = run_check(_model(stand_in), "R001")
        assert code == 0, payload
        assert violations(payload, "R001") == []

    def test_missing_to_column_is_listed(self, stand_in):
        model = _model(stand_in)
        rel = model / "definition" / "relationships.tmdl"
        rel.write_text(rel.read_text(encoding="utf-8")
                       + "relationship 00000000-0000-4000-8000-00000000abcd\n"
                         "\tfromColumn: Orders.order_id\n\ttoColumn: _Shops.order_id\n\n",
                       encoding="utf-8")
        code, payload = run_check(model, "R001")
        assert code == 1  # STRICTER: earlier check only printed it
        found = violations(payload, "R001")
        assert len(found) == 1
        assert "order_id" in found[0]["message"]

    def test_table_name_with_embedded_apostrophe_is_valid(self, stand_in):
        model = _model(stand_in)
        tables = model / "definition" / "tables"
        (tables / "Cohort 'Since' Interval.tmdl").write_text(
            "table 'Cohort ''Since'' Interval'\n"
            "\tlineageTag: 3c1d2e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f\n\n"
            "\tcolumn interval_id\n\t\tdataType: int64\n"
            "\t\tlineageTag: 4d2e3f5a-6b7c-4d8e-9fa0-1b2c3d4e5f6a\n"
            "\t\tsummarizeBy: none\n\t\tsourceColumn: interval_id\n\n"
            "\tpartition 'Cohort ''Since'' Interval' = calculated\n\t\tmode: import\n"
            "\t\tsource = GENERATESERIES(1, 3)\n", encoding="utf-8")
        rel = model / "definition" / "relationships.tmdl"
        rel.write_text(rel.read_text(encoding="utf-8")
                       + "relationship 00000000-0000-4000-8000-00000000abce\n"
                         "\tfromColumn: Orders.order_id\n"
                         "\ttoColumn: 'Cohort ''Since'' Interval'.interval_id\n\n",
                       encoding="utf-8")
        code, payload = run_check(model, "R001")
        assert violations(payload, "R001") == []
