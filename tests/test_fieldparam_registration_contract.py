"""The field-parameter registration contracts: a registered column needs an
ordinal, and a group row is a live line that names the group and carries an
ordinal (spec A-fieldparam-registration-contract).

The fixture is a fictional field-parameter table with a group of rows, each
carrying a label, a NAMEOF reference and an ordinal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check

TAG = "3c4d5e6f-0000-4000-8000-{:012d}"

ROWS = (
    '\t\t\t\t("Rider", NAMEOF(\'Riders\'[rider_id]), 1486, "rider_axis", "Other"),\n'
    '\t\t\t\t("Bike", NAMEOF(\'Bikes\'[bike_id]), 1487, "rider_axis", "Other"),\n'
    '\t\t\t\t("Region", NAMEOF(\'Regions\'[region]), 1488, "rider_axis", "Other"),\n'
)


def _model(tmp_path: Path, rows: str = ROWS) -> Path:
    d = tmp_path / "Cafe.SemanticModel" / "definition"
    t = d / "tables"
    t.mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    (t / "y-Selector 1.tmdl").write_text(
        f"table 'y-Selector 1'\n\tlineageTag: {TAG.format(1)}\n\n"
        "\tcolumn 'y-Selector 1'\n\t\tlineageTag: " + TAG.format(2) +
        "\n\t\tsourceColumn: [Value]\n\n"
        "\tpartition 'y-Selector 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\t{\n" + rows + "\t\t\t\t }\n", encoding="utf-8")
    for name, col in (("Riders", "rider_id"), ("Bikes", "bike_id"), ("Regions", "region")):
        (t / f"{name}.tmdl").write_text(
            f"table '{name}'\n\tlineageTag: {TAG.format(10)}\n\n"
            f"\tcolumn {col}\n\t\tdataType: string\n\t\tlineageTag: {TAG.format(11)}\n"
            f"\t\tsourceColumn: {col}\n\n", encoding="utf-8")
    return d.parent


def _violations(payload: dict, *needles: str) -> list[dict]:
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in payload["violations"] if all(n in v["message"] for n in needles)]


# ---------------------------------------------------------------------------
# CG-13: a registered column needs an ordinal
# ---------------------------------------------------------------------------


def test_a_registered_column_without_an_ordinal_is_reported(tmp_path):
    """A row that registers the column but carries no ordinal is not a
    registration the contract can check."""
    rows = ('\t\t\t\t("Rider", NAMEOF(\'Riders\'[rider_id]), "rider_axis", "Other"),\n')
    model = _model(tmp_path, rows)
    contract = {"fieldparam": [{"kind": "column_registered", "table": "y-Selector 1",
                                "column": "rider_id",
                                "groups": ["rider_axis"],
                                "range": [1486, 1499]}]}
    code, payload = run_check(model, "fieldparam-registration-contract",
                              config={"contracts": contract})
    assert code == 1
    assert _violations(payload, "no ordinal parsed")


def test_a_registered_column_with_an_ordinal_is_not_reported(tmp_path):
    model = _model(tmp_path)
    contract = {"fieldparam": [{"kind": "column_registered", "table": "y-Selector 1",
                                "column": "rider_id",
                                "groups": ["rider_axis"],
                                "range": [1486, 1499]}]}
    code, payload = run_check(model, "fieldparam-registration-contract",
                              config={"contracts": contract})
    assert code == 0
    assert _violations(payload) == []


# ---------------------------------------------------------------------------
# CG-14: a group row is a live line with an ordinal
# ---------------------------------------------------------------------------


def test_a_line_naming_the_group_without_an_ordinal_is_not_a_row(tmp_path):
    """The row count sees only the rows that carry an ordinal."""
    rows = ROWS + (
        '\t\t\t\t("Extra", NAMEOF(\'Regions\'[region]), "rider_axis", "Other"),\n')
    model = _model(tmp_path, rows)
    contract = {"fieldparam": [{"kind": "group_table_rows", "table": "y-Selector 1",
                                "group": "rider_axis",
                                "references": "'Regions'",
                                "count": 1}]}
    code, payload = run_check(model, "fieldparam-registration-contract",
                              config={"contracts": contract})
    assert code == 0
    assert _violations(payload) == []


def test_a_comment_naming_the_group_is_not_a_row(tmp_path):
    rows = ('\t\t\t\t-- ("Extra", NAMEOF(\'Regions\'[region]), 1489, "rider_axis", "Other"),\n' + ROWS)
    model = _model(tmp_path, rows)
    contract = {"fieldparam": [{"kind": "group_table_rows", "table": "y-Selector 1",
                                "group": "rider_axis",
                                "references": "'Regions'",
                                "count": 1}]}
    code, payload = run_check(model, "fieldparam-registration-contract",
                              config={"contracts": contract})
    assert code == 0
    assert _violations(payload) == []


def test_the_label_comes_from_the_start_of_the_row(tmp_path):
    """A quoted string later in the row is not the row's label."""
    rows = ('\t\t\t\t("Rider", NAMEOF(\'Riders\'[rider_id]), 1486, "rider_axis", "Other"),\n'
            '\t\t\t\t(NAMEOF(\'Bikes\'[bike_id]), 1487, "rider_axis", "Bike"),\n')
    model = _model(tmp_path, rows)
    contract = {"fieldparam": [{"kind": "group_labels", "table": "y-Selector 1",
                                "group": "rider_axis",
                                "labels": ["Rider", "Bike"]}]}
    code, payload = run_check(model, "fieldparam-registration-contract",
                              config={"contracts": contract})
    assert code == 1
    assert _violations(payload, "'Bike' is not registered in group rider_axis")


def test_a_row_without_a_leading_parenthesis_has_no_label(tmp_path):
    rows = ('\t\t\t\t("Rider", NAMEOF(\'Riders\'[rider_id]), 1486, "rider_axis", "Other"),\n'
            '\t\t\t\t"Rider2", NAMEOF(\'Bikes\'[bike_id]), 1487, "rider_axis", "Other"),\n')
    model = _model(tmp_path, rows)
    contract = {"fieldparam": [{"kind": "group_labels", "table": "y-Selector 1",
                                "group": "rider_axis",
                                "labels": ["Rider2"]}]}
    code, payload = run_check(model, "fieldparam-registration-contract",
                              config={"contracts": contract})
    assert code == 1
    assert _violations(payload, "'Rider2' is not registered in group rider_axis")


pytestmark = pytest.mark.layer1
