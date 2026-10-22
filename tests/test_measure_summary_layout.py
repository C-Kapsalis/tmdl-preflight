"""The measure-organisation summary and the helper inventory.

* PA27: the summary is per model, in the reference's layout.
* PA37: the helper inventory by kind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli

TAG = "11111111-1111-4111-8111-{:012d}"


def _table(name: str, measures: list[str], tag: int, described=()) -> str:
    body = f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    for i, m in enumerate(measures):
        if m in described:
            body += f"\t/// What it does\n"
        body += (f"\tmeasure '{m}' = 1\n\t\tlineageTag: "
                 + TAG.format(tag + 100 + i) + "\n")
    body += f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource = 1\n"
    return body


def _axis(name: str, targets: list[str], tag: int) -> str:
    rows = ", ".join(f'("{t}", NAMEOF([{t}]), 0)' for t in targets)
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource =\n"
            f"\t\t\t\t{{ {rows} }}\n")


def _model(root: Path, name: str, tables: dict[str, str]) -> Path:
    definition = root / f"{name}.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for tname, body in tables.items():
        (definition / "tables" / f"{tname}.tmdl").write_text(body, encoding="utf-8")
    return root / f"{name}.SemanticModel"


def test_the_summary_reads_the_y_axis_tables_too(tmp_path):
    """PA27: the surfacing set is x-Selector 1..9 and y-Selector 1..9."""
    _model(tmp_path, "Cafe", {
        "Helper Measures": _table("Helper Measures", ["Revenue", "Bags Sold"], 1),
        "y-Selector 1": _axis("y-Selector 1", ["Revenue"], 2),
    })
    code, out, err = run_cli("stats", tmp_path, "--measures")
    assert code == 0, err
    assert "Distinct measures referenced by x/y-Selector field params: 1" in out, out
    assert "User-facing measures surfaced (intersection):          1" in out, out


def test_the_summary_of_a_four_measure_model(tmp_path):
    """PA27: the exact lines of the reference layout."""
    _model(tmp_path, "Cafe", {
        "Helper Measures": _table("Helper Measures",
                                  ["Revenue", "Bags Sold", "-helper Base", "f-Sales"], 1),
    })
    code, out, err = run_cli("stats", tmp_path, "--measures")
    assert code == 0, err
    assert "Total measures: 4" in out, out
    assert "  User-facing names: 2 (50.0%)" in out, out
    assert "  Helper names:      2 (50.0%)" in out, out
    assert "Helper subcategories:" in out, out
    assert "Top 10 tables by measure count:" in out, out


def test_the_dash_helper_block_is_left_out_when_there_is_none(tmp_path):
    """PA27: the With/Without lines are omitted when the count is 0."""
    _model(tmp_path, "Cafe", {
        "Helper Measures": _table("Helper Measures", ["Revenue"], 1),
    })
    code, out, err = run_cli("stats", tmp_path, "--measures")
    assert code == 0, err
    assert "Helper Measure Analysis:" in out, out
    assert "With description:" not in out, out
    assert "Without description:" not in out, out


def test_the_helper_inventory_by_kind(tmp_path):
    """PA37: the helpers counted by kind, with the description of each."""
    _model(tmp_path, "Cafe", {
        "Helper Measures": _table("Helper Measures",
                                  ["-helper Base", "f-Sales", "i-Rows",
                                   "-Visual Label", "-Base Cups"], 1),
    })
    code, out, err = run_cli("stats", tmp_path, "--measures")
    assert code == 0, err
    assert "Total helper-named measures: 5" in out, out
    assert "By subcategory:" in out, out
    assert "'-helper Foo' reusable DAX subroutine for complex measures" in out, out
    assert "'f-Foo' visual-level filter (0/1 flag) lives in f-Filters" in out, out
    assert ("'i-Foo' consumed by visuals (tooltips, dynamic titles, "
            "applied-filter labels)") in out, out
    assert ("'-Visual Foo' affects plot elements; 'w-' interacts with plot "
            "colors") in out, out
    assert ("'-Foo'  hidden building-block in a domain Measures table; feeds "
            "final measures") in out, out


def test_the_json_carries_the_inventory(tmp_path):
    """PA37: the JSON has the same numbers."""
    _model(tmp_path, "Cafe", {
        "Helper Measures": _table("Helper Measures", ["-helper Base", "f-Sales"], 1),
    })
    code, out, err = run_cli("stats", tmp_path, "--measures", "--json")
    assert code == 0, err
    payload = json.loads(out)["measures"]
    one = payload["per_model"][0]
    assert one["total"] == 2
    assert one["helpers"] == 2
    assert one["helper_kinds"] == {"measure_helper": 1, "slicer_helper": 1}
