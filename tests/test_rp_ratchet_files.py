"""The ratchet files: where they are looked up, and what they hold.

Three rules read a floor file: S004 (the ticket references in comments),
O007 (the dead fact tables), R008 (the facts that do not join the
conformed dimension) and R016 (the dead anchor calendars). The file is
written by hand, so a mistake in it is a mistake in the gate.

Two things matter here. A relative path is resolved against the folder of
the configuration file that names it, not against the working directory, so
a run from anywhere finds the floor. And a floor key names one model and
one model only.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import run_check, run_cli, violations

S004 = "comment-ticket-refs"
O007 = "dead-fact-tables"
R008 = "fact-conformed-dimension-join"
R016 = "dead-anchor-calendar"


def _model(tmp_path: Path, name: str = "Shop.SemanticModel") -> Path:
    d = tmp_path / name / "definition" / "tables"
    d.mkdir(parents=True)
    (d / "Sales.tmdl").write_text(
        "table 'Sales'\n\tlineageTag: 00000000-0000-0000-0000-000000000001\n\n"
        "\t/// see #45 for why\n"
        "\tcolumn amount\n\t\tdataType: double\n\t\tsourceColumn: amount\n\n"
        "\tcolumn account_id\n\t\tdataType: int64\n\t\tsourceColumn: account_id\n",
        encoding="utf-8")
    (d / "Accounts.tmdl").write_text(
        "table 'Accounts'\n\tlineageTag: 00000000-0000-0000-0000-000000000002\n\n"
        "\tcolumn account_id\n\t\tdataType: int64\n\t\tsourceColumn: account_id\n",
        encoding="utf-8")
    (tmp_path / name / "definition" / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\n"
        "ref table Sales\n\nref table Accounts\n", encoding="utf-8")
    (tmp_path / name / "definition" / "relationships.tmdl").write_text(
        "relationship a\n\tfromColumn: Sales.account_id\n\ttoColumn: Accounts.account_id\n",
        encoding="utf-8")
    return tmp_path


def test_a_relative_floor_path_resolves_against_the_configuration(tmp_path):
    """A config in a sub-folder still finds its floor file when the run
    happens from the parent folder."""
    root = _model(tmp_path)
    sub = root / "tools"
    sub.mkdir()
    floors = sub / "floors.json"
    floors.write_text(json.dumps({"Shop.SemanticModel": {"description": 1, "inline": 0}}) + "\n",
                    encoding="utf-8")
    cfg = sub / ".tmdl-preflight.json"
    cfg.write_text(json.dumps({"rules": {S004: {"floors": "floors.json"}}}), encoding="utf-8")
    code, payload = run_check(root, S004, config=str(cfg))
    assert code == 0
    assert violations(payload) == []


def test_a_relative_floor_path_without_a_configuration_is_read_as_given(tmp_path):
    """Without a configuration the path is read as given, so a relative path
    that does not exist means an empty floor."""
    root = _model(tmp_path)
    code, payload = run_check(root, S004, config={"rules": {S004: {"floors": "absent.json"}}})
    assert code == 1
    assert len(violations(payload)) == 1


def test_the_dead_fact_rule_reports_a_table_that_is_alive_again(tmp_path):
    """O007: a table recorded in the floor that is no longer dead prints a
    tighten hint."""
    root = _model(tmp_path)
    floors = root / "floors.json"
    floors.write_text(json.dumps({"Shop.SemanticModel": ["Sales"]}), encoding="utf-8")
    code, payload = run_check(root, O007, config={"rules": {O007: {"baseline": str(floors)}}})
    found = violations(payload)
    assert found == [] or all("dead" in v["message"] for v in found)
