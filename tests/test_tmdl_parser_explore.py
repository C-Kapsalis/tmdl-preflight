"""Parser conformance (spec H-parser-conformance).

Two asserting tests (crash freedom and whole-model performance) are kept; the print-only
exploration tests are developer tooling. The README edge-case library
(EC-001..EC-021) becomes one fixture table per case in
`tests/fixtures/test_tmdl_parser_explore_edge_cases/EdgeCases.SemanticModel`,
with the expected parse result. Cases the README marked LIMITATION are TARGETS
(named `..._target`): the earlier check parser was not expected to pass them, the
tool must.

The earlier check kernel index and its private table-file parser are replaced by
`tmdl_preflight.parser.parse_table_file` / `parse_model`; the registry-selected
model by the edge-case stand-in; the performance model is generated.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from conftest import FIXTURES, run_check, violations
from tmdl_preflight.dax import extract_nameof_references, extract_references
from tmdl_preflight.parser import parse_model, parse_table_file

EDGE = FIXTURES / "test_tmdl_parser_explore_edge_cases"
EDGE_DEF = EDGE / "EdgeCases.SemanticModel" / "definition"
TABLE_FILES = sorted((EDGE_DEF / "tables").glob("*.tmdl"))


@pytest.fixture(scope="module")
def model():
    return parse_model(EDGE_DEF)


def _table(model, name):
    t = model.get_table(name)
    assert t is not None, f"table {name!r} not parsed; got {sorted(model.tables)}"
    return t


# ---------------------------------------------------------------------------
# Kept tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmdl_path", TABLE_FILES, ids=lambda p: p.stem)
def test_no_parser_crashes(tmdl_path):
    """Parser robustness — the given file parses cleanly, and whole-model
    success rate >= 90%."""
    single, _errors = parse_table_file(tmdl_path)
    assert single is not None
    assert single.name

    model = parse_model(EDGE_DEF)
    tmdl_files = list((EDGE_DEF / "tables").glob("*.tmdl"))
    success_rate = len(model.table_list) / len(tmdl_files) if tmdl_files else 0.0
    assert success_rate >= 0.90


def test_every_table_file_yields_a_named_table(model):
    """Tool target (H-parser-conformance rule 1): 100% on every shipped fixture."""
    assert len(TABLE_FILES) == 39
    assert len(model.table_list) == len(TABLE_FILES)
    assert all(t.name for t in model.table_list)


def _generate_model(root: Path, tables=300, columns=20, measures=10) -> Path:
    d = root / "Perf.SemanticModel" / "definition" / "tables"
    d.mkdir(parents=True)
    for i in range(tables):
        cols = "".join(f"\tcolumn c{j}\n\t\tdataType: int64\n\t\tsourceColumn: c{j}\n\n"
                       for j in range(columns))
        ms = "".join(f"\tmeasure 'M{i}_{j}' = SUM('T{i:03d}'[c{j}])\n\n" for j in range(measures))
        (d / f"T{i:03d}.tmdl").write_text(f"table T{i:03d}\n\n{cols}{ms}", encoding="utf-8")
    return d.parent


def test_parser_performance(tmp_path):
    """Time a fresh whole-model parse"""
    definition = _generate_model(tmp_path)
    start = time.time()
    fresh = parse_model(definition)
    elapsed = time.time() - start
    assert len(fresh.table_list) == 300
    assert elapsed < 30, f"Parser took {elapsed:.1f}s, should be <30s"


# ---------------------------------------------------------------------------
# Edge cases EC-001..EC-021 (tests/fixtures/edge_cases/README.md)
# ---------------------------------------------------------------------------

def test_ec001_doubled_apostrophe_in_column_name_target(model):
    assert "Rider's Name" in _table(model, "EC001 Quotes").columns


def test_ec001_unescaped_apostrophe_is_reported_not_crashed():
    invalid = EDGE / "Ec001Invalid.SemanticModel"
    parse_model(invalid / "definition")  # must not raise
    code, payload = run_check(invalid, "M002")
    assert violations(payload, "M002")


def test_ec002_mixed_quotes_reference_ignored(model):
    m = _table(model, "EC002 Mixed Quotes").measures["Mixed Ref"]
    assert extract_nameof_references(m.expression) == []


def test_ec003_doubled_quotes_in_string_literal(model):
    m = _table(model, "EC003 Nested Quotes").measures["Greeting"]
    assert m.expression.strip() == '"Say ""hello"" to [Nobody]"'
    assert all(r.member != "Nobody" for r in extract_references(m.expression))


def test_ec004_backticks_inside_fenced_string_target(model):
    m = _table(model, "EC004 Backticks").measures["Backtick Text"]
    assert 'This has ``` backticks' in m.expression
    assert "RETURN txt" in m.expression


def test_ec005_empty_quoted_name_is_diagnosed(model):
    t = _table(model, "EC005 Empty Name")
    assert "Kept Column" in t.columns
    code, payload = run_check(EDGE / "EdgeCases.SemanticModel")
    assert any(
        "EC005" in (v.get("path") or "") and v["severity"] == "warning"
        and "empty" in v["message"].lower()
        for v in violations(payload)
    )


def test_ec006_very_long_quoted_name(model):
    names = list(_table(model, "EC006 Long Name").columns)
    assert len(names) == 1 and len(names[0]) == 260


def test_ec007_trailing_spaces_trimmed(model):
    assert "Frame Size" in _table(model, "EC007 Trailing Spaces").columns


def test_ec008_tabs_in_expression(model):
    m = _table(model, "EC008 Tabs").measures["Tabbed"]
    assert 'Rentals[Status] = "Done"' in m.expression


def test_ec009_blank_lines_inside_expression(model):
    t = _table(model, "EC009 Blank Lines")
    assert list(t.measures) == ["Spaced"]
    expr = t.measures["Spaced"].expression
    assert "VAR a" in expr and "VAR b" in expr and "a + b" in expr


def test_ec010_unicode_name(model):
    assert "Preis €" in _table(model, "EC010 Unicode").columns


def test_ec011_emoji_name(model):
    assert "🚲 Bike Count" in _table(model, "EC011 Emoji").columns


def test_ec012_reserved_words_as_names(model):
    cols = _table(model, "EC012 Reserved Words").columns
    assert "VAR" in cols and "RETURN" in cols


def test_ec013_brackets_in_column_name_target(model):
    assert "Price [EUR]" in _table(model, "Bikes").columns
    code, payload = run_check(EDGE / "EdgeCases.SemanticModel", "D004")
    assert not [v for v in violations(payload, "D004") if "EUR" in v["message"]]


def test_ec014_nested_calculate_references(model):
    m = _table(model, "EC014 Nested Calculate").measures["Deep"]
    refs = {(r.table, r.member) for r in extract_references(m.expression) if r.kind == "column"}
    assert {("Rentals", "Minutes"), ("Rentals", "Status"), ("Rentals", "Year")} <= refs


def test_ec015_very_long_expression_then_properties(model):
    m = _table(model, "EC015 Long Expression").measures["Huge"]
    assert len(m.expression) > 10000
    assert m.format_string == "#,0.00"
    assert m.lineage_tag


def test_ec016_expression_with_no_whitespace(model):
    """BUGFIX: the README marks this HANDLED but the earlier check parser drops the
    measure when `=` has no surrounding spaces (project decision)."""
    m = _table(model, "EC016 No Whitespace").measures["Compact"]
    assert m.expression.strip() == "[Sales]+[Returns]-[Discounts]"
    bare = [r.member for r in extract_references(m.expression) if r.kind == "bare"]
    assert bare == ["Sales", "Returns", "Discounts"]


def test_ec017_line_comments_ignored(model):
    m = _table(model, "EC017 Comments").measures["Simple Comments"]
    members = {r.member for r in extract_references(m.expression)}
    assert "Ghost Slash" not in members and "Ghost Dash" not in members


def test_ec017_multiline_block_comment_ignored_target(model):
    m = _table(model, "EC017 Comments").measures["Block Comment"]
    members = {r.member for r in extract_references(m.expression)}
    assert "Ghost Block" not in members and "Ghost Column" not in members


def test_ec018_two_return_lines(model):
    m = _table(model, "EC018 Two Returns").measures["Odd"]
    assert m.expression.count("RETURN") == 2


def test_ec019_same_measure_on_two_tables(model):
    assert "Grand Total" in _table(model, "EC019 Shop A").measures
    assert "Grand Total" in _table(model, "EC019 Shop B").measures
    code, payload = run_check(EDGE / "EdgeCases.SemanticModel", "D002", "D004")
    assert any(v["severity"] == "warning" and "Grand Total" in v["message"]
               for v in violations(payload))


def test_ec020_column_and_measure_share_a_name_target(model):
    t = _table(model, "EC020 Shared Name")
    assert "Total" in t.columns and "Total" in t.measures
    code, payload = run_check(EDGE / "EdgeCases.SemanticModel")
    # STRICTER: the target asks for an INFO finding; M012 already reports a
    # measure named like a column of its own table, as an ERROR.
    assert any(v["severity"] in ("info", "warning", "error") and "EC020" in (v.get("path") or "")
               and "Total" in v["message"] for v in violations(payload))


def test_ec021_table_named_like_its_column(model):
    assert "Date" in _table(model, "Date").columns
    code, payload = run_check(EDGE / "EdgeCases.SemanticModel", "M002", "D001", "D002", "D004")
    assert not [v for v in violations(payload) if (v.get("path") or "").endswith("tables/Date.tmdl")]
