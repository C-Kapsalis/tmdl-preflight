"""Output formats and the stats command."""

from __future__ import annotations

import json
import re

from tmdl_preflight.cli import main


def _break_lineage(definition):
    products = (definition / "tables" / "_Products.tmdl").read_text(encoding="utf-8")
    tag = re.search(r"lineageTag:\s*(\S+)", products).group(1)
    stores_file = definition / "tables" / "_Stores.tmdl"
    stores = stores_file.read_text(encoding="utf-8")
    old = re.search(r"lineageTag:\s*(\S+)", stores).group(1)
    stores_file.write_text(stores.replace(old, tag, 1), encoding="utf-8")


def test_text_prints_scanned_summary(project, capsys):
    assert main(["check", str(project)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert any(l.startswith("scanned: 1 model, 6 tables,") for l in lines)
    assert lines[-1].startswith("tmdl-preflight: 0 error(s)")


def test_json_has_scanned_and_legacy_fields(project, definition, capsys):
    _break_lineage(definition)
    assert main(["check", str(project), "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) >= {"summary", "fixes", "violations", "scanned"}
    assert payload["scanned"]["tables"] == 6 and payload["scanned"]["measures"] == 6
    assert payload["scanned"]["relationships"] == 4
    v = payload["violations"][0]
    assert {"rule", "severity", "message", "file", "line", "object", "fixable"} <= set(v)
    assert v["path"] == "BikeShop.SemanticModel/definition/tables/_Stores.tmdl"


def test_json_flag_is_alias(project, capsys):
    main(["check", str(project), "--json"])
    a = json.loads(capsys.readouterr().out)
    main(["check", str(project), "--format", "json"])
    assert json.loads(capsys.readouterr().out) == a


def test_json_conflicting_format_exits_two(project, capsys):
    assert main(["check", str(project), "--json", "--format", "sarif"]) == 2


def test_github_format(project, definition, capsys):
    _break_lineage(definition)
    assert main(["check", str(project), "--format", "github"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("::error file=")
    assert ",line=3,title=M003 lineage-duplicates::" in out[0]
    assert out[-1].startswith("tmdl-preflight: 1 error(s)")


def test_sarif_format(project, definition, capsys):
    _break_lineage(definition)
    assert main(["check", str(project), "--format", "sarif"]) == 1
    sarif = json.loads(capsys.readouterr().out)
    assert sarif["version"] == "2.1.0" and "$schema" in sarif
    run = sarif["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "tmdl-preflight"
    assert {r["id"] for r in driver["rules"]} >= {"M003", "D004", "B004"}
    result = run["results"][0]
    assert result["ruleId"] == "M003" and result["level"] == "error"
    assert driver["rules"][result["ruleIndex"]]["id"] == "M003"
    loc = result["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"].endswith("tables/_Stores.tmdl")
    assert loc["region"]["startLine"] == 3
    assert "\\" not in loc["artifactLocation"]["uri"]


def test_sarif_clean_run_has_empty_results(project, capsys):
    assert main(["check", str(project), "--format", "sarif"]) == 0
    assert json.loads(capsys.readouterr().out)["runs"][0]["results"] == []


def test_markdown_format(project, definition, capsys):
    _break_lineage(definition)
    assert main(["check", str(project), "--format", "markdown"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("## tmdl-preflight")
    assert "| error | M003 |" in out


def test_stats_text_and_json(project, capsys):
    assert main(["stats", str(project)]) == 0
    text = capsys.readouterr().out
    assert re.search(r"^tables\s+6$", text, re.M)
    assert main(["stats", str(project), "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["measures"] == 6 and stats["field_parameters"] == 1
    assert stats["partitions"] == {"calculated": 2, "m": 4}
    assert stats["inactive_relationships"] == 1


def test_stats_missing_path_exits_two(tmp_path, capsys):
    assert main(["stats", str(tmp_path / "nope")]) == 2
