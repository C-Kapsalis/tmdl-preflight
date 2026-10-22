"""Field-parameter (x-/y-Selector) tuple-arity integrity (spec A-fieldparam-arity).

A field parameter is a calculated table whose partition source is a list of
tuples; EVERY tuple must have the same width as the table's declared column
count (Value1..ValueN). A ragged list (a short row merged in, or a custom
column stripped while its per-row value lingers) stops the calculated table
compiling: Power BI reports `MdxScript(Model) ... 'SYNTAXERROR'` and every
visual bound to that field parameter breaks.

Mapping: mixed widths in one table -> F004 (fieldparam-ragged-rows); one
uniform width that differs from the declared ValueN count -> the new rule
`fieldparam-arity`. Commas inside quoted labels are not separators.

Stand-in (tests/fixtures/b3-a2/fieldparam_arity/roastery, model ar_db/Roastery):
- ``x-Selector 1``: 6 declared columns, every row 6 wide -> pass
- ``x-Selector 2``: one 5-wide row among 6-wide rows -> ragged (fail)
- ``y-Selector 1``: every row 7 wide, Value1..Value6 declared -> mismatch (fail)
- ``y-Selector 2``: a label containing a comma inside quotes -> pass
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

TABLES = [
    pytest.param("x-Selector 1", "pass", id="x-Selector 1.tmdl"),
    pytest.param("x-Selector 2", "fail", id="x-Selector 2.tmdl"),
    pytest.param("y-Selector 1", "fail", id="y-Selector 1.tmdl"),
    pytest.param("y-Selector 2", "pass", id="y-Selector 2.tmdl"),
]


@pytest.mark.parametrize("table,verdict", TABLES)
def test_fieldparam_tuple_arity_uniform(stand_in, table, verdict):
    root = stand_in("b3-a2/fieldparam_arity/roastery")
    _code, payload = run_check(root, "F004", "fieldparam-arity")
    assert "summary" in payload, payload
    mine = [v for v in violations(payload)
            if (v.get("file") or "").replace("\\", "/").endswith(f"tables/{table}.tmdl")]
    if verdict == "pass":
        assert mine == [], mine
        return
    assert mine
    for v in mine:
        assert v["severity"] == "error" or v["rule"] == "F004"
    if table == "x-Selector 2":
        assert any(v["rule"] == "F004" for v in mine)        # counts vary
    if table == "y-Selector 1":
        assert any(v["rule"] != "F004" and "7" in v["message"] and "6" in v["message"]
                   for v in mine)                             # 7 fields vs 6 declared


def test_arity_message_names_the_width_and_the_columns(stand_in):
    root = stand_in("b3-a2/fieldparam_arity/roastery")
    _code, payload = run_check(root, "fieldparam-arity")
    mine = [v for v in violations(payload)
            if (v.get("file") or "").replace("\\", "/").endswith("tables/y-Selector 1.tmdl")]
    assert len(mine) == 1, mine
    assert mine[0]["message"] == (
        "field-parameter tuples carry 7 field(s) but the table declares 6 column(s) "
        "(Value1..Value6) — mismatch breaks compilation.")


UNFENCED = """table 'x-Selector 1'
\tcolumn 'x-Selector 1'
\t\tsourceColumn: [Value1]

\tcolumn 'x-Selector 1 Fields'
\t\tsourceColumn: [Value2]

\tcolumn 'x-Selector 1 Order'
\t\tsourceColumn: [Value3]

\tcolumn 'x-Selector 1 Field Category'
\t\tsourceColumn: [Value4]

\tpartition 'x-Selector 1' = calculated
\t\tmode: import
\t\tsource =
\t\t\t\t{
\t\t\t\t\t("Cups Sold", NAMEOF([Cups Sold]), 1, "beans_x", "Other")
\t\t\t\t}
"""


def test_arity_reads_a_source_that_is_not_fenced(tmp_path):
    """Desktop writes some sources without the fence; the rows still count."""
    tables = tmp_path / "Roastery.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "x-Selector 1.tmdl").write_text(UNFENCED, encoding="utf-8")
    _code, payload = run_check(tmp_path / "Roastery.SemanticModel", "fieldparam-arity")
    found = violations(payload)
    assert len(found) == 1, found
    assert found[0]["message"] == (
        "field-parameter tuples carry 5 field(s) but the table declares 4 column(s) "
        "(Value1..Value4) — mismatch breaks compilation.")

