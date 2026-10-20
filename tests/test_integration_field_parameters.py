"""Integration pattern: field-parameter categories.

* C-fieldparam-category-required: every row of ``x-Selector N`` /
  ``y-Selector N`` (N = 1-9) carries a 4th value (the category).
* C-fieldparam-coverage: advisory audit of what the axes expose (info only).

Stand-in: ``universal`` rows all have categories; ``failing_db`` adds
``("Pace", NAMEOF([Visit Count]), 2)`` to ``x-Selector 1`` and
``("Region", NAMEOF('_Shops'[shop_name]), 3)`` to ``y-Selector 1``.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"
RULE = "fieldparam-category-required"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"


def _in_table(found, table):
    return [v for v in found if table in (v.get("path") or "") or table in v["message"]]
class TestCategoryRequired:
    def test_x_plot_specific_field_parameters_have_categories(self, stand_in):
        code, payload = run_check(_model(stand_in), RULE)
        assert code == 0, payload
        assert _in_table(violations(payload), "x-Selector") == []

    def test_y_plot_specific_field_parameters_have_categories(self, stand_in):
        code, payload = run_check(_model(stand_in), RULE)
        assert code == 0, payload
        assert _in_table(violations(payload), "y-Selector") == []

    def test_x_row_without_category_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), RULE)
        assert code == 1
        found = _in_table(violations(payload), "x-Selector 1")
        assert len(found) == 1 and "Pace" in found[0]["message"]

    def test_y_row_without_category_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), RULE)
        assert code == 1
        found = _in_table(violations(payload), "y-Selector 1")
        assert len(found) == 1 and "Region" in found[0]["message"]

    def test_disabled_by_policy_is_skipped(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), RULE,
                                  config={"rules": {RULE: {"require_category": False}}})
        assert code == 0 and violations(payload) == []
        assert RULE in payload.get("skipped", [])
class TestFieldParameterCoverage:
    RULE = "fieldparam-coverage"

    def test_field_parameter_coverage(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0  # advisory: never fails, even under --strict
        found = violations(payload)
        assert found and all(v["severity"] == "info" for v in found)
        text = "\n".join(v["message"] for v in found)
        assert "Pick" in text            # user-facing, not on any metric axis
        assert "Total Revenue" not in text
        assert "__Calendar" in text      # dimension not exposed on an axis
        assert "_Shops" not in text

    def test_broken_axis_table_reference_is_reported(self, stand_in, replace_in):
        model = _model(stand_in)
        replace_in(model / "definition" / "tables" / "y-Selector 2.tmdl",
                   "NAMEOF('_Shops'[shop_name])", "NAMEOF('_Kiosks'[shop_name])")
        code, payload = run_check(model, self.RULE)
        assert code == 0
        assert any("_Kiosks" in v["message"] for v in violations(payload))
