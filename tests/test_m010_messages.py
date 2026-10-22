"""PA9: the M010 messages name the object and quote the offending line.

Three shapes: a property right after the `=`, a property buried in the
expression, and a property inside a ``` expression. Each message quotes the
first 40 characters of the offending line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations


def _model(tmp_path: Path, body: str) -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    (definition / "tables" / "Beans.tmdl").write_text(body, encoding="utf-8")
    return definition


AFTER_EQUALS = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tmeasure Kg =\n"
    "\t\tisHidden\n"
    "\t\t\tSUM(Beans[kg])\n"
)

BURIED = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tmeasure Kg =\n"
    "\t\t\tVAR c = SUM(Beans[kg])\n"
    "\t\t\tRETURN\n"
    "\t\t\tisHidden\n"
    "\t\t\tc\n"
)

INSIDE_FENCE = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tmeasure Kg = ```\n"
    "\t\t\tSUM(Beans[kg])\n"
    "\t\t\tlineageTag: 12345678-0000-4000-8000-000000000000\n"
    "\t\t```\n"
)


def test_the_property_right_after_the_equals(tmp_path):
    """PA9: the first shape."""
    d = _model(tmp_path, AFTER_EQUALS)
    found = violations(run_check(d, "M010")[1], "M010")
    assert len(found) == 1, found
    assert found[0]["message"] == (
        "Kg: property right after `=` (line 5): "
        "isHidden"), found[0]["message"]


def test_the_property_buried_in_the_expression(tmp_path):
    """PA9: the second shape."""
    d = _model(tmp_path, BURIED)
    found = violations(run_check(d, "M010")[1], "M010")
    assert len(found) == 1, found
    assert found[0]["message"] == (
        "Kg: property buried in expression (line 7): "
        "isHidden"), found[0]["message"]


def test_the_property_inside_a_fenced_expression(tmp_path):
    """PA9: the third shape."""
    d = _model(tmp_path, INSIDE_FENCE)
    found = violations(run_check(d, "M010")[1], "M010")
    assert len(found) == 1, found
    assert found[0]["message"] == (
        "Kg: property inside ``` expression (line 6): "
        "lineageTag: 12345678-0000-4000-8000-0000"), found[0]["message"]


def test_a_long_offending_line_is_quoted_to_forty_characters(tmp_path):
    """PA9: the quote stops at 40 characters."""
    body = INSIDE_FENCE.replace(
        "lineageTag: 12345678-0000-4000-8000-000000000000",
        "displayFolder: a very long folder name that goes on and on")
    d = _model(tmp_path, body)
    found = violations(run_check(d, "M010")[1], "M010")
    assert len(found) == 1, found
    assert found[0]["message"].endswith(
        "displayFolder: a very long folder name t"), found[0]["message"]


def test_a_property_shaped_line_in_a_string_is_not_a_finding(tmp_path):
    """PA9: the tool skips strings and comments."""
    body = (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tmeasure Kg = ```\n"
        '\t\t\t"isHidden is only text"\n'
        "\t\t\t-- isHidden is only a comment\n"
        "\t\t```\n"
    )
    d = _model(tmp_path, body)
    assert violations(run_check(d, "M010")[1], "M010") == []
