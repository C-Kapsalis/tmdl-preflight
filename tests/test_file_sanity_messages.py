"""PA14: the file-sanity messages of M001, M002 and M016."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations


def _model(tmp_path: Path, tables: dict[str, str] | None = None,
           model: str = "model Model\n") -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(model, encoding="utf-8")
    (definition / "database.tmdl").write_text(
        "database\n\tcompatibilityLevel: 1601\n", encoding="utf-8")
    for name, body in (tables or {"Beans": (
            "table Beans\n\tlineageTag: 11111111-1111-4111-8111-111111111111\n"
    )}).items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def test_a_model_file_without_a_model_declaration(tmp_path):
    """PA14: the model declaration message."""
    d = _model(tmp_path, model="culture: en-US\n")
    found = violations(run_check(d, "M016")[1], "M016")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Model file must start with 'model' declaration"), found[0]["message"]


def test_a_table_file_without_a_table_declaration(tmp_path):
    """PA14: the table declaration message."""
    d = _model(tmp_path, tables={"Beans": "column kg\n\tdataType: double\n"})
    found = violations(run_check(d, "M016")[1], "M016")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Table file must start with 'table' declaration"), found[0]["message"]


def test_a_measure_with_an_empty_expression(tmp_path):
    """PA14: the empty DAX message."""
    d = _model(tmp_path, tables={"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tmeasure Kg = ```\n"
        "\t\t```\n"
    )})
    found = violations(run_check(d, "M016")[1], "M016")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Measure 'Kg' has empty DAX expression"), found[0]["message"]


def test_a_file_that_is_not_utf8(tmp_path):
    """PA14: the encoding message."""
    d = _model(tmp_path)
    (d / "tables" / "Apples.tmdl").write_bytes(b"table Apples\n\xff\xfe\n")
    found = violations(run_check(d, "M002")[1], "M002")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "File encoding error: "), found[0]["message"]


def test_a_file_with_a_null_byte(tmp_path):
    """PA14: the null byte message."""
    d = _model(tmp_path)
    (d / "tables" / "Apples.tmdl").write_bytes(
        b"table Apples\n\tlineageTag: 11111111-1111-4111-8111-111111111111\n\x00\n")
    found = violations(run_check(d, "M016")[1], "M016")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Apples.tmdl:3 contains null bytes"), found[0]["message"]


def test_a_file_with_windows_line_endings(tmp_path):
    """PA14: the line-ending message, when the check is on."""
    d = _model(tmp_path)
    f = d / "tables" / "Apples.tmdl"
    f.write_bytes(
        b"table Apples\r\n\tlineageTag: 11111111-1111-4111-8111-111111111111\r\n")
    config = {"rules": {"M016": {"check_line_endings": True,
                                 "lf_only_files": ["tables/Apples.tmdl"]}}}
    from conftest import write_config
    cfg = write_config(tmp_path, config)
    found = violations(run_check(d, "M016", config=cfg)[1], "M016")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "Apples.tmdl: Windows line endings (CRLF)"), found[0]["message"]


def test_a_root_level_comment(tmp_path):
    """PA14: the root-level comment message."""
    d = _model(tmp_path, tables={"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\t// A note between the objects\n"
    )})
    found = violations(run_check(d, "M016")[1], "M016")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "line 4: root-level comment is indented"), found[0]["message"]


def test_unmatched_code_fences(tmp_path):
    """PA14: the fence counter message."""
    d = _model(tmp_path, tables={"Beans": (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tmeasure Kg = ```\n"
        "\t\tSUM(Beans[kg])\n"
    )})
    found = violations(run_check(d, "M016")[1], "M016")
    assert len(found) == 1, found
    assert found[0]["message"].startswith(
        "unmatched DAX code fences: 1 ``` markers (must be even)"), found[0]["message"]


def test_the_missing_directories_and_files(tmp_path):
    """PA14: the model-level messages."""
    root = tmp_path / "Cafe.SemanticModel"
    (root / "definition" / "tables").mkdir(parents=True)
    (root / "definition" / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    config = {"rules": {"M016": {"required_files": ["model.tmdl", "database.tmdl"]}}}
    from conftest import write_config
    cfg = write_config(tmp_path, config)
    found = violations(run_check(root, "M016", config=cfg)[1], "M016")
    messages = [f["message"] for f in found]
    assert any("required files missing: ['database.tmdl']" in m for m in messages), messages


def test_the_missing_directories(tmp_path):
    """PA14: the directories message."""
    root = tmp_path / "Cafe.SemanticModel"
    (root / "definition").mkdir(parents=True)
    (root / "definition" / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    found = violations(run_check(root, "M016")[1], "M016")
    messages = [f["message"] for f in found]
    assert any("required directories missing: ['tables']" in m for m in messages), messages
    found = violations(run_check(root, "M001")[1], "M001")
    messages = [f["message"] for f in found]
    assert any("required directories missing: ['tables']" in m for m in messages), messages
