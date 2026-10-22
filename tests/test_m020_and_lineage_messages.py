"""PA15, PA16: the messages of M020, M003 and M004."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def test_a_calculated_column_without_an_expression(tmp_path):
    """PA15: a column declared with '=' and no expression at all.

    The expression of the column is empty, so the column is reported with
    the empty-expression text.
    """
    d = _model(tmp_path, {"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcolumn kg =\n"
        "\t\tdataType: double\n"
    )})
    found = violations(run_check(d, "M020")[1], "M020")
    assert len(found) == 1, found
    assert found[0]["message"] == (
        "Beans[kg] has empty expression"), found[0]["message"]


def test_a_calculated_column_with_an_empty_expression(tmp_path):
    """PA15: the first text."""
    d = _model(tmp_path, {"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcolumn kg = ```\n"
        "\t\t```\n"
    )})
    found = violations(run_check(d, "M020")[1], "M020")
    assert len(found) == 1, found
    assert found[0]["message"] == (
        "Beans[kg] has empty expression"), found[0]["message"]


def test_a_calculated_column_with_the_expression_on_the_next_line(tmp_path):
    """PA15: the expression of a calculated column may sit on the next
    line; such a column has an expression and is not reported."""
    d = _model(tmp_path, {"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcolumn kg =\n"
        "\t\t\tIF(Beans[price] > 1000, \"Premium\", \"Standard\")\n"
        "\t\tdataType: string\n"
    )})
    found = violations(run_check(d, "M020")[1], "M020")
    assert found == [], found


def test_a_duplicate_tag_in_two_files(tmp_path):
    """PA16: the M003 text names both files."""
    tag = "11111111-1111-4111-8111-111111111111"
    d = _model(tmp_path, {
        "Beans": (f"table Beans\n\tlineageTag: {tag}\n"),
        "Apples": (f"table Apples\n\tlineageTag: {tag}\n"),
    })
    found = violations(run_check(d, "M003")[1], "M003")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        f"Duplicate lineageTag '{tag}' found in files: "), found[0]["message"]
    assert "Apples.tmdl" in found[0]["message"], found[0]["message"]
    assert "Beans.tmdl" in found[0]["message"], found[0]["message"]


def test_a_placeholder_lineage_tag(tmp_path):
    """PA16: the M004 text."""
    d = _model(tmp_path, {"Beans": (
        "table Beans\n\tlineageTag: placeholder\n"
    )})
    found = violations(run_check(d, "M004")[1], "M004")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "LineageTag 'placeholder' is not a canonically-formatted UUID "
        "(expected 8-4-4-4-12 hex)"), found[0]["message"]
