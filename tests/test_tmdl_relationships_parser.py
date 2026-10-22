"""The relationships parser must see every declared relationship.

Ported from the layer-1 suite. Regression pins:
* a file whose line 1 is ``relationship <id>`` (every real model) must not lose
  that first relationship inside a skipped "preamble";
* a quoted table name with an escaped quote (``'Cohort ''Since'' Interval'``) and
  a quoted column name with spaces must parse in full;
* on every model, parsed count == declared ``relationship`` lines.

Kernel parser / index -> ``tmdl_preflight.parser.parse_relationships`` and
``parse_model``; model discovery -> the stand-in models.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tmdl_preflight.parser import parse_model, parse_relationships

pytestmark = [pytest.mark.p0]

FIRST_LINE_CONTENT = """relationship first-guid-0001
\tfromColumn: Ads.ad_x_id
\ttoColumn: _Ads.ad_x_id

relationship second-guid-0002
\tisActive: false
\tfromColumn: 'Queries Paid'.date
\ttoColumn: __Calendar.Date
"""


def _rels(folder: Path):
    return parse_relationships(folder / "relationships.tmdl")[0]


def test_first_line_relationship_is_parsed(tmp_path):
    (tmp_path / "relationships.tmdl").write_text(FIRST_LINE_CONTENT, encoding="utf-8")
    rels = _rels(tmp_path)
    assert len(rels) == 2, (
        "parse_relationships dropped a relationship — the first-line blindspot is "
        f"back (got {len(rels)}: {[r.rel_id for r in rels]})"
    )
    first, second = rels
    assert first.rel_id == "first-guid-0001"
    assert (first.from_table, first.from_column) == ("Ads", "ad_x_id")
    assert (first.to_table, first.to_column) == ("_Ads", "ad_x_id")
    assert first.is_active is True
    assert second.rel_id == "second-guid-0002"
    assert second.is_active is False


def test_preamble_before_first_relationship_still_skipped(tmp_path):
    (tmp_path / "relationships.tmdl").write_text(
        "// preamble comment\n\n" + FIRST_LINE_CONTENT, encoding="utf-8"
    )
    assert [r.rel_id for r in _rels(tmp_path)] == ["first-guid-0001", "second-guid-0002"]


def test_missing_relationships_file_returns_empty(tmp_path):
    assert _rels(tmp_path) == []


ESCAPED_QUOTE_CONTENT = """relationship guid-escaped-table-0001
\tfromColumn: 'Cohort ''Since'' Interval'.Value4
\ttoColumn: 'z-Selector Cohort Timeframe'.Column1

relationship guid-quoted-column-0002
\tfromColumn: 'z-Selector Spend Report Level'.'z-Spend Report Level'
\ttoColumn: 'z-Spend Report Level'.'Report Level Key'

relationship guid-plain-0003
\tisActive: false
\tfromColumn: Ads.ad_x_id
\ttoColumn: _Ads.ad_x_id
"""


def test_index_parses_escaped_quote_tables_and_quoted_columns(tmp_path):
    (tmp_path / "tables").mkdir()
    (tmp_path / "relationships.tmdl").write_text(ESCAPED_QUOTE_CONTENT, encoding="utf-8")
    rels = parse_model(tmp_path).relationships

    assert [r.rel_id for r in rels] == [
        "guid-escaped-table-0001", "guid-quoted-column-0002", "guid-plain-0003",
    ], f"model loader dropped a declared relationship: {[r.rel_id for r in rels]}"

    escaped, quoted, plain = rels
    assert (escaped.from_table, escaped.from_column) == ("Cohort 'Since' Interval", "Value4")
    assert (escaped.to_table, escaped.to_column) == ("z-Selector Cohort Timeframe", "Column1")
    assert (quoted.from_table, quoted.from_column) == (
        "z-Selector Spend Report Level", "z-Spend Report Level")
    assert (quoted.to_table, quoted.to_column) == ("z-Spend Report Level", "Report Level Key")
    assert (plain.from_table, plain.from_column, plain.is_active) == ("Ads", "ad_x_id", False)


FIXTURES = Path(__file__).parent / "fixtures"
MODELS = sorted(
    p.relative_to(FIXTURES).as_posix()
    for p in (FIXTURES / "relationships_standins").glob("*/Model.SemanticModel/definition")
) + ["xyselector_axis_standins/template/Performance.SemanticModel/definition"]


@pytest.mark.parametrize("rel_path", MODELS)
def test_index_relationship_count_matches_declarations(rel_path):
    definition = FIXTURES / rel_path
    rel_file = definition / "relationships.tmdl"
    if not rel_file.exists():
        pytest.skip("model has no relationships.tmdl")
    declared = len(re.findall(r"^relationship\s", rel_file.read_text(encoding="utf-8"), re.M))
    parsed = len(parse_model(definition).relationships)
    assert parsed == declared, (
        f"the model loader sees {parsed} of {declared} declared relationships — a "
        "false zero: every relationship rule built on it under-reports."
    )
