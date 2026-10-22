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


X_REPORT = (
    "Found 1 x-Selector entries without category (4th parameter)\n"
    "All x-Selector field parameters must have 4th parameter (category_x_id)\n"
    "\n"
    '  - x-Selector 1: "Pace"\n'
    "\n"
    "Valid categories: Performance_x, analytics_api_x, kplanner_x, etc.\n"
    'Example: ("Cost", NAMEOF([!Cost]), -10, "Performance_x")'
)

Y_REPORT = (
    "y-Selector Field Parameter Validation:\n"
    "Tables analyzed: 2\n"
    "Found 1 y-Selector entries without category (4th parameter)\n"
    "\n"
    '  - y-Selector 1: "Region"\n'
    "\n"
    "Valid categories: Campaign_y, Ad_Group_y, Keyword_y, Landing_Page_y, etc.\n"
    'Example: ("Campaign Name", NAMEOF(\'_Campaigns\'[Campaign Actual]), -10, '
    '"campaign_universal_y", "Other")'
)


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

    def test_runs_without_being_selected(self, stand_in):
        """The rule is part of the default suite: a plain check reports it."""
        code, payload = run_check(_model(stand_in, "failing_db"))
        assert code == 1
        assert len(violations(payload, "F011")) == 2

    def test_x_family_report(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), RULE)
        found = [v for v in violations(payload) if "x-Selector" in v["message"]]
        assert len(found) == 1
        assert found[0]["message"] == X_REPORT

    def test_y_family_report(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), RULE)
        found = [v for v in violations(payload) if "y-Selector" in v["message"]]
        assert len(found) == 1
        assert found[0]["message"] == Y_REPORT

    def test_a_parked_row_is_not_a_finding(self, tmp_path):
        """A row behind a comment marker is parked, not live: it is not judged."""
        tables = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
        tables.mkdir(parents=True)
        (tables / "y-Selector 1.tmdl").write_text(
            "table 'y-Selector 1'\n"
            "\tcolumn 'y-Selector 1'\n"
            "\t\tsourceColumn: [Value1]\n"
            "\n"
            "\tpartition 'p' = calculated\n"
            "\t\tmode: import\n"
            "\t\tsource = ```\n"
            "\t\t\t\t{\n"
            "\t\t\t\t\t-- (\"Old\", NAMEOF('_Stores'[Old]), 2),\n"
            "\t\t\t\t\t(\"New\", NAMEOF('_Stores'[New]), 3, \"g_y\")\n"
            "\t\t\t\t}\n"
            "\t\t\t\t```\n", encoding="utf-8")
        code, payload = run_check(tmp_path / "Shop.SemanticModel", RULE)
        assert code == 0, payload
        assert violations(payload, "F011") == []

    def test_a_row_whose_last_value_is_no_order_is_not_a_finding(self, tmp_path):
        """The rule judges the three-value shape: label, NAMEOF, order."""
        tables = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
        tables.mkdir(parents=True)
        (tables / "y-Selector 1.tmdl").write_text(
            "table 'y-Selector 1'\n"
            "\tcolumn 'y-Selector 1'\n"
            "\t\tsourceColumn: [Value1]\n"
            "\n"
            "\tpartition 'p' = calculated\n"
            "\t\tmode: import\n"
            "\t\tsource = ```\n"
            "\t\t\t\t{\n"
            "\t\t\t\t\t(\"Odd\", NAMEOF('_Stores'[Odd]), \"later\")\n"
            "\t\t\t\t}\n"
            "\t\t\t\t```\n", encoding="utf-8")
        code, payload = run_check(tmp_path / "Shop.SemanticModel", RULE)
        assert code == 0, payload
        assert violations(payload, "F011") == []


class TestFieldParameterCoverage:
    RULE = "fieldparam-coverage"
    STANDIN = "fieldparam_coverage"

    def _coverage_model(self, stand_in):
        return stand_in(self.STANDIN) / "Coverage.SemanticModel"

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

    def test_the_summary_counts_the_audit(self, stand_in):
        code, payload = run_check(self._coverage_model(stand_in), self.RULE)
        assert code == 0, payload
        summary = violations(payload)[0]["message"]
        assert summary == (
            "x-Selector — measure level:\n"
            "  x-Selector measure count:                  1\n"
            "  User-facing measures (total):          6\n"
            "  Covered in x-Selector:                     1 (16.7%)\n"
            "  Uncovered (not in any x-Selector):         5\n"
            "\n"
            "y-Selector — dim-table level:\n"
            "  y-Selector dim tables referenced:          1\n"
            "  `_` dim tables in model (total):       2\n"
            "  Dim tables in model not in y-Selector:     1\n"
            "  y-Selector refs to missing tables:         0")

    def test_the_lists_name_what_they_found(self, stand_in):
        code, payload = run_check(self._coverage_model(stand_in), self.RULE)
        found = [v["message"] for v in violations(payload)]
        assert found[1] == (
            "User-facing measures not in x-Selector (5):\n"
            "  - #Report Measures[Cups]\n"
            "  - #Report Measures[Margin]\n"
            "  - #Report Measures[Orders]\n"
            "  - #Report Measures[Refunds]\n"
            "  - #Report Measures[Revenue]")
        assert found[2] == (
            "`_` dim tables in model not exposed on y-Selector:\n"
            "  - _Hidden")

    def test_a_quoted_table_name_counts_as_covered(self, stand_in, replace_in):
        """A row that names its measure with a quoted table is on the axis."""
        model = self._coverage_model(stand_in)
        replace_in(model / "definition" / "tables" / "x-Selector 1.tmdl",
                   "NAMEOF('#Report Measures'[Cost])", "NAMEOF('Other'[Cost])")
        code, payload = run_check(model, self.RULE)
        assert code == 0, payload
        summary = violations(payload)[0]["message"]
        assert "Covered in x-Selector:                     1 (16.7%)" in summary

    def test_a_measure_on_an_axis_table_is_listed_with_its_table(self, tmp_path):
        """A measure that sits on an axis table is named with that table."""
        tables = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
        tables.mkdir(parents=True)
        (tables / "x-Selector 2.tmdl").write_text(
            "table 'x-Selector 2'\n"
            "\tmeasure Stray = 1\n"
            "\t\tlineageTag: 7c6cd67a-9d37-5730-872a-78a386ad12c6\n"
            "\n"
            "\tcolumn 'x-Selector 2'\n"
            "\t\tsourceColumn: [Value1]\n"
            "\n"
            "\tpartition 'p' = calculated\n"
            "\t\tmode: import\n"
            "\t\tsource = ```\n"
            "\t\t\t\t{\n"
            "\t\t\t\t\t(\"Cups\", NAMEOF([Cups]), 1, \"g_x\")\n"
            "\t\t\t\t}\n"
            "\t\t\t\t```\n", encoding="utf-8")
        code, payload = run_check(tmp_path / "Shop.SemanticModel", self.RULE)
        assert code == 0, payload
        lists = [v["message"] for v in violations(payload)]
        assert any("  - x-Selector 2[Stray]" in m for m in lists), lists

    def test_the_summary_is_printed_even_when_nothing_is_found(self, tmp_path):
        tables = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
        tables.mkdir(parents=True)
        (tables / "Shop.tmdl").write_text(
            "table Shop\n"
            "\tcolumn shop_name\n"
            "\t\tdataType: string\n"
            "\n"
            "\tpartition Shop = m\n"
            "\t\tmode: import\n"
            "\t\tsource =\n"
            "\t\t\t\tlet\n"
            "\t\t\t\t    Source = Sql.Database(\"example-server\", \"roastery\")\n"
            "\t\t\t\tin\n"
            "\t\t\t\t    Source\n", encoding="utf-8")
        code, payload = run_check(tmp_path / "Shop.SemanticModel", self.RULE)
        assert code == 0, payload
        found = violations(payload)
        assert len(found) == 1
        assert found[0]["message"].startswith("x-Selector — measure level:")
        assert "  x-Selector measure count:                  0" in found[0]["message"]
        assert "  y-Selector refs to missing tables:         0" in found[0]["message"]
