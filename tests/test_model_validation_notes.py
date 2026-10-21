"""PA17: the advisory model validation notes.

The reference validator reported a few things it did not fail on: a model
without a culture or a data source version, a column without a dataType or
with an unknown summarizeBy, a calculation group without a precedence, and
a calculation item that uses neither SELECTEDMEASURE nor ISSELECTEDMEASURE.
They are one opt-in info rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

RULE = "M023"


MODEL = ("model Model\n"
         "\tculture: en-US\n"
         "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n")


def _model(tmp_path: Path, model: str = MODEL,
           tables: dict[str, str] | None = None) -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(model, encoding="utf-8")
    for name, body in (tables or {}).items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def test_the_rule_is_off_by_default(tmp_path):
    """PA17: the notes never fail a plain run."""
    d = _model(tmp_path)
    assert violations(run_check(d)[1], RULE) == []


def test_a_model_without_a_culture(tmp_path):
    """PA17: the recommended model properties."""
    d = _model(tmp_path, model="model Model\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n")
    found = violations(run_check(d, RULE)[1], RULE)
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Missing recommended model property: culture"), found[0]["message"]


def test_a_model_without_a_data_source_version(tmp_path):
    """PA17: the second recommended property."""
    d = _model(tmp_path, model="model Model\n\tculture: en-US\n")
    found = violations(run_check(d, RULE)[1], RULE)
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Missing recommended model property: defaultPowerBIDataSourceVersion"
    ), found[0]["message"]


def test_a_column_without_a_data_type(tmp_path):
    """PA17: the column notes."""
    d = _model(tmp_path, tables={"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcolumn 'kg'\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
    )})
    found = violations(run_check(d, RULE)[1], RULE)
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Column 'kg' missing dataType"), found[0]["message"]


def test_a_column_with_an_unknown_summarize_by(tmp_path):
    """PA17: the summarizeBy note names the valid values."""
    d = _model(tmp_path, tables={"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcolumn 'kg'\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
        "\t\tdataType: double\n"
        "\t\tsummarizeBy: averageish\n"
    )})
    found = violations(run_check(d, RULE)[1], RULE)
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Column 'kg' has unknown summarizeBy: averageish (valid: none, sum, "
        "min, max, count, distinctCount, average, standardDeviation, "
        "variance)"), found[0]["message"]


def test_a_calculation_group_without_a_precedence(tmp_path):
    """PA17: the calculation group note."""
    d = _model(tmp_path, tables={"Selector": (
        "table 'Selector'\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcalculationGroup\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
    )})
    found = violations(run_check(d, RULE)[1], RULE)
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Calculation group has no explicit precedence (defaults to 0)"
    ), found[0]["message"]


def test_a_calculation_item_that_uses_no_measure_selector(tmp_path):
    """PA17: the calculation item note."""
    d = _model(tmp_path, tables={"Selector": (
        "table 'Selector'\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcalculationGroup\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
        "\t\tprecedence: 1\n\n"
        "\t\tcalculationItem\n"
        "\t\t\tlineageTag: 33333333-3333-4333-8333-333333333333\n"
        "\t\t\tformula = 1 + 1\n"
    )})
    found = violations(run_check(d, RULE)[1], RULE)
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Calculation item should typically use SELECTEDMEASURE or "
        "ISSELECTEDMEASURE"), found[0]["message"]
