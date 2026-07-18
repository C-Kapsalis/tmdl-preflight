"""Rules M001-M005: structure, well-formedness, lineage tags, data types."""

from __future__ import annotations

import re
import uuid

from tmdl_preflight.rules.base import Context, Severity
from tmdl_preflight.rules.structural import (
    ColumnDataTypeRule,
    EntityQuerySourceRule,
    LineageTagFormatRule,
    LineageTagUniquenessRule,
    ModelStructureRule,
    ModelTableReferencesRule,
    ReservedTableNameRule,
    TablePartitionPresenceRule,
    TmdlWellFormedRule,
)

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


class TestModelStructure:
    def test_clean_passes(self, project):
        assert ModelStructureRule().check(Context(project)) == []

    def test_missing_model_tmdl(self, project, definition):
        (definition / "model.tmdl").unlink()
        violations = ModelStructureRule().check(Context(project))
        assert len(violations) == 1
        assert "model.tmdl" in violations[0].message

    def test_empty_tables_dir(self, project, definition):
        for f in (definition / "tables").glob("*.tmdl"):
            f.unlink()
        violations = ModelStructureRule().check(Context(project))
        assert any("no .tmdl files" in v.message for v in violations)


class TestTmdlWellFormed:
    def test_clean_passes(self, project):
        assert TmdlWellFormedRule().check(Context(project)) == []

    def test_unpaired_fence(self, project, definition):
        f = definition / "tables" / "Sales Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\t\t\t    DIVIDE([Revenue], store_count)\n\t\t\t```",
                "\t\t\t    DIVIDE([Revenue], store_count)",
            ),
            encoding="utf-8",
        )
        violations = TmdlWellFormedRule().check(Context(project))
        assert any("unpaired expression fences" in v.message for v in violations)

    def test_null_bytes(self, project, definition):
        f = definition / "tables" / "Stores.tmdl"
        f.write_bytes(f.read_bytes() + b"\x00")
        violations = TmdlWellFormedRule().check(Context(project))
        assert any("null bytes" in v.message for v in violations)

    def test_missing_table_declaration(self, project, definition):
        (definition / "tables" / "Broken.tmdl").write_text(
            "\tcolumn floating\n\t\tdataType: string\n", encoding="utf-8"
        )
        violations = TmdlWellFormedRule().check(Context(project))
        assert any("no table declaration" in v.message for v in violations)


class TestLineageTagUniqueness:
    def _duplicate_a_tag(self, definition):
        """Copy Products' table tag onto Stores' table tag."""
        products = (definition / "tables" / "Products.tmdl").read_text(encoding="utf-8")
        tag = re.search(r"lineageTag:\s*(\S+)", products).group(1)
        stores_file = definition / "tables" / "Stores.tmdl"
        stores = stores_file.read_text(encoding="utf-8")
        old_tag = re.search(r"lineageTag:\s*(\S+)", stores).group(1)
        stores_file.write_text(stores.replace(old_tag, tag, 1), encoding="utf-8")
        return tag

    def test_clean_passes(self, project):
        assert LineageTagUniquenessRule().check(Context(project)) == []

    def test_duplicate_detected(self, project, definition):
        tag = self._duplicate_a_tag(definition)
        violations = LineageTagUniquenessRule().check(Context(project))
        assert len(violations) == 1
        assert tag in violations[0].message
        assert violations[0].fixable

    def test_fix_regenerates_duplicate(self, project, definition):
        self._duplicate_a_tag(definition)
        ctx = Context(project)
        rule = LineageTagUniquenessRule()
        assert rule.check(ctx)
        applied = rule.fix(ctx)
        assert len(applied) == 1
        ctx.reload()
        assert rule.check(ctx) == []
        # regenerated tag is a canonical UUID
        stores = (definition / "tables" / "Stores.tmdl").read_text(encoding="utf-8")
        new_tag = re.search(r"lineageTag:\s*(\S+)", stores).group(1)
        assert UUID_RE.match(new_tag)

    def test_fix_keeps_first_occurrence(self, project, definition):
        tag = self._duplicate_a_tag(definition)
        ctx = Context(project)
        LineageTagUniquenessRule().fix(ctx)
        products = (definition / "tables" / "Products.tmdl").read_text(encoding="utf-8")
        assert tag in products  # original untouched


class TestLineageTagFormat:
    def test_clean_passes(self, project):
        assert LineageTagFormatRule().check(Context(project)) == []

    def test_malformed_tag_detected_and_fixed(self, project, definition):
        f = definition / "tables" / "Calendar.tmdl"
        text = f.read_text(encoding="utf-8")
        old = re.search(r"lineageTag:\s*(\S+)", text).group(1)
        f.write_text(text.replace(old, "not-a-real-uuid", 1), encoding="utf-8")

        ctx = Context(project)
        rule = LineageTagFormatRule()
        violations = rule.check(ctx)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING

        applied = rule.fix(ctx)
        assert len(applied) == 1
        ctx.reload()
        assert rule.check(ctx) == []
        new = re.search(r"lineageTag:\s*(\S+)", f.read_text(encoding="utf-8")).group(1)
        assert UUID_RE.match(new)


class TestColumnDataTypes:
    def test_clean_passes(self, project):
        assert ColumnDataTypeRule().check(Context(project)) == []

    def test_unknown_type_flagged(self, project, definition):
        f = definition / "tables" / "Products.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace("dataType: string", "dataType: text", 1),
            encoding="utf-8",
        )
        violations = ColumnDataTypeRule().check(Context(project))
        assert len(violations) == 1
        assert "'text'" in violations[0].message
        assert violations[0].severity == Severity.WARNING


class TestModelTableReferences:
    """M006: every tables/*.tmdl must be linked via ``ref table`` in model.tmdl.
    A missing ref means Power BI Desktop refuses to open the project."""

    def test_clean_passes(self, project):
        assert ModelTableReferencesRule().check(Context(project)) == []

    def test_missing_ref_detected_and_fixed(self, project, definition):
        model = definition / "model.tmdl"
        model.write_text(
            model.read_text(encoding="utf-8").replace("ref table Stores\n", ""),
            encoding="utf-8",
        )
        ctx = Context(project)
        rule = ModelTableReferencesRule()
        violations = rule.check(ctx)
        assert len(violations) == 1
        assert "Stores" in violations[0].message
        assert violations[0].fixable

        rule.fix(ctx)
        ctx.reload()
        assert rule.check(ctx) == []


class TestTablePartitions:
    """M007: every table (including measures-only tables) needs a partition,
    or Power BI crashes on open in GetLinkedQuery."""

    def test_clean_passes(self, project):
        assert TablePartitionPresenceRule().check(Context(project)) == []

    def test_missing_partition_detected(self, project, definition):
        sm = definition / "tables" / "Sales Measures.tmdl"
        text = sm.read_text(encoding="utf-8")
        sm.write_text(text[: text.index("\tpartition ")].rstrip() + "\n", encoding="utf-8")
        violations = TablePartitionPresenceRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].obj == "Sales Measures"
        assert violations[0].severity == Severity.ERROR


class TestEntityQuerySource:
    """M008: inline ``#table(type table [...])`` entity sources force a
    composite model and block open."""

    def test_clean_passes(self, project):
        assert EntityQuerySourceRule().check(Context(project)) == []

    def test_entity_source_detected(self, project, definition):
        stores = definition / "tables" / "Stores.tmdl"
        stores.write_text(
            stores.read_text(encoding="utf-8").replace(
                'Csv.Document(File.Contents("stores.csv"), [Delimiter = ",", Encoding = 65001])',
                "#table(type table [store_id = Int64.Type], {{1}})",
            ),
            encoding="utf-8",
        )
        violations = EntityQuerySourceRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].obj == "Stores"
        assert violations[0].severity == Severity.ERROR


class TestReservedTableNames:
    """M009: a table named with a Power BI reserved name (e.g. 'Measures')
    makes Power BI Desktop refuse to open the project."""

    def test_clean_passes(self, project):
        assert ReservedTableNameRule().check(Context(project)) == []

    def test_reserved_name_detected(self, project, definition):
        f = definition / "tables" / "Products.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace("table Products", "table Measures", 1),
            encoding="utf-8",
        )
        violations = ReservedTableNameRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].obj == "Measures"
        assert violations[0].severity == Severity.ERROR
