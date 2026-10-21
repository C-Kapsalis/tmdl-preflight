"""Relationship, calendar and key rules: R001-R016 (spec slice RL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations
from tmdl_preflight.parser import parse_model
from tmdl_preflight.rules.base import Context, Severity
from tmdl_preflight.rules.relationships import (
    AmbiguousActivePairRule,
    AutodetectedRelationshipsRule,
    BidirectionalFilterRule,
    FactConformedDimensionJoinRule,
    OrphanTablesRule,
    RelationshipCardinalityRule,
    RelationshipEndpointsRule,
)
from tmdl_preflight.rules.topology import (
    CalendarRelationshipCardinalityRule,
    CalendarStandardColumnsRule,
    CohortCalendarReachRule,
    DeadAnchorCalendarRule,
    DimensionKeyColumnsRule,
    FactCalendarCoverageRule,
    RelationshipCyclesRule,
    RelationshipsPresenceRule,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _table(folder: Path, name: str, cols: list[str], extra: str = "") -> None:
    body = f"table '{name}'\n"
    for c in cols:
        body += (f"\tcolumn {c}\n\t\tdataType: string\n\t\tsourceColumn: {c}\n\n")
    body += extra
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = Sql.Database(\"s\", \"d\")\n"
    (folder / f"{name}.tmdl").write_text(body, encoding="utf-8")


def _model(tmp_path: Path, name: str = "Shop.SemanticModel") -> Path:
    d = tmp_path / name / "definition"
    (d / "tables").mkdir(parents=True)
    (d / "model.tmdl").write_text("model Shop\n\tculture: en-US\n", encoding="utf-8")
    return d


def _rels(d: Path, text: str) -> None:
    (d / "relationships.tmdl").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# RL-26: the parser accepts a tab (any whitespace) after the keyword
# ---------------------------------------------------------------------------


def test_relationship_keyword_followed_by_a_tab_is_parsed(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d, "relationship\t11111111-2222-4333-8444-555555555555\n"
             "\tfromColumn: Orders.id\n"
             "\ttoColumn: Stores.id\n")
    model = parse_model(d)
    assert len(model.relationships) == 1
    assert model.relationships[0].rel_id == "11111111-2222-4333-8444-555555555555"
    assert (model.relationships[0].from_table, model.relationships[0].from_column) == ("Orders", "id")
    assert (model.relationships[0].to_table, model.relationships[0].to_column) == ("Stores", "id")
    assert not model.parse_errors


# ---------------------------------------------------------------------------
# RL-13: R001 texts
# ---------------------------------------------------------------------------


def test_r001_missing_to_column_message(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tfromColumn: Orders.id\n"
             "\ttoColumn: Stores.missing\n")
    ctx = Context(tmp_path)
    found = RelationshipEndpointsRule().check(ctx)
    assert len(found) == 1
    assert found[0].message.startswith("To column not found: Stores[missing] (in relationship 11111111...)")


def test_r001_missing_from_table_message(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tfromColumn: Ghosts.id\n"
             "\ttoColumn: Orders.id\n")
    found = RelationshipEndpointsRule().check(Context(tmp_path))
    assert len(found) == 1
    assert found[0].message.startswith("From table not found: Ghosts (in relationship 11111111...)")


def test_r001_summary_note(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tfromColumn: Orders.id\n"
             "\ttoColumn: Stores.id\n"
             "\n"
             "relationship 22222222-2222-4333-8444-555555555555\n"
             "\tisActive: false\n"
             "\tfromColumn: Orders.id\n"
             "\ttoColumn: Stores.id\n")
    ctx = Context(tmp_path)
    RelationshipEndpointsRule().check(ctx)
    joined = "\n".join(ctx.notes)
    assert "Validated 2 relationships" in joined
    assert "   Errors: 0" in joined
    assert "   Warnings (inactive): 1" in joined
    assert "   Success rate: 100.0%" in joined
    assert "Inactive: Orders -> Stores" in joined


# ---------------------------------------------------------------------------
# RL-14: R002 texts and the cardinality distribution note
# ---------------------------------------------------------------------------


def test_r002_invalid_to_cardinality_message(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\ttoCardinality: single\n"
             "\tfromColumn: Orders.id\n"
             "\ttoColumn: Stores.id\n")
    found = RelationshipCardinalityRule().check(Context(tmp_path))
    assert len(found) == 1
    assert found[0].message == "Invalid to cardinality: single in 11111111..."


def test_r002_cardinality_distribution_note(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tfromColumn: Orders.id\n"
             "\ttoColumn: Stores.id\n")
    ctx = Context(tmp_path)
    RelationshipCardinalityRule().check(ctx)
    joined = "\n".join(ctx.notes)
    assert "Cardinality Distribution:" in joined
    assert f"   {'many_to_one':20s} {1:3d}" in joined


# ---------------------------------------------------------------------------
# RL-15: R004 note
# ---------------------------------------------------------------------------


def test_r004_note(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tcrossFilteringBehavior: bothDirections\n"
             "\tfromColumn: Orders.id\n"
             "\ttoColumn: Stores.id\n")
    ctx = Context(tmp_path)
    BidirectionalFilterRule().check(ctx)
    joined = "\n".join(ctx.notes)
    assert "Cross-filtering Analysis:" in joined
    assert "   Unidirectional: 0" in joined
    assert "   Bidirectional: 1" in joined
    assert "   - Orders <-> Stores" in joined
    assert "     Orders[id] <-> Stores[id]" in joined
    assert "Bidirectional count is acceptable (<=3)" in joined


# ---------------------------------------------------------------------------
# RL-9: R006 one finding per table pair, naming every relationship
# ---------------------------------------------------------------------------


def test_r006_one_finding_per_pair(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id", "store_id", "region_id"])
    _table(d / "tables", "Stores", ["id", "region_id"])
    _rels(d,
          "relationship aaaaaaaa-1111-4333-8444-555555555555\n"
          "\tfromColumn: Orders.store_id\n\ttoColumn: Stores.id\n\n"
          "relationship bbbbbbbb-2222-4333-8444-555555555555\n"
          "\tfromColumn: Orders.region_id\n\ttoColumn: Stores.region_id\n\n"
          "relationship cccccccc-3333-4333-8444-555555555555\n"
          "\tfromColumn: Orders.id\n\ttoColumn: Stores.id\n")
    found = AmbiguousActivePairRule().check(Context(tmp_path))
    assert len(found) == 1
    message = found[0].message
    assert "3 active" in message
    for rid in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        assert rid in message
    assert "store_id->id" in message


# ---------------------------------------------------------------------------
# RL-10 and RL-20: R011
# ---------------------------------------------------------------------------


def test_r011_facts_without_a_calendar_table(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Views", ["id"])
    _rels(d, "")
    found = FactCalendarCoverageRule().check(Context(tmp_path))
    assert len(found) == 1
    assert "Calendar coverage 0.0% below threshold 90.0" in found[0].message
    assert "Fact tables with NO __Calendar relationship (active or inactive): Orders, Views" in found[0].message


def test_r011_coverage_below_threshold(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "__Calendar", ["Date"])
    for n in range(10):
        _table(d / "tables", f"Fact{n:02d}", ["id"])
    rels = "".join(
        f"relationship r{n:08d}-1111-4333-8444-555555555555\n"
        f"\tfromColumn: Fact{n:02d}.id\n\ttoColumn: __Calendar.Date\n\n"
        for n in range(8)
    )
    _rels(d, rels)
    found = FactCalendarCoverageRule().check(Context(tmp_path))
    assert len(found) == 1
    assert "Calendar coverage 80.0% below threshold 90.0" in found[0].message


def test_r011_is_an_error(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "__Calendar", ["Date"])
    for n in range(10):
        _table(d / "tables", f"Fact{n:02d}", ["id"])
    rels = "".join(
        f"relationship r{n:08d}-1111-4333-8444-555555555555\n"
        f"\tfromColumn: Fact{n:02d}.id\n\ttoColumn: __Calendar.Date\n\n"
        for n in range(8)
    )
    _rels(d, rels)
    code, payload = run_check(d.parent, "fact-calendar-coverage")
    assert code == 1
    assert violations(payload, "R011")[0]["severity"] == "error"


# ---------------------------------------------------------------------------
# RL-21: R012
# ---------------------------------------------------------------------------


def test_r012_raw_case_compare(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "__Calendar", ["Date"])
    _table(d / "tables", "Orders", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tfromCardinality: Many\n"
             "\tfromColumn: Orders.id\n\ttoColumn: __Calendar.Date\n")
    found = CalendarRelationshipCardinalityRule().check(Context(tmp_path))
    assert len(found) == 1
    assert "Orders[id] -> __Calendar[Date]: Many-to-one" in found[0].message


def test_r012_note(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "__Calendar", ["Date"])
    _table(d / "tables", "Orders", ["id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tfromColumn: Orders.id\n\ttoColumn: __Calendar.Date\n")
    ctx = Context(tmp_path)
    CalendarRelationshipCardinalityRule().check(ctx)
    joined = "\n".join(ctx.notes)
    assert "Calendar Relationship Cardinality:" in joined
    assert "Total calendar relationships: 1" in joined
    assert "Valid (many-to-one): 1" in joined
    assert "Invalid cardinality: 0" in joined


# ---------------------------------------------------------------------------
# RL-12: R009 runs by default
# ---------------------------------------------------------------------------


def test_r009_missing_file_is_an_error_by_default(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    code, payload = run_check(d.parent)
    found = violations(payload, "R009")
    assert len(found) == 1
    assert found[0]["severity"] == "error"
    assert found[0]["message"] == "relationships.tmdl file not found"
    assert code == 1


def test_r009_zero_relationships_message(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _rels(d, "// only a comment\n")
    code, payload = run_check(d.parent)
    found = violations(payload, "R009")
    assert len(found) == 1
    assert found[0]["message"] == "relationships.tmdl exists but parses to zero relationships"


# ---------------------------------------------------------------------------
# RL-16: R005 name buckets
# ---------------------------------------------------------------------------


def test_r005_expected_orphan_names_are_exempt(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "z-Toggle", ["id"])
    _table(d / "tables", "y-Plot Specific 1", ["id"])
    _table(d / "tables", "My Selector", ["id"])
    _table(d / "tables", "Report Measures", ["id"])
    _rels(d, "")
    found = OrphanTablesRule().check(Context(tmp_path))
    assert found == []


def test_r005_summary_note(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "z-Toggle", ["id"])
    _rels(d, "")
    ctx = Context(tmp_path)
    OrphanTablesRule().check(ctx)
    joined = "\n".join(ctx.notes)
    assert "Total tables: 2" in joined
    assert "With relationships: 0" in joined
    assert "Orphans: 2" in joined
    assert "Expected orphans (Plot Specific/Selector/Measure): 1" in joined
    assert "Unexpected orphans: 1" in joined


# ---------------------------------------------------------------------------
# RL-17: R010 self loops
# ---------------------------------------------------------------------------


def test_r010_self_loop(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id", "parent_id"])
    _rels(d, "relationship 11111111-2222-4333-8444-555555555555\n"
             "\tfromColumn: Orders.parent_id\n\ttoColumn: Orders.id\n")
    found = RelationshipCyclesRule().check(Context(tmp_path))
    assert len(found) == 1
    assert found[0].message == "Cycle detected: Orders -> Orders"


# ---------------------------------------------------------------------------
# RL-18 and RL-19: R007
# ---------------------------------------------------------------------------


def test_r007_finding_text(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d, "relationship AutoDetected_11111111-2222-4333-8444-555555555555\n"
             "\tisActive: false\n"
             "\tfromColumn: Orders.id\n\ttoColumn: Stores.id\n")
    found = AutodetectedRelationshipsRule().check(Context(tmp_path))
    assert len(found) == 1
    assert found[0].message.startswith("inactive  ")
    assert "Orders[id] -> Stores[id]" in found[0].message
    assert "name: AutoDetected_11111111-2222-4333-8444-555555555555" in found[0].message
    assert AutodetectedRelationshipsRule.baselinable is False


def test_r007_fixer_keeps_the_other_bytes(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d,
          "relationship 11111111-2222-4333-8444-555555555555\n"
          "\tfromColumn: Orders.id\n"
          "\ttoColumn: Stores.id\n"
          "\n"
          "relationship AutoDetected_22222222-2222-4333-8444-555555555555\n"
          "\tfromColumn: Orders.id\n"
          "\ttoColumn: Stores.id\n"
          "\n"
          "\n")
    code, _out, _err = run_cli("fix", d.parent, "--select", "R007", "--no-config")
    assert code == 0
    text = (d / "relationships.tmdl").read_text(encoding="utf-8")
    assert text.endswith("toColumn: Stores.id\n\n")
    assert "AutoDetected" not in text
