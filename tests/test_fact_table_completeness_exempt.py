"""PA30: the O015 informational report, with an exempt fact.

Beside the uncovered findings, the filter-coverage check prints, per model,
the fact-table completeness: how many facts there are, how many are
consumed, how many are covered, how many are uncovered and how many are
unused — and the three lists that say which fact is which.

An exempt fact and an unused fact never fail; they are reported so that a
reader can see why nothing was said about them.
"""

from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

import pytest

from conftest import run_check, violations

TAG = "11111111-1111-4111-8111-{:012d}"


def _table(name: str, measures: list[str], tag: int, partition: str = "",
           reads: str = "") -> str:
    body = f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    if partition:
        body += ("\tcolumn amount\n\t\tdataType: double\n\t\tlineageTag: "
                 + TAG.format(tag + 50) + "\n\t\tsourceColumn: amount\n\n")
    for i, m in enumerate(measures):
        expr = f"SUM({reads}[amount])" if reads else "1"
        body += (f"\tmeasure '{m}' = {expr}\n\t\tlineageTag: "
                 + TAG.format(tag + 100 + i) + "\n")
    if partition:
        body += f"\tpartition {name} = {partition}\n\t\tmode: import\n\t\tsource = x\n"
    return body


def _axis(name: str, targets: list[str], tag: int) -> str:
    rows = ", ".join(f'("{t}", NAMEOF([{t}]), 0, "Sales_x")' for t in targets)
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource = ```\n"
            f"\t\t\t\t{{ {rows} }}\n\t\t\t```\n")


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
    rows = json.dumps([["Sales", "", "Sales_x"]]).encode()
    comp = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    blob = base64.b64encode(comp.compress(rows) + comp.flush()).decode()
    definition = _model(tmp_path, tables)
    (definition / "tables" / "z-Map Dimension-Measure Groupings.tmdl").write_text(
        "table 'z-Map Dimension-Measure Groupings'\n"
        "\tlineageTag: " + TAG.format(900) + "\n\n"
        "\tcolumn 'Analysis Category'\n\t\tdataType: string\n\t\tlineageTag: "
        + TAG.format(901) + "\n\t\tsourceColumn: Analysis Category\n\n"
        "\tpartition 'z-Map Dimension-Measure Groupings' = m\n"
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


def test_the_exempt_fact_is_listed_and_never_fails(tmp_path):
    """PA30: one uncovered, one exempt and one unused fact."""
    model = _with_mapping(tmp_path, {
        "Sales": _table("Sales", ["Revenue"], 1, partition="m", reads="Sales"),
        "Orders": _table("Orders", ["Count"], 2, partition="m", reads="Orders"),
        "Stock": _table("Stock", ["Level"], 3, partition="m"),
        "x-Selector 1": _axis("x-Selector 1", ["Revenue"], 9),
    })
    code, payload = run_check(model, "fact-table-filter-coverage")
    text = "\n".join(payload.get("notes") or [])
    assert "Fact tables identified:                3" in text, text
    assert "Consumed by user-facing measures:      2" in text, text
    assert "Reachable via some f-measure:          0" in text, text
    assert "Uncovered (consumed, no f-measure):    1" in text, text
    assert "Unused (no user-facing consumer):      1" in text, text
    # the exempt fact is listed, the uncovered one names its consumers
    assert ("Gated via the z-Map-driven f-Analysis Category mechanism "
            "(no per-fact f-measure needed, not gating):") in text, text
    assert "  - Sales" in text, text
    assert "Fact tables consumed by user-facing measures, no f-coverage:" in text, text
    assert "  - Orders  (1 user-facing consumer(s))" in text, text
    assert "      e.g. Orders[Count]" in text, text
    assert "Fact tables with no user-facing consumer (not gating):" in text, text
    assert "  - Stock" in text, text
    # only the uncovered fact fails
    found = violations(payload, "O015")
    assert [v["object"] for v in found] == ["Orders"], found
    assert code == 1
