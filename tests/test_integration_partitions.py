"""Integration pattern: partitions.

* D-field-parameter-partition-shape (test_field_parameter_partition_pattern):
  axis tables are import-mode with a ``("label", NAMEOF(...), ...)`` tuple
  source. Advisory: never fails.
* D-calculated-helper-partition-coverage (test_calculated_table_partition_completeness):
  covered by M007 (every table declares a partition).
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"
class TestFieldParameterPartitionShape:
    RULE = "field-parameter-partition-shape"

    def test_field_parameter_partition_pattern(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0
        assert violations(payload) == []

    def test_direct_query_mode_is_reported(self, stand_in, replace_in):
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "x-Selector 1.tmdl",
                   "\t\tmode: import\n", "\t\tmode: directQuery\n")
        code, payload = run_check(model, self.RULE)
        assert code == 0  # advisory
        assert len(violations(payload)) == 1

    def test_missing_mode_is_unknown(self, stand_in, replace_in):
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "y-Selector 2.tmdl", "\t\tmode: import\n", "")
        code, payload = run_check(model, self.RULE)
        assert code == 0
        found = violations(payload)
        assert len(found) == 1 and "unknown" in found[0]["message"]

    def test_source_without_nameof_tuple_is_reported(self, stand_in):
        model = _model(stand_in)
        f = model / "definition" / "tables" / "y-Selector 2.tmdl"
        text = f.read_text(encoding="utf-8")
        start = text.index("source = ```")
        f.write_text(text[:start] + 'source = ```\n\t\t\t\t{ ("Cups", 1) }\n\t\t\t\t```\n', encoding="utf-8")
        code, payload = run_check(model, self.RULE)
        assert code == 0
        assert len(violations(payload)) == 1

    def test_disabled_by_policy_is_skipped(self, stand_in, replace_in):
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "x-Selector 1.tmdl",
                   "\t\tmode: import\n", "\t\tmode: directQuery\n")
        code, payload = run_check(model, self.RULE, config={"rules": {self.RULE: {
            "validate_field_parameter_pattern": False}}})
        assert code == 0 and violations(payload) == []
        assert self.RULE in payload.get("skipped", [])
class TestCalculatedHelperPartitionCoverage:
    def test_calculated_table_partition_completeness(self, stand_in):
        code, payload = run_check(_model(stand_in), "M007")
        assert code == 0, payload
        assert violations(payload, "M007") == []

    def test_axis_table_without_partition_fails_m007(self, stand_in):
        """STRICTER: an existing file alone does not count as 'with partition'."""
        model = _model(stand_in)
        f = model / "definition" / "tables" / "y-Selector 2.tmdl"
        text = f.read_text(encoding="utf-8")
        f.write_text(text[:text.index("\tpartition ")], encoding="utf-8")
        code, payload = run_check(model, "M007")
        assert code == 1
        assert len(violations(payload, "M007")) == 1

    def test_table_declared_in_differently_named_file_is_judged_by_content(self, stand_in):
        model = _model(stand_in)
        tables = model / "definition" / "tables"
        (tables / "x-Selector 1.tmdl").rename(tables / "Picker.tmdl")
        code, payload = run_check(model, "M007")
        assert violations(payload, "M007") == []
