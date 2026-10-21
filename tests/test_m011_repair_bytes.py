"""PA6, PA8: the M011 repair's bytes and the properties it recognises.

(a) A blank line before the moved property line stays.
(b) An object that carries the same flag twice keeps one copy, in its
    first property slot.
(c) The moved line keeps its own indentation.

The reference recognised a fixed list of simple properties; the tool knows
a few more, and flags a simple property at any depth under its owner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations


def _model(tmp_path: Path, body: str) -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True, exist_ok=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    (definition / "tables" / "Beans.tmdl").write_text(body, encoding="utf-8")
    return definition


AFTER_ANNOTATION = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tmeasure Kg = SUM(Beans[kg])\n"
    "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n\n"
    "\t\tannotation note = a\n"
    "\n"
    "\t\tisHidden\n"
)


def test_the_blank_line_before_the_moved_line_stays(tmp_path):
    """PA6 (a): the blank line is not merged away."""
    d = _model(tmp_path, AFTER_ANNOTATION)
    code, payload = run_fix(d, "M011")
    text = (d / "tables" / "Beans.tmdl").read_text(encoding="utf-8")
    assert "\t\tannotation note = a\n\n" in text, repr(text)
    assert text.endswith("\n"), repr(text)
    assert code == 0, payload


def test_the_moved_line_lands_in_the_first_property_slot(tmp_path):
    """PA6: the property moves to the object's first property slot."""
    d = _model(tmp_path, AFTER_ANNOTATION)
    run_fix(d, "M011")
    text = (d / "tables" / "Beans.tmdl").read_text(encoding="utf-8")
    assert "\tmeasure Kg = SUM(Beans[kg])\n\t\tisHidden\n" in text, repr(text)


def test_a_repeated_flag_is_left_once(tmp_path):
    """PA6 (b): one copy, in the first property slot."""
    body = (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tmeasure Kg = SUM(Beans[kg])\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n\n"
        "\t\tannotation note = a\n"
        "\n"
        "\t\tisHidden\n"
        "\n"
        "\t\tisHidden\n"
    )
    d = _model(tmp_path, body)
    run_fix(d, "M011")
    text = (d / "tables" / "Beans.tmdl").read_text(encoding="utf-8")
    assert text.count("isHidden") == 1, repr(text)
    assert "\t\tisHidden\n\t\tlineageTag:" in text, repr(text)


def test_the_moved_line_keeps_its_own_indentation(tmp_path):
    """PA6 (c): the indentation of the line that moved."""
    body = AFTER_ANNOTATION.replace("\t\tisHidden\n", "\t\t\tisHidden\n")
    d = _model(tmp_path, body)
    run_fix(d, "M011")
    text = (d / "tables" / "Beans.tmdl").read_text(encoding="utf-8")
    assert "\t\t\tisHidden" in text, repr(text)


def test_the_repair_keeps_the_final_newline(tmp_path):
    """PA6: the file keeps the newline it had."""
    d = _model(tmp_path, AFTER_ANNOTATION)
    run_fix(d, "M011")
    raw = (d / "tables" / "Beans.tmdl").read_bytes()
    assert raw.endswith(b"\n"), raw


def test_a_property_the_reference_knows_is_flagged(tmp_path):
    """PA8: the reference's list of simple properties."""
    for token in ("isHidden", "isKey", "isNameInferred", "isDefaultLabel",
                  "isDefaultImage", "displayFolder", "formatString",
                  "summarizeBy", "sortByColumn", "dataType", "dataCategory",
                  "displayOrdinal", "lineageTag"):
        body = AFTER_ANNOTATION.replace("\t\tisHidden\n", f"\t\t{token}: x\n")
        d = _model(tmp_path, body)
        found = violations(run_check(d, "M011")[1], "M011")
        assert found, f"{token} was not flagged"


def test_a_property_below_the_owner_is_not_flagged(tmp_path):
    """PA8: the tool wants the property one level under its owner; the
    reference wanted any depth."""
    body = AFTER_ANNOTATION.replace("\t\tisHidden\n", "\t\t\t\tisHidden\n")
    d = _model(tmp_path, body)
    assert violations(run_check(d, "M011")[1], "M011") == []
