"""PA31: the category-mechanism exemption reads the numbered x-axis tables.

By default the exemption reads its axis rows only from `x-Selector 1` to
`x-Selector 9`. A plot-specific table is added only by configuration, so a
fact whose only surfacing row lives there stays uncovered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

TAG = "11111111-1111-4111-8111-{:012d}"


def _fact(name: str, tag: int) -> str:
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            "\tcolumn amount\n\t\tdataType: double\n\t\tlineageTag: "
            + TAG.format(tag + 50) + "\n\t\tsourceColumn: amount\n\n"
            "\tmeasure 'Revenue' = SUM(Sales[amount])\n\t\tlineageTag: "
            + TAG.format(tag + 100) + "\n\n"
            f"\tpartition {name} = m\n\t\tmode: import\n\t\tsource = x\n")


def _axis(name: str, tag: int) -> str:
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource = ```\n"
            '\t\t\t\t{ ("Revenue", NAMEOF(\'Sales\'[Revenue]), 0, "Sales_x") }\n'
            "\t\t\t```\n")


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def _with_mapping(tmp_path: Path, tables: dict[str, str]) -> Path:
    """The same model, with a mapping table that maps the Sales_x group."""
    import base64
    import json
    import zlib
    rows = json.dumps([["Sales", "", "Sales_x"]]).encode()
    comp = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    blob = base64.b64encode(comp.compress(rows) + comp.flush()).decode()
    definition = _model(tmp_path, tables)
    (definition / "tables" / "z-Map Dimension-Measure Groupings.tmdl").write_text(
        "table 'z-Map Dimension-Measure Groupings'\n"
        "\tlineageTag: " + TAG.format(900) + "\n\n"
        "\tcolumn 'Analysis Category'\n\t\tdataType: string\n\t\tlineageTag: "
        + TAG.format(901) + "\n\t\tsourceColumn: Analysis Category\n\n"
        f"\tpartition 'z-Map Dimension-Measure Groupings' = m\n"
        "\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\tlet\n"
        "\t\t\t\t    Source = Table.FromRows(Json.Document(Binary.Decompress("
        f'Binary.FromText("{blob}", BinaryEncoding.Base64), '
        "Compression.Deflate)), let _t = ((type nullable text) meta "
        '[Serialized.Text = true]) in type table [#"Analysis Category" = _t, '
        '#"Analysis Subcategory" = _t, category_x_id = _t])\n'
        "\t\t\t\tin\n"
        "\t\t\t\t    Source\n",
        encoding="utf-8")
    return definition


def test_a_plot_specific_row_does_not_exempt_a_fact(tmp_path):
    """PA31: the exemption reads the numbered x-axis tables only."""
    model = _with_mapping(tmp_path, {
        "Sales": _fact("Sales", 1),
        "x-Plot Specific 1": _axis("x-Plot Specific 1", 2),
    })
    code, payload = run_check(model, "fact-table-filter-coverage")
    found = violations(payload, "O015")
    assert found, "the fact was exempt through a plot-specific row"
    assert "Sales" in found[0]["message"], found[0]


def test_a_numbered_x_axis_row_does_exempt_a_fact(tmp_path):
    """PA31: the other side of the rule."""
    model = _with_mapping(tmp_path, {
        "Sales": _fact("Sales", 1),
        "x-Selector 1": _axis("x-Selector 1", 2),
    })
    code, payload = run_check(model, "fact-table-filter-coverage")
    found = violations(payload, "O015")
    assert found == [], found
