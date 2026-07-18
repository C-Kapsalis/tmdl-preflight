"""Rules R001-R005: relationship integrity and topology advisories."""

from __future__ import annotations

from tmdl_preflight.rules.base import Context, Severity
from tmdl_preflight.rules.relationships import (
    BidirectionalFilterRule,
    DuplicateRelationshipsRule,
    OrphanTablesRule,
    RelationshipCardinalityRule,
    RelationshipEndpointsRule,
)


def _rels_file(definition):
    return definition / "relationships.tmdl"


class TestRelationshipEndpoints:
    def test_clean_passes(self, project):
        assert RelationshipEndpointsRule().check(Context(project)) == []

    def test_missing_table_detected(self, project, definition):
        f = _rels_file(definition)
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "toColumn: Stores.store_id", "toColumn: Warehouses.warehouse_id"
            ),
            encoding="utf-8",
        )
        violations = RelationshipEndpointsRule().check(Context(project))
        assert any("'Warehouses' does not exist" in v.message for v in violations)

    def test_missing_column_detected(self, project, definition):
        f = _rels_file(definition)
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "fromColumn: Sales.product_id", "fromColumn: Sales.sku"
            ),
            encoding="utf-8",
        )
        violations = RelationshipEndpointsRule().check(Context(project))
        assert any("'Sales'[sku] does not exist" in v.message for v in violations)


class TestRelationshipCardinality:
    def test_clean_passes(self, project):
        assert RelationshipCardinalityRule().check(Context(project)) == []

    def test_invalid_cardinality_detected(self, project, definition):
        f = _rels_file(definition)
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tfromColumn: Sales.product_id",
                "\tfromCardinality: both\n\tfromColumn: Sales.product_id",
            ),
            encoding="utf-8",
        )
        violations = RelationshipCardinalityRule().check(Context(project))
        assert len(violations) == 1
        assert "'both'" in violations[0].message
        assert "not a cardinality" in violations[0].message


class TestDuplicateRelationships:
    def test_clean_passes(self, project):
        assert DuplicateRelationshipsRule().check(Context(project)) == []

    def test_duplicate_endpoints_detected(self, project, definition):
        f = _rels_file(definition)
        text = f.read_text(encoding="utf-8")
        text += (
            "\nrelationship 99999999-0000-4000-8000-000000000000\n"
            "\tfromColumn: Sales.product_id\n"
            "\ttoColumn: Products.product_id\n"
        )
        f.write_text(text, encoding="utf-8")
        violations = DuplicateRelationshipsRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "duplicate" in violations[0].message


class TestBidirectionalFilter:
    def test_clean_passes(self, project):
        assert BidirectionalFilterRule().check(Context(project)) == []

    def test_bidirectional_surfaced_as_info(self, project, definition):
        f = _rels_file(definition)
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tfromColumn: Sales.store_id",
                "\tcrossFilteringBehavior: bothDirections\n\tfromColumn: Sales.store_id",
            ),
            encoding="utf-8",
        )
        violations = BidirectionalFilterRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].severity == Severity.INFO


class TestOrphanTables:
    def test_clean_passes(self, project):
        assert OrphanTablesRule().check(Context(project)) == []

    def test_orphan_data_table_detected(self, project, definition):
        (definition / "tables" / "Returns.tmdl").write_text(
            "table Returns\n"
            "\tlineageTag: 77777777-7777-4777-8777-777777777777\n"
            "\n"
            "\tcolumn return_id\n"
            "\t\tdataType: int64\n"
            "\t\tlineageTag: 66666666-6666-4666-8666-666666666666\n"
            "\t\tsummarizeBy: none\n"
            "\t\tsourceColumn: return_id\n",
            encoding="utf-8",
        )
        violations = OrphanTablesRule().check(Context(project))
        assert len(violations) == 1
        assert "Returns" in violations[0].message
        assert violations[0].severity == Severity.INFO

    def test_measure_only_and_field_parameter_exempt(self, project):
        # fixture has both 'Sales Measures' (no columns) and 'Metric Selector'
        # (field parameter) unrelated to anything, yet the clean check passes.
        assert OrphanTablesRule().check(Context(project)) == []

    def test_measure_home_table_with_hidden_column_exempt(self, project, definition):
        # The classic measure-home pattern: one hidden placeholder column plus
        # measures, no relationships (regression: real models declare dozens
        # of these and they are orphans by design).
        (definition / "tables" / "Inventory Measures.tmdl").write_text(
            "table 'Inventory Measures'\n"
            "\tlineageTag: 55555555-5555-4555-8555-555555555555\n"
            "\n"
            "\tmeasure 'Stock Level' = COUNTROWS(Products)\n"
            "\t\tlineageTag: 44444444-4444-4444-8444-444444444444\n"
            "\n"
            "\tcolumn placeholder_value\n"
            "\t\tdataType: int64\n"
            "\t\tisHidden\n"
            "\t\tlineageTag: 33333333-3333-4333-8333-333333333333\n"
            "\t\tsourceColumn: placeholder_value\n",
            encoding="utf-8",
        )
        assert OrphanTablesRule().check(Context(project)) == []

    def test_hidden_table_exempt(self, project, definition):
        # Hidden helper tables are unrelated by design (regression: real
        # models keep hidden mapping tables with visible-typed columns).
        (definition / "tables" / "Size Mappings.tmdl").write_text(
            "table 'Size Mappings'\n"
            "\tisHidden\n"
            "\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
            "\n"
            "\tcolumn size_code\n"
            "\t\tdataType: string\n"
            "\t\tlineageTag: 11111111-1111-4111-8111-111111111111\n"
            "\t\tsourceColumn: size_code\n",
            encoding="utf-8",
        )
        assert OrphanTablesRule().check(Context(project)) == []
