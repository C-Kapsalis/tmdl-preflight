"""PA32: a fact is matched only when the reference names it.

The reference counted a fact `Sales` as read whenever the text `Sales[`
appeared, even inside `MySales[`. The tool requires a non-word character
before the name, so a measure reading `MySales[amount]` does not consume
`Sales`.

PA33: the finding names the exact pbip-forge command for the model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

TAG = "11111111-1111-4111-8111-{:012d}"


def _fact(name: str, tag: int, measure: str, reads: str) -> str:
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            "\tcolumn amount\n\t\tdataType: double\n\t\tlineageTag: "
            + TAG.format(tag + 50) + "\n\t\tsourceColumn: amount\n\n"
            f"\tmeasure '{measure}' = SUM({reads}[amount])\n\t\tlineageTag: "
            + TAG.format(tag + 100) + "\n\n"
            f"\tpartition {name} = m\n\t\tmode: import\n\t\tsource = x\n")


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def test_a_longer_name_does_not_consume_the_shorter_fact(tmp_path):
    """PA32: `MySales[amount]` does not consume `Sales`.

    A measure that reads `MySales[amount]` leaves `Sales` uncovered: the
    reference would have counted the shorter name as read too.
    """
    sales = _fact("Sales", 1, "Revenue", "Sales")
    my_sales = _fact("MySales", 2, "Other", "MySales")
    model = _model(tmp_path, {"Sales": sales, "MySales": my_sales})
    code, payload = run_check(model, "fact-table-filter-coverage")
    facts = {v["message"].split()[2] for v in violations(payload, "O015")}
    assert "Sales" in facts, facts


def test_the_finding_names_the_command_for_the_model(tmp_path):
    """PA33: the exact pbip-forge command for the model at hand."""
    sales = _fact("Sales", 1, "Revenue", "Sales")
    model = _model(tmp_path, {"Sales": sales})
    code, payload = run_check(model, "fact-table-filter-coverage")
    found = violations(payload, "O015")
    assert found, "no finding"
    assert "pbip-forge f-filters --model Shop.SemanticModel" in \
        found[0]["message"], found[0]
