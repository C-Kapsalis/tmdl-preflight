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
        assert any("not found in table" in v.message for v in violations)

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
            "Ambiguous: measure 'Units Sold' exists in multiple tables:"
            in v.message and v.severity == Severity.WARNING
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


# ---------------------------------------------------------------------------
# D003 (case-insensitive), D004, D005
# ---------------------------------------------------------------------------

from tmdl_preflight.rules.dax_rules import (  # noqa: E402
    DaxReferenceResolutionRule,
    DuplicateVariableRule,
)


def _measures(definition):
    return definition / "tables" / "Sales Measures.tmdl"


def _add_measure(definition, replace_in, decl):
    replace_in(
        _measures(definition),
        "\tpartition 'Sales Measures' = m",
        f"\t{decl}\n\t\tlineageTag: 0a0a0a0a-0000-4000-8000-000000000001\n\n"
        "\tpartition 'Sales Measures' = m",
    )


def test_duplicate_measure_names_are_case_insensitive(project, definition, replace_in):
    replace_in(
        definition / "tables" / "Sales.tmdl",
        "\tmeasure 'countrows sales' = COUNTROWS(Sales)",
        "\tmeasure REVENUE = 1\n\n\tmeasure 'countrows sales' = COUNTROWS(Sales)",
    )
    violations = DuplicateMeasureNamesRule().check(Context(project))
    assert len(violations) == 1 and "REVENUE" in violations[0].message


class TestDaxReferenceResolution:
    def test_clean_passes(self, project):
        assert DaxReferenceResolutionRule().check(Context(project)) == []

    def test_missing_table_is_error(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "measure Revenue = SUM(Sales[net_amount])",
            "measure Revenue = SUM(Orders[net_amount])",
        )
        violations = DaxReferenceResolutionRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert violations[0].message.startswith(
            "measure Sales Measures[Revenue] -> missing 'Orders'"
        )
        assert violations[0].line == 6

    def test_bare_quoted_table_is_checked(self, project, definition, replace_in):
        _add_measure(definition, replace_in, "measure 'Row Count' = COUNTROWS('Gone Table')")
        violations = DaxReferenceResolutionRule().check(Context(project))
        assert [v.message.split("'")[1] for v in violations] == ["Gone Table"]

    def test_missing_qualified_column_is_error(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "measure 'Units Sold' = SUM(Sales[quantity])",
            "measure 'Units Sold' = SUM('Sales'[qty])",
        )
        violations = DaxReferenceResolutionRule().check(Context(project))
        assert len(violations) == 1 and "'Sales'[qty]" in violations[0].message

    def test_case_mismatch_resolves_but_is_an_error(self, project, definition, replace_in):
        # DAX resolves names case-insensitively, so nothing is "missing"; a
        # spelling that differs from the declaration is still reported, as an
        # error, by project decision (casing mismatches are errors).
        replace_in(
            _measures(definition),
            "measure 'Units Sold' = SUM(Sales[quantity])",
            "measure 'Units Sold' = SUM('SALES'[Quantity]) + [revenue]",
        )
        found = DaxReferenceResolutionRule().check(Context(project))
        assert len(found) == 3
        assert all("casing mismatch" in v.message and v.severity == Severity.ERROR for v in found)
        assert not any("does not exist" in v.message for v in found)

    def test_unresolved_bare_reference_is_warning(self, project, definition, replace_in):
        _add_measure(definition, replace_in, "measure Ratio = DIVIDE([Revenue], [Old Measure])")
        violations = DaxReferenceResolutionRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "[Old Measure]" in violations[0].message

    def test_columns_introduced_by_string_literals_are_suppressed(
        self, project, definition, replace_in
    ):
        _add_measure(
            definition,
            replace_in,
            'measure Peak = MAXX(ADDCOLUMNS(VALUES(Sales[store_id]), "Store Revenue", '
            "[Revenue]), [Store Revenue])",
        )
        assert DaxReferenceResolutionRule().check(Context(project)) == []

    def test_auto_date_tables_are_legal(self, project, definition, replace_in):
        _add_measure(
            definition,
            replace_in,
            "measure Years = DISTINCTCOUNT('LocalDateTable_0a1b2c3d'[Year]) + "
            "COUNTROWS(DateTableTemplate_9f8e7d6c)",
        )
        assert DaxReferenceResolutionRule().check(Context(project)) == []

    def test_references_in_strings_and_comments_are_ignored(
        self, project, definition, replace_in
    ):
        _add_measure(
            definition,
            replace_in,
            "measure Label = \"'Gone'[x]\" -- 'Also Gone'[y]",
        )
        assert DaxReferenceResolutionRule().check(Context(project)) == []

    def test_bare_check_can_be_turned_off(self, project, definition, replace_in):
        _add_measure(definition, replace_in, "measure Ratio = [Old Measure]")
        rule = DaxReferenceResolutionRule()
        rule.configure({"check_bare_references": False})
        assert rule.check(Context(project)) == []


class TestDuplicateVariable:
    def test_clean_passes(self, project):
        assert DuplicateVariableRule().check(Context(project)) == []

    def test_outer_scope_duplicate(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "\t\t\tRETURN\n\t\t\t    DIVIDE([Revenue], store_count)",
            "\t\t\tVAR store_count = 2\n\t\t\tRETURN\n\t\t\t    DIVIDE([Revenue], store_count)",
        )
        violations = DuplicateVariableRule().check(Context(project))
        assert len(violations) == 1
        assert "store_count" in violations[0].message and violations[0].line == 29

    def test_nested_reuse_is_legal(self, project, definition, replace_in):
        _add_measure(
            definition,
            replace_in,
            "measure Pick = IF([Revenue] > 0, VAR t = 1 RETURN t, VAR t = 2 RETURN t)",
        )
        assert DuplicateVariableRule().check(Context(project)) == []
