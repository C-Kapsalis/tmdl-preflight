"""PA11: the M017 defaults and wording.

Every line of a table file that begins with four spaces is an error,
expression bodies included; a line that begins with tabs is never flagged.
The message is `Line <N>: Uses spaces instead of tabs for indentation`.

The bare quoted multi-line measure note is always computed as a non-failing
note.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

BEANS = (
    "table Beans\n"
    "\tlineageTag: 00000000-0000-4000-8000-000000000001\n\n"
    "\tcolumn kg\n"
    "\t\tdataType: double\n"
    "\t\tlineageTag: 00000000-0000-4000-8000-000000000002\n"
    "\t\tsourceColumn: kg\n\n"
    "\tmeasure Kg = SUM(Beans[kg])\n"
    "\t\tlineageTag: 00000000-0000-4000-8000-000000000003\n"
)


def _model(tmp_path: Path, body: str) -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    (definition / "tables" / "Beans.tmdl").write_text(body, encoding="utf-8")
    return definition


def test_a_line_with_four_spaces_is_an_error(tmp_path):
    """PA11: the exact message."""
    body = BEANS.replace("\t\tsourceColumn: kg\n",
                         "    sourceColumn: kg\n")
    model = _model(tmp_path, body)
    found = violations(run_check(model, "M017")[1], "M017")
    assert len(found) == 1, found
    assert found[0]["message"] == \
        "Line 7: Uses spaces instead of tabs for indentation", found[0]


def test_a_fenced_body_line_is_an_error_too(tmp_path):
    """PA11: expression bodies included."""
    body = BEANS.replace(
        "\tmeasure Kg = SUM(Beans[kg])\n",
        "\tmeasure Kg = ```\n    VAR x = SUM(Beans[kg])\n    RETURN x\n\t\t\t```\n")
    model = _model(tmp_path, body)
    found = violations(run_check(model, "M017")[1], "M017")
    assert len(found) == 2, found
    assert all(f["message"].startswith("Line ") for f in found)


def test_a_bare_multiline_body_is_an_info_note(tmp_path):
    """PA11: the note is always computed, and it never fails."""
    body = BEANS.replace("\tmeasure Kg = SUM(Beans[kg])\n",
                         "\tmeasure 'Kg' =\n\t\t\tSUM(Beans[kg])\n")
    model = _model(tmp_path, body)
    found = violations(run_check(model, "M017")[1], "M017")
    assert len(found) == 1 and found[0]["severity"] == "info"
    assert "Multiline DAX should use triple backticks" in found[0]["message"]


def test_a_line_that_starts_with_tabs_is_never_flagged(tmp_path):
    """PA11: tabs and then spaces are fine."""
    body = BEANS.replace("\t\tdataType: double\n",
                         "\t\t    dataType: double\n")
    model = _model(tmp_path, body)
    assert violations(run_check(model, "M017")[1], "M017") == []
