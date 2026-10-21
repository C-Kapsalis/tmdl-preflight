"""Spec cases for the DAX batch beyond the ported tests: NAMEOF shapes and
resolution (E-nameof-resolution 15-28), D001's threshold and empty-model
guard, the reports and the format-resolve command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations
from tmdl_preflight.nameof import NameofResolver, extract, parse_argument
from tmdl_preflight.parser import parse_model

TAG = "2b3c4d5e-0000-4000-8000-{:012d}"


def _shop(tmp_path: Path, rows: list[str], measures: str = "") -> Path:
    d = tmp_path / "Shop.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    (d / "tables" / "Sales.tmdl").write_text(
        f"table Sales\n\tlineageTag: {TAG.format(1)}\n\n"
        f"\tmeasure Units = SUM(Sales[Revenue])\n\t\tlineageTag: {TAG.format(2)}\n\n"
        + measures +
        f"\tcolumn Revenue\n\t\tdataType: double\n\t\tlineageTag: {TAG.format(3)}\n\t\tsourceColumn: Revenue\n\n"
        f"\tpartition Sales = m\n\t\tmode: import\n\t\tsource = #table({{\"Revenue\"}}, {{{{1}}}})\n",
        encoding="utf-8")
    (d / "tables" / "Calendar.tmdl").write_text(
        f"table Calendar\n\tlineageTag: {TAG.format(4)}\n\n"
        f"\tcolumn Month\n\t\tdataType: string\n\t\tlineageTag: {TAG.format(5)}\n\t\tsourceColumn: Month\n\n"
        f"\tpartition Calendar = m\n\t\tmode: import\n\t\tsource = #table({{\"Month\"}}, {{{{1}}}})\n",
        encoding="utf-8")
    (d / "tables" / "Other Measures.tmdl").write_text(
        f"table 'Other Measures'\n\tlineageTag: {TAG.format(6)}\n\n"
        f"\tmeasure 'Margin %' = 1\n\t\tlineageTag: {TAG.format(7)}\n\n"
        f"\tpartition 'Other Measures' = calculated\n\t\tmode: import\n\t\tsource = ROW(\"x\", 1)\n",
        encoding="utf-8")
    body = ",\n".join("\t\t\t\t" + r for r in rows)
    (d / "tables" / "x-Plot Specific 1.tmdl").write_text(
        f"table 'x-Plot Specific 1'\n\tlineageTag: {TAG.format(8)}\n\n"
        f"\tpartition 'x-Plot Specific 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        f"\t\t\t\t{{\n{body}\n\t\t\t\t}}\n",
        encoding="utf-8")
    return d.parent


@pytest.mark.parametrize("row,verdict", [
    ('("Revenue", NAMEOF(\'Sales\'[Revenue]), 1, "g")', "pass"),
    ('("Units", NAMEOF( [Units] ), 2, "g")', "pass"),
    ('("Units", NAMEOF(\'Sales\'[Units]), 3, "g")', "pass"),
    ('("Margin", NAMEOF([Margin]), 4, "g")', "error"),
    ('("Month", NAMEOF(\'Sales\'[Month]), 5, "g")', "error"),
    ('("Margin", NAMEOF(\'Sales\'[Margin %]), 6, "g")', "error"),
    ('("Gone", NAMEOF(\'Shops\'[Units]), 7, "g")', "error"),
    ('-- ("Margin", NAMEOF([Margin]), 4, "g")', "pass"),
    ('("Revenue", NAMEOF(Sales[\'Revenue\']), 8, "g")', "pass"),
    ('("Bad", NAMEOF(Sales Revenue), 9, "g")', "error"),
    ('("Revenue", NAMEOF(\'sales\'[revenue]), 10, "g")', "error"),
])
def test_field_parameter_rows(tmp_path, row, verdict):
    rows = ['("Units", NAMEOF([Units]), 0, "g")', row]
    model = _shop(tmp_path, rows)
    found = [v for v in violations(run_check(model, "D002")[1]) if v["severity"] == "error"]
    if verdict == "pass":
        assert found == []
    else:
        assert len(found) == 1
        msg = found[0]["message"]
        assert "not found" in msg or "casing mismatch" in msg


def test_qualified_measure_in_a_measure_is_a_warning(tmp_path):
    model = _shop(tmp_path, ['("Units", NAMEOF([Units]), 0, "g")'],
                  measures=f"\tmeasure Label = NAMEOF('Sales'[Units])\n\t\tlineageTag: {TAG.format(9)}\n\n")
    found = violations(run_check(model, "D002")[1])
    assert [v["severity"] for v in found] == ["warning"]
    assert "bare form" in found[0]["message"]


def test_excluded_tables_and_double_quoted_and_block_comment(tmp_path):
    model = _shop(tmp_path, ['("Month", NAMEOF(\'Calendar\'[Month]), 0, "g")'],
                  measures=(f"\tmeasure Label = NAMEOF(\"Sales\"[Revenue]) /* NAMEOF([Ghost]) */\n"
                            f"\t\tlineageTag: {TAG.format(9)}\n\n"))
    assert violations(run_check(model, "D002")[1]) == []
    cfg = {"rules": {"D002": {"excluded_tables": ["Calendar"]}}}
    found = violations(run_check(model, "D002", config=cfg)[1])
    assert len(found) == 1 and "excluded" in found[0]["message"]


def test_extraction_record_and_shapes():
    refs = extract("NAMEOF ( 'Ride ''Since'' Bucket' [ Days ] ) & nameof([M]) & NAMEOF(T.x[y])",
                   "Owner", "Host")
    assert [(r.table_name, r.object_name, r.is_measure_ref) for r in refs] == [
        ("Ride 'Since' Bucket", "Days", False), (None, "M", True), ("T.x", "y", False)]
    assert refs[0].full_reference == "Ride 'Since' Bucket[Days]" and refs[0].source_measure == "Owner"
    assert parse_argument("Sales Revenue") is None


def test_dax_success_rate_summary_finding(tmp_path):
    model = _shop(tmp_path, ['("Units", NAMEOF([Units]), 0, "g")'],
                  measures=f"\tmeasure Broken = SUM(Sales[Revenue]\n\t\tlineageTag: {TAG.format(9)}\n\n")
    code, payload = run_check(model, "D001", config={"rules": {"D001": {"min_success_rate": 0.9}}})
    found = violations(payload, "D001")
    assert code == 1 and len(found) == 2  # the expression, plus the summary (2/3 < 90%)
    assert any("parse success rate below threshold" in v["message"] for v in found)
    assert any("are balanced" in n for n in payload["notes"])


def test_measureless_model_fails(tmp_path):
    d = tmp_path / "Empty.SemanticModel" / "definition" / "tables"
    d.mkdir(parents=True)
    (d / "T.tmdl").write_text(f"table T\n\tlineageTag: {TAG.format(1)}\n", encoding="utf-8")
    found = violations(run_check(d.parent.parent, "D001")[1])
    assert [v["severity"] for v in found] == ["error"]
    assert found[0]["message"] == "Empty.SemanticModel: no measures found (suspicious)"


def test_report_complexity_numbers(tmp_path):
    model = _shop(tmp_path, ['("Units", NAMEOF([Units]), 0, "g")'],
                  measures=(f"\tmeasure Mid = \"{'x' * 198}\"\n\t\tlineageTag: {TAG.format(9)}\n\n"
                            f"\tmeasure Big = \"{'y' * 5998}\"\n\t\tlineageTag: {TAG.format(10)}\n\n"))
    code, out, _ = run_cli("report", "complexity", model, "--json")
    data = json.loads(out)
    lengths = sorted(m["length"] for m in data["measures"])
    assert code == 0 and len(lengths) == 4
    buckets = {b["bucket"]: b["count"] for b in data["buckets"]}
    assert buckets["Very Large"] == 1 and data["top"][0]["measure"] == "Big"
    assert data["statistics"]["p50"] == lengths[2]


def test_report_relationships_spec_stand_in(tmp_path):
    d = tmp_path / "Coffee.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True)
    for n in ("Sales", "_Products", "__Calendar", "x-Plot Specific 1", "z-Selector Format", "Old Import"):
        (d / "tables" / f"{n}.tmdl").write_text(f"table '{n}'\n", encoding="utf-8")
    (d / "relationships.tmdl").write_text(
        "relationship a\n\tfromColumn: Sales.product_id\n\ttoColumn: _Products.product_id\n\n"
        "relationship b\n\tcrossFilteringBehavior: bothDirections\n\tfromColumn: Sales.date\n"
        "\ttoColumn: __Calendar.Date\n\n"
        "relationship c\n\tisActive: false\n\tfromColumn: 'Sales'.'shop ''A'' key'\n"
        "\ttoColumn: __Calendar.Date\n", encoding="utf-8")
    code, out, _ = run_cli("report", "relationships", d.parent, "--json")
    data = json.loads(out)
    assert (data["total_relationships"], data["active_relationships"], data["inactive_relationships"]) == (3, 2, 1)
    assert data["cardinality_types"] == {"many_to_one": 3}
    assert data["cross_filtering"]["bidirectional"] == 1
    assert data["orphan_categories"] == {"parameter_tables": ["x-Plot Specific 1"],
                                         "selector_tables": ["z-Selector Format"],
                                         "other_orphans": ["Old Import"]}
    assert data["hub_tables"][0] == {"table": "Sales", "relationship_count": 3}


def test_format_resolve_command(tmp_path):
    d = tmp_path / "Fmt.SemanticModel" / "definition" / "tables"
    d.mkdir(parents=True)
    (d / "z-Selector Format.tmdl").write_text(
        "table 'z-Selector Format'\n\tcalculationGroup\n\t\tcalculationItem F = SELECTEDMEASURE()\n\n"
        "\t\t\tformatStringDefinition =\n"
        "\t\t\t\tSWITCH(TRUE(),\n"
        "\t\t\t\t\tISINSCOPE('x-Selector 1'[x-Selector 1 Field]), \"AXIS\",\n"
        "\t\t\t\t\tCONTAINSSTRING(SELECTEDMEASURENAME(), \"cost\"), \"#,##0\",\n"
        "\t\t\t\t\t\"#,##0.00\")\n", encoding="utf-8")
    code, out, _ = run_cli("format-resolve", d.parent.parent, "--name", "Cost", "--compare",
                           "Clicks", "--json")
    rows = {r["axis"]: r for r in json.loads(out)["results"]}
    assert code == 0 and rows[None]["format"] == "#,##0" and rows["x-Selector 1"]["format"] == "AXIS"
    assert rows[None]["decimals_differ"] is True
