"""PA30: the O015 informational report.

Beside the uncovered findings, the filter-coverage check prints, per model,
the fact-table completeness: how many facts there are, how many are
consumed, how many are covered, how many are uncovered and how many are
unused — and the three lists that say which fact is which.

An exempt fact and an unused fact never fail; they are reported so that a
reader can see why nothing was said about them.
"""

from __future__ import annotations

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


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def test_the_report_prints_the_counts_and_the_lists(tmp_path):
    """PA30: three facts, one uncovered, one covered, one unused."""
    sales = _table("Sales", ["Revenue"], 1, partition="m", reads="Sales")
    orders = _table("Orders", ["Count"], 2, partition="m", reads="Orders")
    stock = _table("Stock", ["Level"], 3, partition="m")
    # an f- measure that covers Orders but not Sales
    filters = _table("f-Filters", ["f-Orders"], 4, reads="Orders")
    model = _model(tmp_path, {"Sales": sales, "Orders": orders,
                              "Stock": stock, "f-Filters": filters})

    code, payload = run_check(model, "fact-table-filter-coverage")
    text = "\n".join(payload.get("notes") or [])
    assert "Fact-Table Completeness" in text, text
    assert "Fact tables identified:                3" in text, text
    assert "Consumed by user-facing measures:      2" in text, text
    assert "Reachable via some f-measure:          1" in text, text
    assert "Uncovered (consumed, no f-measure):    1" in text, text
    assert "Unused (no user-facing consumer):      1" in text, text
    assert "Fact tables consumed by user-facing measures, no f-coverage:" \
        in text, text
    assert "  - Sales  (1 user-facing consumer(s))" in text, text
    assert "      e.g. Sales[Revenue]" in text, text
    assert "Fact tables with no user-facing consumer (not gating):" in text, text
    assert "  - Stock" in text, text
