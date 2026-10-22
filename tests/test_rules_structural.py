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
        assert any("unmatched DAX code fences" in v.message for v in violations)

    def test_null_bytes(self, project, definition):
        f = definition / "tables" / "_Stores.tmdl"
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
        products = (definition / "tables" / "_Products.tmdl").read_text(encoding="utf-8")
        tag = re.search(r"lineageTag:\s*(\S+)", products).group(1)
        stores_file = definition / "tables" / "_Stores.tmdl"
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
        stores = (definition / "tables" / "_Stores.tmdl").read_text(encoding="utf-8")
        new_tag = re.search(r"lineageTag:\s*(\S+)", stores).group(1)
        assert UUID_RE.match(new_tag)

    def test_fix_keeps_first_occurrence(self, project, definition):
        tag = self._duplicate_a_tag(definition)
        ctx = Context(project)
        LineageTagUniquenessRule().fix(ctx)
        products = (definition / "tables" / "_Products.tmdl").read_text(encoding="utf-8")
        assert tag in products  # original untouched


class TestLineageTagFormat:
    def test_clean_passes(self, project):
        assert LineageTagFormatRule().check(Context(project)) == []

    def test_malformed_tag_detected_and_fixed(self, project, definition):
        f = definition / "tables" / "__Calendar.tmdl"
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
        f = definition / "tables" / "_Products.tmdl"
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
            model.read_text(encoding="utf-8").replace("ref table _Stores\n", ""),
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
        stores = definition / "tables" / "_Stores.tmdl"
        stores.write_text(
            stores.read_text(encoding="utf-8").replace(
                'Csv.Document(File.Contents("stores.csv"), [Delimiter = ",", Encoding = 65001])',
                "#table(type table [store_id = Int64.Type], {{1}})",
            ),
            encoding="utf-8",
        )
        violations = EntityQuerySourceRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].obj == "_Stores"
        assert violations[0].severity == Severity.ERROR


class TestReservedTableNames:
    """M009: a table named with a Power BI reserved name (e.g. 'Measures')
    makes Power BI Desktop refuse to open the project."""

    def test_clean_passes(self, project):
        assert ReservedTableNameRule().check(Context(project)) == []

    def test_reserved_name_detected(self, project, definition):
        f = definition / "tables" / "_Products.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace("table _Products", "table Measures", 1),
            encoding="utf-8",
        )
        violations = ReservedTableNameRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].obj == "Measures"
        assert violations[0].severity == Severity.ERROR


# ---------------------------------------------------------------------------
# M010-M015
# ---------------------------------------------------------------------------

from tmdl_preflight.engine import fix as run_fix  # noqa: E402
from tmdl_preflight.rules import default_ruleset  # noqa: E402
from tmdl_preflight.rules.structural import (  # noqa: E402
    CalcGroupImplicitMeasuresRule,
    DanglingDescriptionRule,
    DuplicateObjectNamesRule,
    MetadataInExpressionRule,
    PropertyAfterChildBlockRule,
    RefTableTargetRule,
)


def _measures(definition):
    return definition / "tables" / "Sales Measures.tmdl"


class TestMetadataInExpression:
    def test_clean_passes(self, project):
        assert MetadataInExpressionRule().check(Context(project)) == []

    def test_property_buried_in_expression_body(self, project, definition, replace_in):
        replace_in(
            definition / "tables" / "__Calendar.tmdl",
            "\t\tsource = CALENDAR(DATE(2024, 1, 1), DATE(2026, 12, 31))",
            "\t\tsource =\n\t\t\t\tCALENDAR(DATE(2024, 1, 1), DATE(2026, 12, 31))\n"
            "\t\t\t\tlineageTag: 11111111-2222-4333-8444-555555555555",
        )
        violations = MetadataInExpressionRule().check(Context(project))
        assert len(violations) == 1
        assert "lineageTag" in violations[0].message
        assert violations[0].severity == Severity.ERROR

    def test_property_inside_fence(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "\t\t\t    DIVIDE([Revenue], store_count)\n\t\t\t```",
            "\t\t\t    DIVIDE([Revenue], store_count)\n\t\tisHidden\n\t\t\t```",
        )
        violations = MetadataInExpressionRule().check(Context(project))
        assert [v.line for v in violations] and "isHidden" in violations[0].message
        assert violations[0].line == 31

    def test_property_right_after_equals(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "\tmeasure 'Units Sold' = SUM(Sales[quantity])\n\t\tformatString: #,0\n",
            "\tmeasure 'Units Sold' =\n\t\tformatString: #,0\n",
        )
        violations = MetadataInExpressionRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].message == (
            "Units Sold: property right after `=` (line 22): formatString: #,0"
        ), violations[0].message

    def test_keyword_inside_string_or_comment_is_fine(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "\t\t\t    DIVIDE([Revenue], store_count)\n\t\t\t```",
            "\t\t\t    DIVIDE([Revenue], store_count)\n"
            "\t\t\t    -- displayFolder: not a property here\n\t\t\t```",
        )
        assert MetadataInExpressionRule().check(Context(project)) == []

    def test_not_baselinable(self):
        assert MetadataInExpressionRule.baselinable is False


class TestPropertyAfterChildBlock:
    def _plant(self, definition, replace_in):
        f = definition / "tables" / "Metric Selector.tmdl"
        replace_in(
            f,
            "\t\tsourceColumn: [Value3]\n\n\t\tannotation SummarizationSetBy = Automatic\n",
            "\t\tsourceColumn: [Value3]\n\n\t\tannotation SummarizationSetBy = Automatic\n"
            "\n\t\tdisplayFolder: Hidden helpers\n",
        )
        return f

    def test_clean_passes(self, project):
        assert PropertyAfterChildBlockRule().check(Context(project)) == []

    def test_detected(self, project, definition, replace_in):
        self._plant(definition, replace_in)
        violations = PropertyAfterChildBlockRule().check(Context(project))
        assert len(violations) == 1
        v = violations[0]
        assert v.severity == Severity.ERROR and v.fixable  # stricter since 1.2
        assert "displayFolder" in v.message and "Metric Selector Order" in v.obj

    def test_fix_moves_line_and_is_idempotent(self, project, definition, replace_in):
        f = self._plant(definition, replace_in)
        rule = PropertyAfterChildBlockRule()
        applied = rule.fix(Context(project))
        assert applied and "moved 1" in applied[0]
        text = f.read_text(encoding="utf-8")
        # the property moves to the column's first property slot (spec
        # B-property-after-child-block), right under the declaration
        assert (
            "\tcolumn 'Metric Selector Order'\n\t\tdisplayFolder: Hidden helpers\n"
            "\t\tisHidden\n" in text
        )
        # the blank line that stood before the moved line stays where it was
        assert "\t\tannotation SummarizationSetBy = Automatic\n\n" in text
        assert rule.check(Context(project)) == []
        assert rule.fix(Context(project)) == []

    def test_annotation_values_are_not_properties(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "\tannotation PBI_ResultType = Table",
            "\tannotation PBI_ResultType = Table\n\n\tannotation Note = ```\n"
            "\t\tisHidden\n\t\t```",
        )
        assert PropertyAfterChildBlockRule().check(Context(project)) == []


class TestDuplicateObjectNames:
    def test_clean_passes(self, project):
        assert DuplicateObjectNamesRule().check(Context(project)) == []

    def test_tables_differing_by_case(self, project, definition):
        src = definition / "tables" / "_Stores.tmdl"
        text = src.read_text(encoding="utf-8").replace("table _Stores", "table _STORES", 1)
        text = re.sub(r"lineageTag: \S+", lambda m: f"lineageTag: {uuid.uuid4()}", text)
        (definition / "tables" / "_STORES copy.tmdl").write_text(text, encoding="utf-8")
        violations = DuplicateObjectNamesRule().check(Context(project))
        # files are read in sorted order, so "_STORES copy.tmdl" comes first
        assert [v.obj for v in violations] == ["_Stores"]
        assert "duplicates table '_STORES'" in violations[0].message

    def test_duplicate_measure_in_one_table(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "\tpartition 'Sales Measures' = m",
            "\tmeasure 'units sold' = 1\n\t\tlineageTag: 0e0e0e0e-0000-4000-8000-000000000001\n\n"
            "\tpartition 'Sales Measures' = m",
        )
        violations = DuplicateObjectNamesRule().check(Context(project))
        assert len(violations) == 1 and "declared twice" in violations[0].message

    def test_duplicate_column_in_one_table(self, project, definition, replace_in):
        replace_in(
            definition / "tables" / "Sales.tmdl",
            "\tcolumn quantity\n",
            "\tcolumn Quantity\n\t\tdataType: int64\n\t\tsourceColumn: quantity\n\n"
            "\tcolumn quantity\n",
        )
        violations = DuplicateObjectNamesRule().check(Context(project))
        assert len(violations) == 1 and "column 'quantity'" in violations[0].message

    def test_measure_named_like_its_column(self, project, definition, replace_in):
        replace_in(
            definition / "tables" / "Sales.tmdl",
            "\tmeasure 'countrows sales' = COUNTROWS(Sales)",
            "\tmeasure Net_Amount = SUM(Sales[net_amount])\n\n"
            "\tmeasure 'countrows sales' = COUNTROWS(Sales)",
        )
        violations = DuplicateObjectNamesRule().check(Context(project))
        assert len(violations) == 1 and "same name as column" in violations[0].message


class TestDanglingDescription:
    def test_clean_passes(self, project):
        assert DanglingDescriptionRule().check(Context(project)) == []

    def test_blank_line_before_declaration_is_error(self, project, definition, replace_in):
        replace_in(
            _measures(definition),
            "\t/// Number of distinct orders placed.\n",
            "\t/// Number of distinct orders placed.\n\n",
        )
        violations = DanglingDescriptionRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR and violations[0].fixable

    def test_at_end_of_file_is_error(self, project, definition):
        f = definition / "tables" / "_Stores.tmdl"
        f.write_text(f.read_text(encoding="utf-8").rstrip("\n") + "\n\n/// orphan\n",
                     encoding="utf-8")
        violations = DanglingDescriptionRule().check(Context(project))
        assert len(violations) == 1 and violations[0].severity == Severity.ERROR

    def test_fix_preserves_crlf_and_is_idempotent(self, project, definition):
        f = _measures(definition)
        text = f.read_text(encoding="utf-8").replace(
            "\t/// Number of distinct orders placed.\n",
            "\t/// Number of distinct orders placed.\n\n",
        )
        f.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        rule = DanglingDescriptionRule()
        assert rule.fix(Context(project))
        raw = f.read_bytes().decode("utf-8")
        assert "\r\n" in raw and "\n" not in raw.replace("\r\n", "")
        assert "Number of distinct orders placed" not in raw
        assert "\tmeasure 'Orders #' = DISTINCTCOUNT" in raw
        assert rule.check(Context(project)) == []
        assert rule.fix(Context(project)) == []

    def test_fix_at_eof_keeps_blank_lines_before_the_run(self, project, definition):
        f = definition / "tables" / "_Stores.tmdl"
        original = f.read_text(encoding="utf-8")
        f.write_text(original.rstrip("\n") + "\n\n/// orphan\n", encoding="utf-8")
        DanglingDescriptionRule().fix(Context(project))
        # the run goes with the line break after it; the blank line before it
        # becomes the file's last line break
        assert f.read_text(encoding="utf-8") == original.rstrip("\n") + "\n"


class TestCalcGroupImplicitMeasures:
    def _add_calc_group(self, definition):
        (definition / "tables" / "Time Intelligence.tmdl").write_text(
            "table 'Time Intelligence'\n"
            "\tlineageTag: 0f0f0f0f-0000-4000-8000-000000000001\n\n"
            "\tcalculationGroup\n"
            "\t\tprecedence: 1\n\n"
            "\t\tcalculationItem Current = SELECTEDMEASURE()\n\n"
            "\tcolumn Name\n"
            "\t\tdataType: string\n"
            "\t\tlineageTag: 0f0f0f0f-0000-4000-8000-000000000002\n"
            "\t\tsummarizeBy: none\n"
            "\t\tsourceColumn: Name\n\n"
            "\tpartition 'Time Intelligence' = calculationGroup\n"
            "\t\tmode: import\n",
            encoding="utf-8",
        )
        mf = definition / "model.tmdl"
        mf.write_text(mf.read_text(encoding="utf-8") + "ref table 'Time Intelligence'\n",
                      encoding="utf-8")

    def test_clean_passes(self, project):
        assert CalcGroupImplicitMeasuresRule().check(Context(project)) == []

    def test_calc_group_without_flag(self, project, definition):
        self._add_calc_group(definition)
        violations = CalcGroupImplicitMeasuresRule().check(Context(project))
        assert len(violations) == 1 and "Time Intelligence" in violations[0].message

    def test_flag_set(self, project, definition, replace_in):
        self._add_calc_group(definition)
        replace_in(
            definition / "model.tmdl",
            "\tculture: en-US\n",
            "\tculture: en-US\n\tdiscourageImplicitMeasures\n",
        )
        assert CalcGroupImplicitMeasuresRule().check(Context(project)) == []


class TestRefTableTarget:
    def test_clean_passes(self, project):
        assert RefTableTargetRule().check(Context(project)) == []

    def test_ref_without_table(self, project, definition):
        (definition / "tables" / "_Stores.tmdl").unlink()
        violations = RefTableTargetRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].obj == "_Stores" and violations[0].line == 13
        assert RefTableTargetRule.baselinable is False

    def test_case_difference_still_resolves(self, project, definition, replace_in):
        replace_in(definition / "model.tmdl", "ref table _Stores\n", "ref table _stores\n")
        assert RefTableTargetRule().check(Context(project)) == []


def test_new_fixers_leave_clean_model_untouched(project):
    before = {f: f.read_bytes() for f in sorted(project.rglob("*")) if f.is_file()}
    report = run_fix(Context(project), default_ruleset())
    assert report.fixes_applied == []
    assert before == {f: f.read_bytes() for f in sorted(project.rglob("*")) if f.is_file()}
