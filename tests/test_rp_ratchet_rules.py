"""The ratchet files of O007, R008 and R016.

Three rules gate a backlog: the dead fact tables (O007), the facts that do
not join the conformed dimension (R008) and the anchor calendars that reach
nothing (R016). Each reads a floor file that records what is already
accepted; only growth fails.

The floor files are written by hand, so the tool can write them for the
team: ``baseline --capture-floors`` records the current findings in the
shape each rule reads back.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import run_check, run_cli, violations

O007 = "dead-fact-tables"
R008 = "fact-conformed-dimension-join"
R016 = "dead-anchor-calendar"


def _model(tmp_path: Path) -> Path:
    """A model with a fact that reads nothing (dead), a fact that does not
    join the accounts table, and an anchor calendar that reaches nothing."""
    d = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
    d.mkdir(parents=True)
    (d / "Sales.tmdl").write_text(
        "table 'Sales'\n\tlineageTag: 00000000-0000-0000-0000-000000000001\n\n"
        "\tmeasure Revenue = SUM(Sales[amount])\n\t\tlineageTag: "
        "00000000-0000-0000-0000-000000000011\n\n"
        "\tcolumn amount\n\t\tdataType: double\n\t\tsourceColumn: amount\n\n"
        "\tcolumn account_id\n\t\tdataType: int64\n\t\tsourceColumn: account_id\n\n"
        "\tpartition 'Sales' = m\n\t\tmode: import\n\t\tsource = ```\n"
        "\t\t\tlet x = 1 in x\n\t\t\t```\n",
        encoding="utf-8")
    (d / "Ledger.tmdl").write_text(
        "table 'Ledger'\n\tlineageTag: 00000000-0000-0000-0000-000000000002\n\n"
        "\tcolumn amount\n\t\tdataType: double\n\t\tsourceColumn: amount\n\n"
        "\tcolumn account_id\n\t\tdataType: int64\n\t\tsourceColumn: account_id\n\n"
        "\tpartition 'Ledger' = m\n\t\tmode: import\n\t\tsource = ```\n"
        "\t\t\tlet x = 1 in x\n\t\t\t```\n",
        encoding="utf-8")
    (d / "Accounts.tmdl").write_text(
        "table 'Accounts'\n\tlineageTag: 00000000-0000-0000-0000-000000000003\n\n"
        "\tcolumn account_id\n\t\tdataType: int64\n\t\tsourceColumn: account_id\n\n"
        "\tpartition 'Accounts' = m\n\t\tmode: import\n\t\tsource = ```\n"
        "\t\t\tlet x = 1 in x\n\t\t\t```\n",
        encoding="utf-8")
    (d / "__First Order Calendar.tmdl").write_text(
        "table '__First Order Calendar'\n\tlineageTag: "
        "00000000-0000-0000-0000-000000000004\n\n"
        "\tcolumn date\n\t\tdataType: dateTime\n\t\tsourceColumn: date\n",
        encoding="utf-8")
    (tmp_path / "Shop.SemanticModel" / "definition" / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\n"
        "ref table Sales\n\nref table Ledger\n\nref table Accounts\n\n"
        "ref table __First Order Calendar\n", encoding="utf-8")
    (tmp_path / "Shop.SemanticModel" / "definition" / "relationships.tmdl").write_text(
        "relationship a\n\tfromColumn: Sales.account_id\n\ttoColumn: Accounts.account_id\n",
        encoding="utf-8")
    return tmp_path


def test_the_dead_fact_rule_reports_a_table_that_is_alive_again(tmp_path):
    """O007: a table recorded in the floor that is no longer dead prints one
    hint naming the model and the table."""
    root = _model(tmp_path)
    floors = root / "floors.json"
    floors.write_text(json.dumps({"Shop.SemanticModel": ["Sales"]}), encoding="utf-8")
    code, payload = run_check(root, O007, config={"rules": {O007: {"baseline": str(floors)}}})
    assert code == 1
    notes = payload["notes"]
    assert any("[dead-fact-table floor] entries no longer dead" in n for n in notes), notes
    assert any("Shop.SemanticModel: Sales" in n for n in notes), notes


def test_the_anchor_calendar_rule_reads_a_floor_file(tmp_path):
    """R016: a dead anchor calendar that the floor lists is not a finding."""
    root = _model(tmp_path)
    floors = root / "floors.json"
    floors.write_text(json.dumps({"Shop.SemanticModel": ["__First Order Calendar"]}),
                      encoding="utf-8")
    code, payload = run_check(root, R016, config={"rules": {R016: {"floor": str(floors)}}})
    assert code == 0
    assert violations(payload) == []


def test_the_anchor_calendar_rule_fails_an_unlisted_calendar(tmp_path):
    root = _model(tmp_path)
    floors = root / "floors.json"
    floors.write_text(json.dumps({"Shop.SemanticModel": []}), encoding="utf-8")
    code, payload = run_check(root, R016, config={"rules": {R016: {"floor": str(floors)}}})
    assert code == 1
    assert any("__First Order Calendar" in v["message"] for v in violations(payload))


def test_an_anchor_calendar_floor_that_does_not_exist_is_an_empty_floor(tmp_path):
    """R016: a floor file that is not there accepts nothing, so the dead
    calendar is new and is reported."""
    root = _model(tmp_path)
    code, payload = run_check(root, R016, config={"rules": {R016: {
        "floor": str(tmp_path / "absent.json")}}})
    assert code == 1
    assert any("__First Order Calendar" in v["message"] for v in violations(payload))


def test_the_account_key_rule_fails_a_model_without_a_floor_entry(tmp_path):
    """R008: a model with no entry in the floor file is a finding."""
    root = _model(tmp_path)
    floors = root / "floors.json"
    floors.write_text(json.dumps({"Other.SemanticModel": []}), encoding="utf-8")
    code, payload = run_check(root, R008, config={"rules": {R008: {
        "dimension_table": "Accounts", "key_column": "account_id",
        "baseline": str(floors), "fail_without_baseline_entry": True}}})
    assert code == 1
    found = violations(payload)
    assert any("no account-key floor recorded" in v["message"] for v in found), found
    assert any("Currently flagged (2): Accounts, Ledger" in v["message"] for v in found), found


def test_the_account_key_rule_passes_a_model_with_an_empty_entry(tmp_path):
    root = _model(tmp_path)
    floors = root / "floors.json"
    floors.write_text(json.dumps({"Shop.SemanticModel": []}), encoding="utf-8")
    code, payload = run_check(root, R008, config={"rules": {R008: {
        "dimension_table": "Accounts", "key_column": "account_id",
        "baseline": str(floors), "fail_without_baseline_entry": True}}})
    # The fact that does not join is still a finding, but the missing floor
    # entry is not.
    assert not any("no account-key floor recorded" in v["message"]
                   for v in violations(payload))


def test_the_capture_writes_the_floor_file_of_the_dead_fact_tables(tmp_path):
    root = _model(tmp_path)
    floors = root / "dead.json"
    code, out, err = run_cli("baseline", str(root), "--capture-floors", O007,
                              "--output", str(floors))
    assert code == 0, err
    assert floors.read_text(encoding="utf-8") == (
        '{\n'
        '  "Shop.SemanticModel": [\n'
        '    "Accounts",\n'
        '    "Ledger"\n'
        '  ]\n'
        '}\n')
    assert "[dead-fact-table floor] captured 2 entries across 1 models" in out


def test_the_capture_writes_the_floor_file_of_the_anchor_calendars(tmp_path):
    root = _model(tmp_path)
    floors = root / "calendars.json"
    code, out, err = run_cli("baseline", str(root), "--capture-floors", R016,
                              "--output", str(floors))
    assert code == 0, err
    assert floors.read_text(encoding="utf-8") == (
        '{\n'
        '  "Shop.SemanticModel": [\n'
        '    "__First Order Calendar"\n'
        '  ]\n'
        '}\n')
    assert "[dead-anchor-calendar floor] captured 1 across 1 models" in out


def test_the_capture_writes_the_floor_file_of_the_account_keys(tmp_path):
    """R008: every scanned model gets an entry, an empty list included."""
    root = _model(tmp_path)
    floors = root / "accounts.json"
    cfg = root / ".tmdl-preflight.json"
    cfg.write_text(json.dumps({"rules": {R008: {
        "dimension_table": "Accounts", "key_column": "account_id"}}}), encoding="utf-8")
    code, out, err = run_cli("baseline", str(root), "--capture-floors", R008,
                              "--output", str(floors), "--config", str(cfg))
    assert code == 0, err
    assert floors.read_text(encoding="utf-8") == (
        '{\n'
        ' "Shop": [\n'
        '  "Accounts",\n'
        '  "Ledger"\n'
        ' ]\n'
        '}\n')


def test_the_capture_keeps_the_entries_of_the_models_it_did_not_scan(tmp_path):
    root = _model(tmp_path)
    floors = root / "accounts.json"
    floors.write_text(json.dumps({"Other": ["Old"]}, indent=1) + "\n", encoding="utf-8")
    cfg = root / ".tmdl-preflight.json"
    cfg.write_text(json.dumps({"rules": {R008: {
        "dimension_table": "Accounts", "key_column": "account_id"}}}), encoding="utf-8")
    code, out, err = run_cli("baseline", str(root), "--capture-floors", R008,
                              "--output", str(floors), "--config", str(cfg))
    assert code == 0, err
    data = json.loads(floors.read_text(encoding="utf-8"))
    assert data["Other"] == ["Old"]
    assert data["Shop"] == ["Accounts", "Ledger"]
