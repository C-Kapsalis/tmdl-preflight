"""The field-parameter partition shape (F015) and the calculated tables'
partition coverage.

The rule is advisory: it never fails a run. It says, per model, how many
axis tables it looked at, what is wrong with the ones that are not the
field parameter the axis visuals expect, and how many of the calculated
tables carry a partition.

Stand-ins (tests/fixtures/partition_shape):
- ``shape_db``: x-Selector 1 is a well-formed field parameter, y-Selector 1
  is a DirectQuery table.
- ``unfenced_db``: x-Selector 1 carries an unfenced source with the tuple
  rows the axis visuals expect.
- ``calc_db``: x-Selector 1 declares an import partition, z-Map Lookups
  declares a partition without a mode.
"""
from __future__ import annotations

from conftest import run_check, violations

STANDIN = "partition_shape"
RULE = "field-parameter-partition-shape"


def _model(stand_in, folder, name):
    return stand_in(STANDIN) / folder / f"{name}.SemanticModel"


def _notes(payload):
    return "\n".join(payload.get("notes", []))


def test_the_finding_says_which_table_and_which_problem(stand_in):
    model = _model(stand_in, "shape_db", "Shape")
    code, payload = run_check(model, RULE)
    assert code == 0  # advisory
    assert [v["message"] for v in violations(payload)] == [
        "y-Selector 1: Partition mode is 'directquery', expected 'import'"]


def test_an_unfenced_source_is_read_too(stand_in):
    model = _model(stand_in, "unfenced_db", "Unfenced")
    code, payload = run_check(model, RULE)
    assert code == 0
    assert violations(payload) == []


def test_a_table_without_a_partition_says_so(stand_in):
    model = _model(stand_in, "shape_db", "Shape")
    table = model / "definition" / "tables" / "x-Selector 1.tmdl"
    text = table.read_text(encoding="utf-8")
    table.write_text(text[:text.index("\tpartition ")], encoding="utf-8")
    code, payload = run_check(model, RULE)
    assert "x-Selector 1: No partition found" in [v["message"] for v in violations(payload)]


def test_the_run_reports_the_partition_pattern_summary(stand_in):
    model = _model(stand_in, "shape_db", "Shape")
    code, payload = run_check(model, RULE)
    notes = _notes(payload)
    assert "📊 Field Parameter Partition Pattern Validation:" in notes
    assert "Tables analyzed: 2" in notes
    assert "Valid partitions: 1" in notes
    assert "Violations: 1" in notes
    assert "⚠️  Partition pattern issues:" in notes
    assert "  - y-Selector 1: Partition mode is 'directquery', expected 'import'" in notes
    assert "Expected pattern: partition = calculated, mode: import, tuple source" in notes


def test_a_clean_model_says_so(stand_in):
    model = _model(stand_in, "unfenced_db", "Unfenced")
    code, payload = run_check(model, RULE)
    notes = _notes(payload)
    assert "✓ All field parameter tables follow standard partition pattern" in notes


def test_the_run_reports_the_calculated_table_coverage(stand_in):
    model = _model(stand_in, "calc_db", "Calc")
    code, payload = run_check(model, RULE)
    notes = _notes(payload)
    assert "📊 Calculated Table Partition Coverage:" in notes
    assert "Total calculated tables: 2" in notes
    assert "With partitions: 2 (100.0%)" in notes
    assert "Without partitions: 0" in notes
    assert "Partition modes:" in notes
    assert "  - import: 1" in notes
    assert "  - unknown: 1" in notes
    assert "✓ All calculated tables have partition definitions" in notes
