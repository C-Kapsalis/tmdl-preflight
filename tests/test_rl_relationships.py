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


# ---------------------------------------------------------------------------
# RL-1: R015 derives the subject dimensions and subject facts from the
# relationship sides
# ---------------------------------------------------------------------------


def _cohort_model(tmp_path: Path, name: str = "Shop.SemanticModel") -> Path:
    d = _model(tmp_path, name)
    _table(d / "tables", "__Cohort Calendar", ["Date", "Registration Cohort Date"])
    _table(d / "tables", "__Other Calendar", ["Date", "Registration Cohort Date"])
    _table(d / "tables", "_Users", ["user_id"])
    _table(d / "tables", "_Region", ["region_id"])
    _table(d / "tables", "Orders", ["user_id", "order_id"])
    _table(d / "tables", "Views", ["user_id"])
    return d


def test_r015_subjects_come_from_the_relationship_sides(tmp_path):
    d = _cohort_model(tmp_path)
    _rels(d,
          "relationship 11111111-1111-4333-8444-555555555555\n"
          "\tfromColumn: _Users.user_id\n\ttoColumn: __Cohort Calendar.Date\n"
          "\n"
          "relationship 22222222-2222-4333-8444-555555555555\n"
          "\tfromColumn: Orders.order_id\n\ttoColumn: __Other Calendar.Date\n"
          "\n"
          "relationship 33333333-3333-4333-8444-555555555555\n"
          "\tfromColumn: Orders.user_id\n\ttoColumn: _Users.user_id\n"
          "\n"
          "relationship 44444444-4444-4333-8444-555555555555\n"
          "\tfromColumn: Views.user_id\n\ttoColumn: _Users.user_id\n"
          "\n"
          "relationship 55555555-5555-4333-8444-555555555555\n"
          "\tcrossFilteringBehavior: bothDirections\n"
          "\tfromColumn: _Users.user_id\n\ttoColumn: _Region.region_id\n")
    found = CohortCalendarReachRule().check(Context(tmp_path))
    # the reverse edge a bidirectional relationship adds does not make _Region
    # a subject fact
    assert len(found) == 1
    assert found[0].obj == "__Other Calendar"
    assert "_Region" not in found[0].message
    assert "Views" in found[0].message


def test_r015_a_dimension_is_never_a_subject_fact(tmp_path):
    d = _cohort_model(tmp_path)
    (d / "tables" / "__Other Calendar.tmdl").unlink()
    _rels(d,
          "relationship 11111111-1111-4333-8444-555555555555\n"
          "\tfromColumn: _Users.user_id\n\ttoColumn: __Cohort Calendar.Date\n"
          "\n"
          "relationship 33333333-3333-4333-8444-555555555555\n"
          "\tfromColumn: Orders.user_id\n\ttoColumn: _Users.user_id\n"
          "\n"
          "relationship 44444444-4444-4333-8444-555555555555\n"
          "\tfromColumn: Views.user_id\n\ttoColumn: _Users.user_id\n")
    found = CohortCalendarReachRule().check(Context(tmp_path))
    assert found == []


# ---------------------------------------------------------------------------
# RL-23: R015 text
# ---------------------------------------------------------------------------


def test_r015_finding_text(tmp_path):
    d = _cohort_model(tmp_path)
    _rels(d,
          "relationship 11111111-1111-4333-8444-555555555555\n"
          "\tfromColumn: _Users.user_id\n\ttoColumn: __Cohort Calendar.Date\n"
          "\n"
          "relationship 22222222-2222-4333-8444-555555555555\n"
          "\tfromColumn: Orders.order_id\n\ttoColumn: __Other Calendar.Date\n"
          "\n"
          "relationship 33333333-3333-4333-8444-555555555555\n"
          "\tfromColumn: Orders.user_id\n\ttoColumn: _Users.user_id\n"
          "\n"
          "relationship 44444444-4444-4333-8444-555555555555\n"
          "\tfromColumn: Views.user_id\n\ttoColumn: _Users.user_id\n")
    found = CohortCalendarReachRule().check(Context(tmp_path))
    assert len(found) == 1
    assert found[0].message == (
        "Shop.SemanticModel: '__Other Calendar' cannot filter ['Views'] over the "
        "active relationship graph (subject-bearing facts: ['Orders', 'Views'])"
    )


# ---------------------------------------------------------------------------
# RL-24: R015 stays opt-in
# ---------------------------------------------------------------------------


def test_r015_nothing_checked_is_opt_in(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _rels(d, "")
    rule = CohortCalendarReachRule()
    assert rule.check(Context(tmp_path)) == []
    rule.options["require_cohort_calendars"] = True
    assert rule.check(Context(tmp_path)) != []


# ---------------------------------------------------------------------------
# RL-22: R013 and R014 run by default (advisory)
# ---------------------------------------------------------------------------


def test_r013_runs_by_default(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "__Calendar", ["Date", "Year", "Quarter", "Month", "Day"])
    _rels(d, "")
    code, payload = run_check(d.parent)
    found = violations(payload, "R013")
    assert len(found) == 1
    assert found[0]["severity"] == "info"
    assert "Week" in found[0]["message"]


def test_r014_runs_by_default(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "_Users", ["full_name"])
    _rels(d, "")
    code, payload = run_check(d.parent)
    found = violations(payload, "R014")
    assert len(found) == 1
    assert found[0]["severity"] == "info"
    assert "_Users" in found[0]["message"]


def test_r013_note_layout(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "__Calendar", ["Date", "Year", "Quarter", "Month", "Day"])
    _rels(d, "")
    ctx = Context(tmp_path)
    CalendarStandardColumnsRule().check(ctx)
    joined = "\n".join(ctx.notes)
    assert "Calendar Table Completeness:" in joined
    assert "Total columns: 5" in joined
    assert "Standard columns present: 5/6" in joined
    assert "Advisory - Missing standard columns:" in joined
    assert "These columns are recommended for complete date hierarchies." in joined
    assert "Additional columns (0):" not in joined


def test_r014_note_layout(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "_Users", ["full_name"])
    _rels(d, "")
    ctx = Context(tmp_path)
    DimensionKeyColumnsRule().check(ctx)
    joined = "\n".join(ctx.notes)
    assert "Total dimension tables (_prefix): 1" in joined
    assert "With key columns: 0 (0.0%)" in joined
    assert "Without apparent keys: 1" in joined
    assert "(Patterns: _x_id, _id, date, _level, z-, .id)" in joined
    assert "  Table: _Users" in joined
    assert "    column: full_name" in joined


# ---------------------------------------------------------------------------
# RL-25: R016 retained list per model
# ---------------------------------------------------------------------------


def test_r016_retained_is_per_model(tmp_path):
    root = tmp_path
    a = _model(root, "ModelA.SemanticModel")
    _table(a / "tables", "__X Calendar", ["Date"])
    _rels(a, "")
    b = _model(root, "ModelB.SemanticModel")
    _table(b / "tables", "__X Calendar", ["Date"])
    _rels(b, "")
    rule = DeadAnchorCalendarRule()
    rule.options["retained"] = {"ModelA": ["__X Calendar"]}
    found = rule.check(Context(root))
    assert len(found) == 1
    assert found[0].obj == "ModelB.SemanticModel"
    assert found[0].file is not None and "ModelB" in str(found[0].file)


# ---------------------------------------------------------------------------
# RL-2: R016 reads the template calendars from a folder that is not scanned
# ---------------------------------------------------------------------------


def test_r016_template_outside_the_scan(tmp_path):
    root = tmp_path
    client = _model(root, "Client.SemanticModel")
    _table(client / "tables", "__Comparison Calendar", ["Date"])
    _rels(client, "")
    template = root / "template" / "Template.SemanticModel" / "definition"
    (template / "tables").mkdir(parents=True)
    _table(template / "tables", "__Comparison Calendar", ["Date"])
    rule = DeadAnchorCalendarRule()
    rule.options["template"] = str(template)
    found = rule.check(Context(root))
    assert found == []


def test_r016_template_folder_that_does_not_exist(tmp_path):
    root = tmp_path
    client = _model(root, "Client.SemanticModel")
    _table(client / "tables", "__Comparison Calendar", ["Date"])
    _rels(client, "")
    rule = DeadAnchorCalendarRule()
    rule.options["template"] = str(root / "nope")
    found = rule.check(Context(root))
    assert len(found) == 1
    assert "__Comparison Calendar" in found[0].message


# ---------------------------------------------------------------------------
# RL-3: R016 per-model ratchet floor
# ---------------------------------------------------------------------------


def test_r016_floor_accepts_a_known_dead_calendar(tmp_path, tmp_path_factory):
    root = tmp_path
    client = _model(root, "Client.SemanticModel")
    _table(client / "tables", "__A Calendar", ["Date"])
    _table(client / "tables", "__B Calendar", ["Date"])
    _rels(client, "")
    floor = tmp_path_factory.mktemp("floor") / "dead.json"
    floor.write_text(json.dumps({"Client": ["__A Calendar"]}), encoding="utf-8")
    rule = DeadAnchorCalendarRule()
    rule.options["floor"] = str(floor)
    ctx = Context(root)
    found = rule.check(ctx)
    assert len(found) == 1
    assert "__B Calendar" in found[0].message
    assert "__A Calendar" not in found[0].message


def test_r016_floor_note_when_a_calendar_reaches_something(tmp_path, tmp_path_factory):
    root = tmp_path
    client = _model(root, "Client.SemanticModel")
    _table(client / "tables", "__A Calendar", ["Date"])
    _table(client / "tables", "Orders", ["id"])
    _rels(client,
          "relationship 11111111-1111-4333-8444-555555555555\n"
          "\tfromColumn: Orders.id\n\ttoColumn: __A Calendar.Date\n")
    floor = tmp_path_factory.mktemp("floor") / "dead.json"
    floor.write_text(json.dumps({"Client": ["__A Calendar"]}), encoding="utf-8")
    rule = DeadAnchorCalendarRule()
    rule.options["floor"] = str(floor)
    ctx = Context(root)
    found = rule.check(ctx)
    assert found == []
    assert any("now reach something" in note for note in ctx.notes)


# ---------------------------------------------------------------------------
# RL-4 to RL-8: R008 groups the offenders per model
# ---------------------------------------------------------------------------


def _account_model(tmp_path: Path, name: str = "Shop.SemanticModel") -> Path:
    d = _model(tmp_path, name)
    _table(d / "tables", "_Accounts", ["account_x_id"])
    _table(d / "tables", "Bookings", ["booking_id", "account_x_id"])
    _table(d / "tables", "Orders", ["order_id"])
    _table(d / "tables", "Sitemap", ["page_id"])
    _table(d / "tables", "Ledger", ["entry_id", "account_x_id"])
    _table(d / "tables", "Reports", ["report_id", "Account_X_ID"])
    _rels(d,
          "relationship 11111111-1111-4333-8444-555555555555\n"
          "\tfromColumn: Bookings.account_x_id\n\ttoColumn: _Accounts.account_x_id\n")
    return d


def _r008(config: dict) -> dict:
    return {"rules": {"R008": config}}


def test_r008_template_fact_split(tmp_path):
    root = tmp_path
    d = _account_model(root)
    code, payload = run_check(d.parent, "R008", config=_r008({
        "dimension_table": "_Accounts",
        "key_column": "account_x_id",
        "template_facts": ["Orders"],
    }))
    found = violations(payload, "R008")
    assert len(found) == 1
    message = found[0]["message"]
    assert "CRITICAL — template fact tables (core-model defect)" in message
    assert "model-specific fact tables" in message
    assert "    - Orders" in message
    assert "    - Sitemap" in message


def test_r008_one_finding_per_model(tmp_path):
    root = tmp_path
    d = _account_model(root)
    code, payload = run_check(d.parent, "R008", config=_r008({
        "dimension_table": "_Accounts",
        "key_column": "account_x_id",
    }))
    found = violations(payload, "R008")
    assert len(found) == 1
    message = found[0]["message"]
    assert message.startswith("NEW account-key offender(s) in 'Shop.SemanticModel' — ")
    assert "Fact tables missing 'account_x_id' — they cannot be account-filtered:" in message
    assert "Fact tables that carry 'account_x_id' but have NO active relationship to " \
           "_Accounts[account_x_id] — the account filter would resolve but return " \
           "UNFILTERED data; create the active relationship (your relationship tooling):" \
           in message
    # the two sections come in that order
    assert message.index("Fact tables missing") < message.index("Fact tables that carry")
    assert "    - Ledger" in message
    assert "    - Orders" in message
    assert "    - Sitemap" in message


def test_r008_key_column_is_case_sensitive(tmp_path):
    root = tmp_path
    d = _account_model(root)
    code, payload = run_check(d.parent, "R008", config=_r008({
        "dimension_table": "_Accounts",
        "key_column": "account_x_id",
    }))
    found = violations(payload, "R008")
    assert len(found) == 1
    message = found[0]["message"]
    # Reports carries Account_X_ID, not account_x_id: it is a missing key column
    assert "    - Reports" in message
    assert message.index("    - Reports") < message.index("Fact tables that carry")


def test_r008_model_without_a_floor_entry_fails(tmp_path):
    root = tmp_path
    d = _account_model(root)
    floor = root / "floor.json"
    floor.write_text("{}", encoding="utf-8")
    code, payload = run_check(d.parent, "R008", config=_r008({
        "dimension_table": "_Accounts",
        "key_column": "account_x_id",
        "baseline": str(floor),
    }))
    found = violations(payload, "R008")
    assert len(found) == 1
    assert "no account-key floor recorded for 'Shop.SemanticModel'" in found[0]["message"]
    assert "Record it deliberately" in found[0]["message"]


def test_r008_known_backlog_does_not_fail(tmp_path):
    root = tmp_path
    d = _account_model(root)
    floor = root / "floor.json"
    floor.write_text(json.dumps({"Shop": ["Sitemap", "Ledger", "Orders", "Reports"]}),
                     encoding="utf-8")
    code, payload = run_check(d.parent, "R008", config=_r008({
        "dimension_table": "_Accounts",
        "key_column": "account_x_id",
        "baseline": str(floor),
    }))
    assert code == 0
    assert violations(payload, "R008") == []


# ---------------------------------------------------------------------------
# RL-6: R008 floor capture writer
# ---------------------------------------------------------------------------


def test_r008_capture_writes_the_floor(tmp_path):
    root = tmp_path
    d = _account_model(root)
    floor = root / "floor.json"
    cfg = root / "cfg.json"
    cfg.write_text(json.dumps(_r008({
        "dimension_table": "_Accounts",
        "key_column": "account_x_id",
    })), encoding="utf-8")
    code, _out, _err = run_cli(
        "check", str(d.parent), "--select", "R008",
        "--capture-floor", str(floor), "--config", str(cfg),
    )
    assert code == 0
    assert json.loads(floor.read_text(encoding="utf-8")) == {
        "Shop.SemanticModel": ["Ledger", "Orders", "Reports", "Sitemap"]
    }
    expected = json.dumps(
        {"Shop.SemanticModel": ["Ledger", "Orders", "Reports", "Sitemap"]}, indent=1) + "\n"
    assert floor.read_text(encoding="utf-8") == expected
    before = floor.read_bytes()
    run_cli("check", str(d.parent), "--select", "R008",
            "--capture-floor", str(floor), "--config", str(cfg))
    assert floor.read_bytes() == before


def test_r016_capture_writes_the_floor(tmp_path):
    root = tmp_path
    client = _model(root, "Client.SemanticModel")
    _table(client / "tables", "__A Calendar", ["Date"])
    _table(client / "tables", "__B Calendar", ["Date"])
    _rels(client, "")
    floor = root / "floor.json"
    cfg = root / "cfg.json"
    cfg.write_text(json.dumps({"rules": {"R016": {}}}), encoding="utf-8")
    code, _out, _err = run_cli(
        "check", str(root), "--select", "R016", "--capture-floor", str(floor),
        "--config", str(cfg),
    )
    assert code == 0
    text = floor.read_text(encoding="utf-8")
    assert json.loads(text) == {"Client.SemanticModel": ["__A Calendar", "__B Calendar"]}
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert '  "Client.SemanticModel"' in text


def test_r016_capture_message(tmp_path, capsys):
    root = tmp_path
    client = _model(root, "Client.SemanticModel")
    _table(client / "tables", "__A Calendar", ["Date"])
    _rels(client, "")
    floor = root / "floor.json"
    cfg = root / "cfg.json"
    cfg.write_text(json.dumps({"rules": {"R016": {}}}), encoding="utf-8")
    code, out, _err = run_cli(
        "check", str(root), "--select", "R016", "--capture-floor", str(floor),
        "--config", str(cfg),
    )
    assert code == 0
    assert "[dead-anchor-calendar floor] captured 1 across 1 models" in out


def test_r007_fixer_console_lines(tmp_path):
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
          "\ttoColumn: Stores.id\n")
    code, out, _err = run_cli("fix", d.parent, "--select", "R007", "--no-config")
    assert code == 0
    assert "Found 1 autodetected relationships:" in out
    assert "   - AutoDetected_22222222-2222-4333-8444-555555555555" in out
    assert "Deleted 1 autodetected relationships" in out
    text = (d / "relationships.tmdl").read_text(encoding="utf-8")
    assert text.endswith("toColumn: Stores.id\n\n")


def test_r007_dry_run_console_lines(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d,
          "relationship AutoDetected_22222222-2222-4333-8444-555555555555\n"
          "\tfromColumn: Orders.id\n"
          "\ttoColumn: Stores.id\n")
    before = (d / "relationships.tmdl").read_text(encoding="utf-8")
    code, out, _err = run_cli("fix", d.parent, "--select", "R007", "--dry-run",
                              "--no-config")
    assert code == 1  # the violation is still there: nothing was repaired
    assert "Would delete 1 autodetected relationships (strict policy)" in out
    assert (d / "relationships.tmdl").read_text(encoding="utf-8") == before


def test_r007_fixer_with_nothing_to_remove(tmp_path):
    d = _model(tmp_path)
    _table(d / "tables", "Orders", ["id"])
    _table(d / "tables", "Stores", ["id"])
    _rels(d,
          "relationship 11111111-2222-4333-8444-555555555555\n"
          "\tfromColumn: Orders.id\n"
          "\ttoColumn: Stores.id\n")
    code, out, _err = run_cli("fix", d.parent, "--select", "R007", "--no-config")
    assert code == 0
    assert "No autodetected relationships found" in out
