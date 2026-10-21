"""The measures-in-fact-tables rule: the internal-name list, the advisory
tags and the report block.

* PA22: the internal-name tokens are the reference ones by default, so a
  measure whose name carries one of them is advisory, never a warning.
* PA23: the advisory tags follow the reference, in its order; an
  internal-name hit adds no tag; no tags means no bracket group.
* PA39: the rule prints, per model, the user-facing measures it found and
  the advisory ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations

TAG = "11111111-1111-4111-8111-{:012d}"


def _measure(name: str, expression: str = "1", hidden: bool = False,
             folder: str = "", tag: int = 0) -> str:
    body = f"\tmeasure '{name}' = {expression}\n"
    if hidden:
        body += "\t\tisHidden\n"
    if folder:
        body += f"\t\tdisplayFolder: {folder}\n"
    body += "\t\tlineageTag: " + TAG.format(tag) + "\n"
    return body


def _fact(name: str, measures: list[str], tag: int) -> str:
    body = f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    body += ("\tcolumn amount\n\t\tdataType: double\n\t\tlineageTag: "
             + TAG.format(tag + 50) + "\n\t\tsourceColumn: amount\n\n")
    for i, m in enumerate(measures):
        body += _measure(m, tag=tag + 100 + i)
    body += (f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = x\n")
    return body


def _axis(name: str, targets: list[str], tag: int) -> str:
    rows = ", ".join(f'("{t}", NAMEOF([{t}]), 0)' for t in targets)
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource =\n"
            f"\t\t\t\t{{ {rows} }}\n")


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def _text(tmp_path: Path, tables: dict[str, str], *args: str) -> str:
    model = _model(tmp_path, tables)
    code, out, err = run_cli("check", str(model), "--select",
                             "measures-in-fact-tables", "--no-config", *args)
    assert code in (0, 1), err
    return out


def test_an_internal_name_is_advisory_and_carries_no_tag(tmp_path):
    """PA22/PA23: the reference's internal tokens are the default."""
    out = _text(tmp_path, {"Sales": _fact("Sales", ["Orders related"], 1)})
    assert "ADVISORY" in out, out
    assert "Sales[Orders related]" in out, out
    # an internal-name hit adds no tag: no bracket group
    assert "Sales[Orders related] [" not in out, out


def test_the_advisory_tags_follow_the_reference(tmp_path):
    """PA23: 'Foo helper' is diagnostic, not helper."""
    out = _text(tmp_path, {"Sales": _fact("Sales", ["Foo helper"], 1)})
    assert "[diagnostic]" in out, out
    assert "[helper]" not in out, out


def test_the_tag_order(tmp_path):
    """PA23: hidden, test, helper, diagnostic, lowercase."""
    out = _text(tmp_path, {"Sales": _fact("Sales", ["-helper Test count"], 1)})
    assert "[-helper Test count] [helper, diagnostic]" in out, out


def test_a_visible_measure_without_a_tag_is_a_warning(tmp_path):
    """PA23: the other side of the rule."""
    out = _text(tmp_path, {"Sales": _fact("Sales", ["Revenue"], 1)})
    assert "Found 1 USER-FACING measures in fact tables" in out, out
    assert "   Table: Sales" in out, out
    assert "      - Revenue" in out, out


def test_the_surfaced_measure_is_marked(tmp_path):
    """PA39: a field parameter that surfaces the measure says so."""
    out = _text(tmp_path, {
        "Sales": _fact("Sales", ["Revenue"], 1),
        "x-Selector 1": _axis("x-Selector 1", ["Revenue"], 9),
    })
    assert "      - Revenue (IN x-Selector!)" in out, out


def test_the_advisory_block(tmp_path):
    """PA39: the advisory block and its recommended actions."""
    out = _text(tmp_path, {"Sales": _fact("Sales", ["Foo helper"], 1)})
    assert "ADVISORY: Found 1 hidden/diagnostic measures in fact tables" in out, out
    assert "   • Sales[Foo helper] [diagnostic]" in out, out
    assert "   Recommended actions:" in out, out
    assert "   - Move diagnostic measures to 'Diagnostic Measures' table" in out, out
    assert "   - Delete test measures (leftover from development)" in out, out
    assert "   - Priority: P2 (cleanup when convenient, not urgent)" in out, out


def test_a_fact_without_measures_says_so(tmp_path):
    """PA39: the all-clear line."""
    out = _text(tmp_path, {"Sales": _fact("Sales", [], 1)})
    assert "No measures in fact tables" in out, out


def test_the_internal_tokens_stay_configurable(tmp_path):
    """PA22: the option still overrides the default."""
    model = _model(tmp_path, {"Sales": _fact("Sales", ["Orders related"], 1)})
    cfg = {"rules": {"measures-in-fact-tables": {
        "internal_name_tokens": []}}}
    code, payload = run_check(model, "measures-in-fact-tables", config=cfg,
                               strict=True)
    assert code == 1
    found = violations(payload)
    assert len(found) == 1 and found[0]["severity"] == "warning", found
