"""Spec cases for the organisation rules beyond the ported tests: the
lenient placement profile, field-parameter surfacing on facts, F005 and the
ratchet hints."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_check, violations

TAG = "1a2b3c4d-0000-4000-8000-{:012d}"


def _table(name: str, measures: list[str], n: int, extra: str = "", partition: str = "calculated") -> str:
    body = f"table '{name}'\n\tlineageTag: {TAG.format(n)}\n\n"
    for k, m in enumerate(measures):
        body += f"\tmeasure '{m}' = 1\n\t\tlineageTag: {TAG.format(n * 100 + k)}\n\n"
    body += extra
    if partition == "m":
        body += (f"\tcolumn id\n\t\tdataType: int64\n\t\tlineageTag: {TAG.format(n * 100 + 99)}\n"
                 f"\t\tsourceColumn: id\n\n\tpartition '{name}' = m\n\t\tmode: import\n"
                 f"\t\tsource = Sql.Database(\"srv\", \"db\")\n")
    else:
        body += f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource = ROW(\"x\", 1)\n"
    return body


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    d = tmp_path / "Shop.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    for name, text in tables.items():
        (d / "tables" / f"{name}.tmdl").write_text(text, encoding="utf-8")
    return d.parent


def test_lenient_profile_judges_four_kinds_as_info(tmp_path):
    model = _model(tmp_path, {
        "Sales": _table("Sales", ["f-Espresso", "-helper Base", "_tmp", "-Visual Label", "i-Rows",
                                  "-Base Cups", "Cohort Test 2", "Total Revenue"], 1, partition="m"),
        "Helper Measures": _table("Helper Measures", ["-helper Ok"], 2),
        "#Shop KPIs": _table("#Shop KPIs", ["-helper X"], 3),
    })
    cfg = {"rules": {"helper-measure-placement": {"profile": "lenient"}}}
    code, payload = run_check(model, "helper-measure-placement", config=cfg, strict=True)
    found = violations(payload)
    assert code == 0 and {v["severity"] for v in found} == {"info"}
    names = sorted(v["object"] for v in found)
    assert names == ["#Shop KPIs[-helper X]", "Sales[-Visual Label]", "Sales[-helper Base]",
                     "Sales[f-Espresso]", "Sales[i-Rows]"]
    strict = violations(run_check(model, "helper-measure-placement", strict=True)[1])
    assert "Sales[_tmp]" in {v["object"] for v in strict}
    assert "Sales[Cohort Test 2]" in {v["object"] for v in strict}


def test_surfaced_hidden_measure_on_a_fact_is_blocking(tmp_path):
    """A measure surfaced by a NUMBERED x-axis table is user-facing."""
    sales = _table("Sales", ["Total Revenue"], 1, partition="m").replace(
        "\tmeasure 'Total Revenue' = 1\n", "\tmeasure 'Total Revenue' = 1\n\t\tisHidden\n")
    picker = ("table 'x-Selector 1'\n\tlineageTag: " + TAG.format(9) + "\n\n"
              "\tpartition 'x-Selector 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
              "\t\t\t\t{ (\"Revenue\", NAMEOF([Total Revenue]), 0) }\n")
    model = _model(tmp_path, {"Sales": sales, "x-Selector 1": picker})
    code, payload = run_check(model, "measures-in-fact-tables", strict=True)
    blocking = [v for v in violations(payload) if v["severity"] != "info"]
    assert code == 1 and len(blocking) == 1 and "field parameter" in blocking[0]["message"]


def test_a_measure_surfaced_only_by_a_plot_specific_table_is_advisory(tmp_path):
    """PA21: the default surfacing set is the numbered x-axis tables only."""
    sales = _table("Sales", ["Total Revenue"], 1, partition="m").replace(
        "\tmeasure 'Total Revenue' = 1\n", "\tmeasure 'Total Revenue' = 1\n\t\tisHidden\n")
    picker = ("table 'x-Plot Specific 1'\n\tlineageTag: " + TAG.format(9) + "\n\n"
              "\tpartition 'x-Plot Specific 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
              "\t\t\t\t{ (\"Revenue\", NAMEOF([Total Revenue]), 0) }\n")
    model = _model(tmp_path, {"Sales": sales, "x-Plot Specific 1": picker})
    code, payload = run_check(model, "measures-in-fact-tables", strict=True)
    found = violations(payload)
    assert code == 0, found
    assert found and all(v["severity"] == "info" for v in found), found


def test_the_surfacing_tables_option_is_an_override(tmp_path):
    """PA21: the option keeps working as an override."""
    sales = _table("Sales", ["Total Revenue"], 1, partition="m").replace(
        "\tmeasure 'Total Revenue' = 1\n", "\tmeasure 'Total Revenue' = 1\n\t\tisHidden\n")
    picker = ("table 'x-Plot Specific 1'\n\tlineageTag: " + TAG.format(9) + "\n\n"
              "\tpartition 'x-Plot Specific 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
              "\t\t\t\t{ (\"Revenue\", NAMEOF([Total Revenue]), 0) }\n")
    model = _model(tmp_path, {"Sales": sales, "x-Plot Specific 1": picker})
    cfg = {"rules": {"measures-in-fact-tables": {
        "surfacing_tables": ["x-Plot Specific *"]}}}
    code, payload = run_check(model, "measures-in-fact-tables", config=cfg,
                               strict=True)
    blocking = [v for v in violations(payload) if v["severity"] != "info"]
    assert code == 1 and len(blocking) == 1, blocking


def test_category_column_needs_fenced_source_and_twin(tmp_path):
    picker = ("table 'x-Plot Specific 1'\n\tlineageTag: " + TAG.format(9) + "\n\n"
              "\tpartition 'x-Plot Specific 1' = calculated\n\t\tmode: import\n\t\tsource = ```\n"
              "\t\t\t\t{ (\"Revenue\", NAMEOF([Revenue]), 0, \"Sales_x\"),\n"
              "\t\t\t\t  (\"Bags\", NAMEOF([Bags]), 1) }\n\t\t\t\t```\n")
    model = _model(tmp_path, {"x-Plot Specific 1": picker})
    cfg = {"rules": {"fieldparam-category-column": {"category_column_tables": ["x-Plot Specific *"]}}}
    found = violations(run_check(model, "F005", config=cfg)[1])
    assert len(found) == 1 and "Bags" in found[0]["message"]
    f = model / "definition" / "tables" / "x-Plot Specific 1.tmdl"
    f.write_text(f.read_text(encoding="utf-8").replace("source = ```", "source =").replace(
        "\t\t\t\t```\n", ""), encoding="utf-8")
    assert violations(run_check(model, "F005", config=cfg)[1]) == []
    assert violations(run_check(model, "F005")[1]) == []  # inert until configured


def test_conformed_join_tighten_hint(tmp_path):
    accounts = _table("_Accounts", [], 1, partition="m").replace("column id", "column account_x_id")
    orders = _table("Orders", [], 2, partition="m")
    model = _model(tmp_path, {"_Accounts": accounts, "Orders": orders})
    (model / "definition" / "relationships.tmdl").write_text(
        "relationship r1\n\tfromColumn: Orders.id\n\ttoColumn: _Accounts.account_x_id\n", encoding="utf-8")
    base = tmp_path / "floors.json"
    base.write_text(json.dumps({"Shop.SemanticModel": ["Orders"]}), encoding="utf-8")
    cfg = {"rules": {"fact-conformed-dimension-join": {
        "dimension_table": "_Accounts", "key_column": "account_x_id", "baseline": str(base)}}}
    code, payload = run_check(model, "R008", config=cfg)
    assert code == 0 and violations(payload) == []
    assert any("tighten" in n for n in payload["notes"])
