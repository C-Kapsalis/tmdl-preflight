"""Baselines: record, check against, update; refusal cases."""

from __future__ import annotations

import json
import re

from tmdl_preflight.baseline import BASELINE_FILENAME
from tmdl_preflight.cli import main


def _strip_formats(definition, names=("Units Sold", "Orders #")):
    f = definition / "tables" / "Sales Measures.tmdl"
    text = f.read_text(encoding="utf-8")
    for name in names:
        text = re.sub(
            rf"(\tmeasure '{re.escape(name)}' = [^\n]*\n)\t\tformatString: [^\n]*\n",
            r"\1",
            text,
        )
    f.write_text(text, encoding="utf-8")


def _baseline(project):
    return json.loads((project / BASELINE_FILENAME).read_text(encoding="utf-8"))


def test_record_then_check_passes_until_something_new(project, definition, capsys):
    _strip_formats(definition, ("Units Sold",))
    assert main(["baseline", str(project)]) == 0
    entries = _baseline(project)["entries"]
    assert entries == [{
        "rule": "S001",
        "path": "BikeShop.SemanticModel/definition/tables/Sales Measures.tmdl",
        "object": "Sales Measures[Units Sold]",
        "count": 1,
    }]
    assert "line" not in entries[0]
    capsys.readouterr()

    baseline = str(project / BASELINE_FILENAME)
    assert main(["check", str(project), "--json", "--baseline", baseline]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["violations"] == [] and payload["summary"]["baselined"] == 1

    # a new violation (an error) is reported and fails the run
    f = definition / "tables" / "Sales Measures.tmdl"
    f.write_text(f.read_text(encoding="utf-8").replace(
        "SUM(Sales[net_amount])", "SUM(Gone[net_amount])"), encoding="utf-8")
    assert main(["check", str(project), "--json", "--baseline", baseline]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert [v["rule"] for v in payload["violations"]] == ["D004"]


def test_baseline_is_line_independent(project, definition, capsys):
    _strip_formats(definition, ("Units Sold",))
    main(["baseline", str(project)])
    f = definition / "tables" / "Sales Measures.tmdl"
    f.write_text("\n\n" + f.read_text(encoding="utf-8"), encoding="utf-8")  # shift lines
    capsys.readouterr()
    assert main(["check", str(project), "--baseline", str(project / BASELINE_FILENAME)]) == 0


def test_fixed_entries_are_reported_and_update_only_shrinks(project, definition, capsys):
    _strip_formats(definition)
    main(["baseline", str(project)])
    assert len(_baseline(project)["entries"]) == 2
    # repair one of the two
    f = definition / "tables" / "Sales Measures.tmdl"
    f.write_text(f.read_text(encoding="utf-8").replace(
        "\tmeasure 'Orders #' = DISTINCTCOUNT(Sales[order_id])\n",
        "\tmeasure 'Orders #' = DISTINCTCOUNT(Sales[order_id])\n\t\tformatString: #,0\n"),
        encoding="utf-8")
    capsys.readouterr()
    main(["check", str(project), "--baseline", str(project / BASELINE_FILENAME)])
    assert "baseline: fixed S001" in capsys.readouterr().out

    # a new violation appears; --update must not accept it
    f.write_text(f.read_text(encoding="utf-8").replace("\t\tformatString: $ #,0.00\n", "", 1),
                 encoding="utf-8")
    assert main(["baseline", str(project), "--update"]) == 0
    objs = [e["object"] for e in _baseline(project)["entries"]]
    assert objs == ["Sales Measures[Units Sold]"]
    assert main(["baseline", str(project), "--update", "--accept-new"]) == 0
    assert len(_baseline(project)["entries"]) == 2


def test_refuses_partial_runs(project, capsys):
    assert main(["baseline", str(project), "--select", "S001"]) == 2
    assert "full run" in capsys.readouterr().err


def test_refuses_runs_with_parse_errors(project, definition, capsys):
    (definition / "tables" / "Broken.tmdl").write_text("not a table\n", encoding="utf-8")
    assert main(["baseline", str(project)]) == 2
    assert "M002" in capsys.readouterr().err
    assert not (project / BASELINE_FILENAME).exists()


def test_refuses_to_overwrite(project, capsys):
    assert main(["baseline", str(project)]) == 0
    assert main(["baseline", str(project)]) == 2
    assert "--update" in capsys.readouterr().err


def test_non_baselinable_rules_are_never_recorded(project, definition, capsys):
    products = (definition / "tables" / "_Products.tmdl").read_text(encoding="utf-8")
    tag = re.search(r"lineageTag:\s*(\S+)", products).group(1)
    stores = definition / "tables" / "_Stores.tmdl"
    text = stores.read_text(encoding="utf-8")
    old = re.search(r"lineageTag:\s*(\S+)", text).group(1)
    stores.write_text(text.replace(old, tag, 1), encoding="utf-8")
    assert main(["baseline", str(project)]) == 0
    assert _baseline(project)["entries"] == []
    assert "can never be baselined" in capsys.readouterr().out
    assert main(["check", str(project), "--baseline", str(project / BASELINE_FILENAME)]) == 1


def test_hand_added_entry_for_non_baselinable_rule_is_stale(project, capsys):
    (project / BASELINE_FILENAME).write_text(json.dumps({"entries": [
        {"rule": "M003", "path": "x", "object": "y", "count": 1},
        {"rule": "Z999", "path": "x", "object": "y", "count": 1},
    ]}), encoding="utf-8")
    main(["check", str(project), "--json", "--baseline", str(project / BASELINE_FILENAME)])
    stale = json.loads(capsys.readouterr().out)["baseline"]["stale"]
    assert {s["rule"] for s in stale} == {"M003", "Z999"}


def test_missing_or_bad_baseline_exits_two(project, capsys):
    assert main(["check", str(project), "--baseline", str(project / "nope.json")]) == 2
    (project / "bad.json").write_text("{}", encoding="utf-8")
    assert main(["check", str(project), "--baseline", str(project / "bad.json")]) == 2
