"""Rules D001-D003: delimiter balance, NAMEOF resolution, duplicate measures."""

from __future__ import annotations

from tmdl_preflight.rules.base import Context, Severity
from tmdl_preflight.rules.dax_rules import (
    DaxDelimiterBalanceRule,
    DuplicateMeasureNamesRule,
    NameofResolutionRule,
)


class TestDaxDelimiters:
    def test_clean_passes(self, project):
        assert DaxDelimiterBalanceRule().check(Context(project)) == []

    def test_unbalanced_measure_detected(self, project, definition):
        f = definition / "tables" / "Sales Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "measure Revenue = SUM(Sales[net_amount])",
                "measure Revenue = SUM(Sales[net_amount]",
            ),
            encoding="utf-8",
        )
        violations = DaxDelimiterBalanceRule().check(Context(project))
        assert any(
            "parenthesis" in v.message and "Revenue" in (v.obj or "") for v in violations
        )

    def test_unbalanced_partition_source_detected(self, project, definition):
        f = definition / "tables" / "Calendar.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "source = CALENDAR(DATE(2024, 1, 1), DATE(2026, 12, 31))",
                "source = CALENDAR(DATE(2024, 1, 1), DATE(2026, 12, 31)",
            ),
            encoding="utf-8",
        )
        violations = DaxDelimiterBalanceRule().check(Context(project))
        assert any("partition_source" in v.message for v in violations)


class TestNameofResolution:
    def test_clean_passes(self, project):
        assert NameofResolutionRule().check(Context(project)) == []

    def test_missing_measure_detected(self, project, definition):
        f = definition / "tables" / "Metric Selector.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "NAMEOF ( [Units Sold] )", "NAMEOF ( [Retired Metric] )"
            ),
            encoding="utf-8",
        )
        violations = NameofResolutionRule().check(Context(project))
        assert len(violations) == 1
        assert "Retired Metric" in violations[0].message
        assert violations[0].severity == Severity.ERROR

    def test_missing_table_detected(self, project, definition):
        f = definition / "tables" / "Metric Selector.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "NAMEOF ( [Units Sold] )", "NAMEOF ( 'Ghost Table'[Units] )"
            ),
            encoding="utf-8",
        )
        violations = NameofResolutionRule().check(Context(project))
        assert any("Ghost Table" in v.message for v in violations)

    def test_missing_column_detected(self, project, definition):
        f = definition / "tables" / "Metric Selector.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "NAMEOF ( [Units Sold] )", "NAMEOF ( Sales[gross_amount] )"
            ),
            encoding="utf-8",
        )
        violations = NameofResolutionRule().check(Context(project))
        assert any("no column or measure named" in v.message for v in violations)

    def test_qualified_measure_reference_is_clean(self, project, definition):
        # Power BI Desktop itself writes NAMEOF('Table'[Measure]) when adding
        # measures to a field parameter — a resolving qualified reference to a
        # measure must not be flagged (regression: false-positive storm on
        # production-size models).
        f = definition / "tables" / "Metric Selector.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "NAMEOF ( [Units Sold] )",
                "NAMEOF ( 'Sales Measures'[Units Sold] )",
            ),
            encoding="utf-8",
        )
        assert NameofResolutionRule().check(Context(project)) == []

    def test_ambiguous_measure_is_warning(self, project, definition):
        # declare a second 'Units Sold' measure on Products
        f = definition / "tables" / "Products.tmdl"
        text = f.read_text(encoding="utf-8")
        text = text.replace(
            "\tcolumn product_id",
            "\tmeasure 'Units Sold' = COUNTROWS(Products)\n"
            "\t\tlineageTag: 99999999-9999-4999-8999-999999999999\n\n"
            "\tcolumn product_id",
            1,
        )
        f.write_text(text, encoding="utf-8")
        violations = NameofResolutionRule().check(Context(project))
        assert any(
            "ambiguous" in v.message and v.severity == Severity.WARNING
            for v in violations
        )


class TestDuplicateMeasureNames:
    def test_clean_passes(self, project):
        assert DuplicateMeasureNamesRule().check(Context(project)) == []

    def test_duplicate_across_tables_detected(self, project, definition):
        f = definition / "tables" / "Stores.tmdl"
        text = f.read_text(encoding="utf-8")
        text = text.replace(
            "\tcolumn store_id",
            "\tmeasure Revenue = SUM(Sales[net_amount])\n"
            "\t\tlineageTag: 88888888-8888-4888-8888-888888888888\n\n"
            "\tcolumn store_id",
            1,
        )
        f.write_text(text, encoding="utf-8")
        violations = DuplicateMeasureNamesRule().check(Context(project))
        assert len(violations) == 1
        assert "Revenue" in violations[0].message
        assert violations[0].severity == Severity.ERROR
