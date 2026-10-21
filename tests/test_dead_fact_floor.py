"""The dead-fact-table floor: how it is captured and how it is reported.

* PA28: a capture writes the floor file and says what it wrote.
* PA29: the tighten hint covers every floor entry that is no longer dead,
  including a model that is not there any more.
* PA30: the failure names every new dead fact table beyond the floor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations

TAG = "11111111-1111-4111-8111-{:012d}"
RULE = "dead-fact-tables"


def _fact(name: str, tag: int, measures: list[str] = ()) -> str:
    body = f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    body += ("\tcolumn amount\n\t\tdataType: double\n\t\tlineageTag: "
             + TAG.format(tag + 50) + "\n\t\tsourceColumn: amount\n\n")
    for i, m in enumerate(measures):
        body += (f"\tmeasure '{m}' = SUM({name}[amount])\n\t\tlineageTag: "
                 + TAG.format(tag + 100 + i) + "\n")
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = x\n"
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


def test_the_capture_writes_the_floor_file(tmp_path):
    """PA28: the capture command writes the file and says so."""
    model = _model(tmp_path, {
        "Sales": _fact("Sales", 1, ["Revenue"]),
        "Returns": _fact("Returns", 2),
    })
    floor = tmp_path / "floor.json"
    code, out, err = run_cli("dead-facts", str(model), "--capture", str(floor))
    assert code == 0, err
    assert ("[dead-fact-table floor] captured 1 entries across 1 models -> "
            f"{floor}") in out, out
    data = json.loads(floor.read_text(encoding="utf-8"))
    assert data == {"Shop.SemanticModel": ["Returns"]}, data
    raw = floor.read_bytes()
    assert raw.endswith(b"\n")
    assert raw == json.dumps(data, indent=2, sort_keys=True).encode() + b"\n"


def test_the_capture_leaves_a_clean_model_out(tmp_path):
    """PA28: a model with no dead table is not in the file."""
    model = _model(tmp_path, {"Sales": _fact("Sales", 1, ["Revenue"])})
    floor = tmp_path / "floor.json"
    code, out, err = run_cli("dead-facts", str(model), "--capture", str(floor))
    assert code == 0, err
    assert floor.read_text(encoding="utf-8") == "{}\n"
    assert "captured 0 entries across 0 models" in out, out


def test_the_check_passes_after_a_capture(tmp_path):
    """PA28: the round trip."""
    model = _model(tmp_path, {
        "Sales": _fact("Sales", 1, ["Revenue"]),
        "Returns": _fact("Returns", 2),
    })
    floor = tmp_path / "floor.json"
    code, _out, err = run_cli("dead-facts", str(model), "--capture", str(floor))
    assert code == 0, err
    cfg = {"rules": {RULE: {"baseline": str(floor)}}}
    code, payload = run_check(model, RULE, config=cfg)
    assert code == 0, payload
    assert violations(payload) == []


def test_a_missing_floor_file_is_an_error(tmp_path):
    """PA28: the check still refuses a floor that is not there."""
    model = _model(tmp_path, {"Returns": _fact("Returns", 2)})
    cfg = {"rules": {RULE: {"baseline": str(tmp_path / "nope.json")}}}
    code, payload = run_check(model, RULE, config=cfg)
    assert code == 1
    assert violations(payload)


def test_the_tighten_hint_covers_a_model_that_is_gone(tmp_path):
    """PA29: a floor entry for a model that no longer exists."""
    model = _model(tmp_path, {"Sales": _fact("Sales", 1, ["Revenue"])})
    floor = tmp_path / "floor.json"
    floor.write_text(json.dumps({"Gone.SemanticModel": ["Returns"]}, indent=2),
                     encoding="utf-8")
    cfg = {"rules": {RULE: {"baseline": str(floor)}}}
    code, payload = run_check(model, RULE, config=cfg)
    text = "\n".join(payload.get("notes") or [])
    assert "[dead-fact-table floor] entries no longer dead" in text, text
    assert "  Gone.SemanticModel: Returns" in text, text


def test_a_floor_key_without_the_suffix_is_the_same_model(tmp_path):
    """PA29: the key of a model compares with or without the suffix."""
    model = _model(tmp_path, {"Returns": _fact("Returns", 2)})
    floor = tmp_path / "floor.json"
    floor.write_text(json.dumps({"Shop": ["Returns"]}, indent=2), encoding="utf-8")
    cfg = {"rules": {RULE: {"baseline": str(floor)}}}
    code, payload = run_check(model, RULE, config=cfg)
    assert code == 0, payload
    assert violations(payload) == []
    text = "\n".join(payload.get("notes") or [])
    assert "no longer dead" not in text, text


def test_the_failure_names_every_new_dead_table(tmp_path):
    """PA30: the summary of the growth."""
    model = _model(tmp_path, {
        "Sales": _fact("Sales", 1, ["Revenue"]),
        "Returns": _fact("Returns", 2),
        "Shipments": _fact("Shipments", 3),
    })
    floor = tmp_path / "floor.json"
    floor.write_text(json.dumps({"Shop.SemanticModel": ["Returns"]}, indent=2),
                     encoding="utf-8")
    cfg = {"rules": {RULE: {"baseline": str(floor)}}}
    code, payload = run_check(model, RULE, config=cfg)
    assert code == 1
    text = "\n".join(payload.get("notes") or [])
    assert ("1 NEW dead fact table(s) beyond the committed floor — no measure "
            "reads them; either finish the drop or accept them into "
            f"{floor} with a reason:") in text, text
    assert "  Shop.SemanticModel: Shipments" in text, text
