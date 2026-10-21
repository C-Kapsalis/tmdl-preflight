"""The visibility and coverage reports.

* PA34: the helper and user-facing visibility summaries.
* PA35: the folder, description and table-description coverage numbers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations

TAG = "11111111-1111-4111-8111-{:012d}"


def _measure(name: str, hidden: bool = False, folder: str = "",
             description: str = "", tag: int = 0) -> str:
    body = ""
    if description:
        body += f"\t/// {description}\n"
    body += f"\tmeasure '{name}' = 1\n"
    if hidden:
        body += "\t\tisHidden\n"
    if folder:
        body += f"\t\tdisplayFolder: {folder}\n"
    body += "\t\tlineageTag: " + TAG.format(tag) + "\n"
    return body


def _table(name: str, measures: list[str], tag: int, described: bool = False) -> str:
    body = ""
    if described:
        body += "\t/// What the table holds\n"
    body += f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    for i, m in enumerate(measures):
        body += _measure(m, tag=tag + 100 + i)
    body += f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource = 1\n"
    return body


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def _text(model: Path, rule: str, *args: str) -> str:
    code, out, err = run_cli("check", str(model), "--select", rule, "--no-config",
                             *args)
    assert code in (0, 1), err
    return out


def test_the_helper_visibility_summary(tmp_path):
    """PA34: the counts and the list of the visible helpers."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Base", "i-Debug"], 1),
    })
    out = _text(model, "helper-measures-hidden")
    assert "Helper Measure Visibility (Shop.SemanticModel):" in out, out
    assert "Total helper-named measures: 2" in out, out
    assert "Hidden: 0 (0.0%)" in out, out
    assert "Visible (need to hide): 2" in out, out
    assert "Helpers currently visible to users (set isHidden=true):" in out, out
    assert "  - [diagnostic_helper] Helper Measures[i-Debug]" in out, out
    assert "  - [measure_helper] Helper Measures[-helper Base]" in out, out


def test_the_helper_visibility_summary_when_all_hidden(tmp_path):
    """PA34: the all-clear line."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Base"], 1),
    })
    path = model / "tables" / "Helper Measures.tmdl"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "\tmeasure '-helper Base' = 1\n", "\tmeasure '-helper Base' = 1\n\t\tisHidden\n"),
        encoding="utf-8")
    out = _text(model, "helper-measures-hidden")
    assert "Hidden: 1 (100.0%)" in out, out
    assert "All helper-named measures are properly hidden." in out, out


def test_the_user_facing_visibility_summary(tmp_path):
    """PA34: the counts and the list of the hidden user-facing measures."""
    model = _model(tmp_path, {
        "Coffee Measures": _table("Coffee Measures", ["Revenue", "Bags Sold"], 1),
    })
    path = model / "tables" / "Coffee Measures.tmdl"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "\tmeasure 'Revenue' = 1\n", "\tmeasure 'Revenue' = 1\n\t\tisHidden\n"),
        encoding="utf-8")
    out = _text(model, "user-facing-measure-visible")
    assert "User-Facing Measure Visibility (Shop.SemanticModel):" in out, out
    assert "Total user-facing-named measures: 2 (+0 scaffolding names filtered)" in out, out
    assert "Visible: 1 (50.0%)" in out, out
    assert "Hidden (need to unhide OR rename to helper): 1" in out, out
    assert "User-facing-named measures currently hidden:" in out, out
    assert "  - Coffee Measures[Revenue]" in out, out
    assert "JUDGMENT CALL FOR THE BI DEVELOPER" in out, out


def test_the_user_facing_visibility_summary_when_all_visible(tmp_path):
    """PA34: the all-clear line."""
    model = _model(tmp_path, {
        "Coffee Measures": _table("Coffee Measures", ["Revenue"], 1),
    })
    out = _text(model, "user-facing-measure-visible")
    assert "Visible: 1 (100.0%)" in out, out
    assert "All user-facing-named measures are visible." in out, out


def test_the_display_folder_coverage(tmp_path):
    """PA35: the folder coverage of the user-facing measures."""
    model = _model(tmp_path, {
        "Coffee Measures": _table("Coffee Measures", ["Revenue"], 1),
    })
    path = model / "tables" / "Coffee Measures.tmdl"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "\tmeasure 'Revenue' = 1\n",
        "\tmeasure 'Revenue' = 1\n\t\tdisplayFolder: Sales\n"), encoding="utf-8")
    out = _text(model, "user-facing-display-folder")
    assert "User-facing measures: 1" in out, out
    assert "With folders:    1 (100.0%)" in out, out
    assert "Without folders: 0" in out, out


def test_a_whitespace_only_folder_counts_as_present(tmp_path):
    """PA35: the folder counts when the property is there and not empty."""
    model = _model(tmp_path, {
        "Coffee Measures": _table("Coffee Measures", ["Revenue"], 1),
    })
    path = model / "tables" / "Coffee Measures.tmdl"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "\tmeasure 'Revenue' = 1\n",
        '\tmeasure \'Revenue\' = 1\n\t\tdisplayFolder: "  "\n'), encoding="utf-8")
    out = _text(model, "user-facing-display-folder")
    assert "With folders:    1 (100.0%)" in out, out
    assert "Without folders: 0" in out, out


def test_the_description_coverage(tmp_path):
    """PA35: the description coverage of the user-facing measures."""
    model = _model(tmp_path, {
        "Coffee Measures": _table("Coffee Measures", ["Revenue", "Bags Sold"], 1),
    })
    path = model / "tables" / "Coffee Measures.tmdl"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "\tmeasure 'Bags Sold' = 1\n",
        "\t/// Number of bags sold\n\tmeasure 'Bags Sold' = 1\n"), encoding="utf-8")
    out = _text(model, "user-facing-measure-description")
    assert "Total user-facing measures: 2" in out, out
    assert "With descriptions:    1 (50.0%)" in out, out
    assert "Without descriptions: 1" in out, out
    assert "Measures needing descriptions:" in out, out
    assert "  - Coffee Measures[Revenue]" in out, out


def test_the_table_description_coverage(tmp_path):
    """PA35: the description coverage of the tables."""
    model = _model(tmp_path, {
        "Coffee Measures": _table("Coffee Measures", ["Revenue"], 1, described=True),
        "Orders": _table("Orders", [], 2),
    })
    out = _text(model, "table-description-coverage")
    assert "Total tables: 2" in out, out
    assert "With descriptions: 1 (50.0%)" in out, out
    assert "Without descriptions: 1" in out, out
