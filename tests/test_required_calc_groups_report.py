"""The required calculation groups: the inventory and the summary.

* PA36: the per-model summary of the required calculation groups.
* PA37: the z-Selector inventory (verbose only, never a finding).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations

TAG = "11111111-1111-4111-8111-{:012d}"
RULE = "required-calc-groups"


def _table(name: str, columns: list[str], measures: list[str], tag: int) -> str:
    body = f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    for i, c in enumerate(columns):
        body += (f"\tcolumn '{c}'\n\t\tdataType: string\n\t\tlineageTag: "
                 + TAG.format(tag + 100 + i) + "\n\t\tsourceColumn: " + c + "\n")
    for i, m in enumerate(measures):
        body += (f"\tmeasure '{m}' = SELECTEDMEASURENAME()\n\t\tlineageTag: "
                 + TAG.format(tag + 200 + i) + "\n")
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


def test_the_summary_names_the_missing_group(tmp_path):
    """PA36: the counts and the two lists."""
    model = _model(tmp_path, {
        "z-Selector Format": _table("z-Selector Format", ["Value1"], ["Format"], 1),
    })
    code, out, err = run_cli("check", str(model), "--select", RULE, "--no-config")
    assert code == 1, err
    assert "Required calculation groups: 2" in out, out
    assert "Present: 1" in out, out
    assert "Missing: 1" in out, out
    assert "  - z-Selector Format" in out, out
    assert "  - z-Selector Time Intelligence Function" in out, out
    assert "These are critical for dynamic formatting and time intelligence" in out, out


def test_the_inventory_is_reported(tmp_path):
    """PA37: the z-Selector tables and their columns."""
    model = _model(tmp_path, {
        "z-Selector Format": _table("z-Selector Format", ["Value1", "Value2"],
                                    ["Format", "Plain"], 1),
    })
    code, out, err = run_cli("check", str(model), "--select", RULE, "--no-config")
    assert code == 1, err
    assert "Total z-Selector tables: 1" in out, out
    assert "z-Selector Format" in out, out
    assert "Value1" in out and "Value2" in out, out
    assert "SELECTEDMEASURENAME" in out, out


def test_the_inventory_is_never_a_finding(tmp_path):
    """PA37: the inventory does not add findings."""
    model = _model(tmp_path, {
        "z-Selector Format": _table("z-Selector Format", ["Value1"], ["Format"], 1),
        "z-Selector Time Intelligence Function": _table(
            "z-Selector Time Intelligence Function", ["Value1"], ["YTD"], 2),
    })
    code, payload = run_check(model, RULE)
    assert code == 0, payload
    assert violations(payload) == []


def test_the_disabled_rule_says_so(tmp_path):
    """PA36: the skip message names the policy switch."""
    model = _model(tmp_path, {
        "z-Selector Format": _table("z-Selector Format", ["Value1"], ["Format"], 1),
    })
    cfg = {"rules": {RULE: {"format_selector": False,
                            "time_intelligence_selector": False}}}
    code, out, err = run_cli("check", str(model), "--select", RULE,
                             "--config", str(_write(model, cfg)))
    assert code == 0, err
    assert "Calculation group validation disabled in policy" in out, out


def _write(model: Path, cfg: dict) -> Path:
    import json
    target = model.parent.parent / "cfg.json"
    target.write_text(json.dumps(cfg), encoding="utf-8")
    return target
