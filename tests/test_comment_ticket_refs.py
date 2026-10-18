"""Ticket references in TMDL comments are ratcheted (spec B-comment-ticket-refs).

A comment that cites an issue (`#365`) instead of explaining the model
rots: the reader needs the tracker to understand the DAX. Existing references
are recorded per model and class in a floors file (same shape as the
original: ``{"<folder>/<Model>.SemanticModel": {"description": n, "inline": n}}``);
a rise fails, a fall prints a tighten hint, and tightening only ever lowers.

Classes: a `///` line is a description; `--`, `//` and `/* ... */` text is
inline (a block may span lines). A reference is `#` + digits not followed by
a word character, so colours (`#FF00AA`) and names (`#Report Measures`) are
not references; text inside double-quoted strings is ignored.

No original test exercised this (the original was a script); these are the
spec's stand-in cases. The floors file is generated per test.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import run_check, run_cli, violations

RULE = "comment-ticket-refs"
KEY = "Shop.SemanticModel"


def _model(tmp_path: Path) -> Path:
    d = tmp_path / "Shop.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n\nref table Beans\n", encoding="utf-8")
    (d / "tables" / "Beans.tmdl").write_text(
        "table Beans\n"
        "\tlineageTag: 3b0d0f4e-2f6c-4b8e-9a51-6c7d8e9f0a1b\n\n"
        "\t/// Revenue, see #365\n"
        "\tmeasure Revenue = SUM(Beans[kg]) -- fixes reportinsights/DBT#12\n"
        "\t\tlineageTag: 4c1e1f5f-3a7d-4c9f-8b62-7d8e9f0a1b2c\n\n"
        "\tmeasure Label = \"text #5\" /* note\n"
        "\t\t #7 */\n"
        "\t\tformatString: #FF00AA\n"
        "\t\tlineageTag: 5d2f2a6a-4b8e-4daf-9c73-8e9f0a1b2c3d\n\n"
        "\tcolumn kg\n\t\tdataType: double\n\t\tlineageTag: 6e3a3b7b-5c9f-4eba-8d84-9f0a1b2c3d4e\n"
        "\t\tsourceColumn: kg\n",
        encoding="utf-8")
    return tmp_path


def _floors(tmp_path, data) -> Path:
    f = tmp_path / "comment_issue_ref_floors.json"
    f.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f


def test_counts_by_class(tmp_path):
    root = _model(tmp_path)
    code, out, _err = run_cli("comment-refs", str(root), "--list", "--json")
    assert code == 0
    counts = json.loads(out)["counts"][KEY]
    # description: '#365'; inline: 'DBT#12' and the block-comment '#7'.
    # Not counted: '"text #5"' (string), '#FF00AA' (colour).
    assert counts == {"description": 1, "inline": 2}


def test_rise_above_floor_fails(tmp_path):
    root = _model(tmp_path)
    floors = _floors(tmp_path, {KEY: {"description": 0, "inline": 2}})
    code, payload = run_check(root, RULE, config={"rules": {RULE: {"floors": str(floors)}}})
    assert code == 1
    found = violations(payload)
    assert len(found) == 1 and "description" in found[0]["message"]


def test_floors_at_current_pass(tmp_path):
    root = _model(tmp_path)
    floors = _floors(tmp_path, {KEY: {"description": 1, "inline": 2}})
    code, payload = run_check(root, RULE, config={"rules": {RULE: {"floors": str(floors)}}})
    assert code == 0 and violations(payload) == []


def test_tighten_only_lowers(tmp_path):
    root = _model(tmp_path)
    floors = _floors(tmp_path, {KEY: {"description": 1, "inline": 2}, "Gone.SemanticModel":
                                {"description": 0, "inline": 0}})
    beans = root / "Shop.SemanticModel/definition/tables/Beans.tmdl"
    beans.write_text(beans.read_text(encoding="utf-8").replace(" -- fixes reportinsights/DBT#12", ""),
                     encoding="utf-8")
    code, _out, _err = run_cli("comment-refs", str(root), "--floors", str(floors), "--tighten")
    assert code == 0
    data = json.loads(floors.read_text(encoding="utf-8"))
    assert data == {KEY: {"description": 1, "inline": 1}}   # lowered by 1; all-zero entry dropped
    assert list(data) == sorted(data)


def test_missing_floors_file_means_empty_floors(tmp_path):
    root = _model(tmp_path)
    code, payload = run_check(root, RULE,
                              config={"rules": {RULE: {"floors": str(tmp_path / "absent.json")}}})
    assert code == 1 and len(violations(payload)) == 2   # both classes rose above 0
