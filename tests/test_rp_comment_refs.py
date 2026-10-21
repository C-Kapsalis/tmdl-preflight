"""``comment-refs`` as a gate: the counts against the committed floor.

A comment that cites an issue (`#365`) instead of explaining the model rots.
The floor file records how many references each model and each comment class
already carries; a rise above the floor fails, a fall prints a tighten hint,
and tightening only ever lowers.

The gate reads the whole scan root, not only the model definition folders: a
``*.tmdl`` outside a model is keyed by the folder it sits in. In a git work
tree only tracked files are counted.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli, run_check, violations

TREE = "rp_comment_refs"
FLOORS = "tests/baselines/comment_issue_ref_floors.json"


def _tree(stand_in) -> Path:
    return stand_in(TREE)


def _floors(tmp_path: Path, data: dict) -> Path:
    f = tmp_path / "floors.json"
    f.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# RP-3: the gate
# ---------------------------------------------------------------------------


def test_a_rise_above_the_floor_fails(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = tmp_path / "floors.json"
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors))
    assert code == 1
    assert out.splitlines() == [
        "❌ issue/PR references in TMDL comments ROSE above the committed floor "
        "in 5 model/class(es):",
        "   loose [inline]: 0 -> 1",
        "   shop_a/Growth.SemanticModel [description]: 0 -> 1",
        "   shop_a/Growth.SemanticModel [inline]: 0 -> 2",
        "   shop_b/Growth.SemanticModel [description]: 0 -> 1",
        "   shop_b/Growth.SemanticModel [inline]: 0 -> 6",
        "",
        "   Offending lines (new refs are among these; comments carry the mechanism, "
        "the commit carries the issue):",
        "   loose/extra.tmdl:1  [inline]  expression X = 1 // ticket #99",
        "   shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:4  [description]  "
        "/// see #45 for why",
        "   shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:5  [inline]  "
        "measure Revenue = SUM(Sales[amount]) -- #12 note",
        "   shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:15  [inline]  "
        "RETURN a + b // PR #7",
        "   shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:4  [description]  "
        "/// see #45 for why",
        "   shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:5  [inline]  "
        "measure Revenue = SUM(Sales[amount]) -- #12 note",
        "   shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:15  [inline]  "
        "RETURN a + b // PR #7",
        "   shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:43  [inline]  "
        'measure Extra = "text -- #400" & "#1E90FF" /* block #401',
        "   shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:44  [inline]  "
        "still #402 */ & 1 -- tail #403 and #404",
        "   shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:44  [inline]  "
        "still #402 */ & 1 -- tail #403 and #404",
        "   shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:44  [inline]  "
        "still #402 */ & 1 -- tail #403 and #404",
        "",
        f"   Fix the comment, or (human edit, justified in the PR) raise {floors}.",
    ]


def test_no_rise_passes_and_names_the_classes_below_their_floor(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {
        "loose": {"description": 0, "inline": 1},
        "shop_a/Growth.SemanticModel": {"description": 1, "inline": 5},
        "shop_b/Growth.SemanticModel": {"description": 1, "inline": 6},
        "gone/Old.SemanticModel": {"description": 3, "inline": 0},
    })
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors))
    assert code == 0
    assert out.splitlines() == [
        "✅ comment issue-ref ratchet: 11 reference(s) across 3 model(s), none above floor",
        "   below floor — tighten with --tighten:",
        "   gone/Old.SemanticModel [description]: 3 -> 0",
        "   shop_a/Growth.SemanticModel [inline]: 5 -> 2",
    ]


# ---------------------------------------------------------------------------
# RP-4: a floor key never borrows another model's floor
# ---------------------------------------------------------------------------


def test_a_floor_key_never_borrows_another_models_floor(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {
        "shop_a/Growth.SemanticModel": {"description": 9, "inline": 9},
        "shop_b/Growth.SemanticModel": {"description": 0, "inline": 0},
    })
    code, out, _err = run_cli("comment-refs", str(tree / "shop_b"), "--floors", str(floors))
    assert code == 1
    assert "[description]: 0 -> 1" in out
    assert "[description]: 0 -> 1" in out and "-> 9" not in out


def test_the_floor_key_matches_with_or_without_the_suffix(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {
        "loose": {"description": 0, "inline": 1},
        "shop_a/Growth": {"description": 1, "inline": 2},
        "shop_b/Growth.SemanticModel": {"description": 1, "inline": 6},
    })
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors))
    assert code == 0
    assert "none above floor" in out


def test_an_ambiguous_floor_key_is_not_used(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {
        "Growth.SemanticModel": {"description": 9, "inline": 9},
    })
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors))
    assert code == 1
    assert "shop_a/Growth.SemanticModel [description]: 0 -> 1" in out


def test_an_ambiguous_floor_key_is_named(stand_in, tmp_path):
    """Two keys could name the model; the run says so and uses neither."""
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {
        "shop_a/Growth.SemanticModel": {"description": 9, "inline": 9},
        "other/Growth.SemanticModel": {"description": 9, "inline": 9},
    })
    code, out, _err = run_cli("comment-refs", str(tree / "shop_a"), "--floors", str(floors))
    assert code == 1
    assert "could name" in out
    assert "none of them was used" in out


def test_the_rule_never_borrows_another_models_floor(stand_in, tmp_path):
    """S004 reads the same floors file and matches the keys the same way."""
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {
        "shop_a/Growth.SemanticModel": {"description": 9, "inline": 9},
        "shop_b/Growth.SemanticModel": {"description": 9, "inline": 9},
    })
    code, payload = run_check(tree / "shop_b", "comment-ticket-refs", config={
        "rules": {"comment-ticket-refs": {"floors": str(floors)}}})
    assert code == 1
    assert violations(payload)


# ---------------------------------------------------------------------------
# RP-5 / RP-6: the tighten run
# ---------------------------------------------------------------------------


def test_tighten_keeps_an_entry_whose_key_is_spelled_differently(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {"shop_a/Growth": {"description": 1, "inline": 9}})
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors), "--tighten")
    assert code == 0
    assert "shop_a/Growth inline: 9 -> 2" in out
    data = json.loads(floors.read_text(encoding="utf-8"))
    assert data["shop_a/Growth"] == {"description": 1, "inline": 2}


def test_tighten_seeds_a_missing_floors_file(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = tmp_path / "new.json"
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors), "--tighten")
    assert code == 0
    assert out.splitlines() == ["no floors file yet — seeding from the current scan"]
    assert floors.read_text(encoding="utf-8") == (
        '{\n'
        '  "loose": {\n'
        '    "description": 0,\n'
        '    "inline": 1\n'
        '  },\n'
        '  "shop_a/Growth.SemanticModel": {\n'
        '    "description": 1,\n'
        '    "inline": 2\n'
        '  },\n'
        '  "shop_b/Growth.SemanticModel": {\n'
        '    "description": 1,\n'
        '    "inline": 6\n'
        '  }\n'
        '}\n')


def test_tighten_prints_nothing_to_tighten_when_nothing_moved(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {
        "loose": {"description": 0, "inline": 1},
        "shop_a/Growth.SemanticModel": {"description": 1, "inline": 2},
        "shop_b/Growth.SemanticModel": {"description": 1, "inline": 6},
    })
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors), "--tighten")
    assert code == 0
    assert out.splitlines() == ["nothing to tighten"]


# ---------------------------------------------------------------------------
# RP-7: the listing
# ---------------------------------------------------------------------------


def test_list_prints_one_line_per_reference(stand_in):
    tree = _tree(stand_in)
    code, out, _err = run_cli("comment-refs", str(tree), "--list")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "loose/extra.tmdl:1  [inline]  expression X = 1 // ticket #99"
    assert lines[-3] == "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:44  " \
                        "[inline]  still #402 */ & 1 -- tail #403 and #404"
    assert lines[-2] == ""
    assert lines[-1] == "11 reference(s) in 3 model(s)"


def test_list_takes_a_prefix(stand_in):
    tree = _tree(stand_in)
    code, out, _err = run_cli("comment-refs", str(tree), "--list", "shop_a")
    assert code == 0
    lines = out.splitlines()
    assert all("shop_a" in ln for ln in lines if ln and not ln.startswith("3 "))
    assert lines[-1] == "3 reference(s) in 1 model(s)"


def test_list_wins_over_tighten(stand_in, tmp_path):
    tree = _tree(stand_in)
    floors = _floors(tmp_path, {"shop_a/Growth.SemanticModel": {"description": 1, "inline": 9}})
    code, out, _err = run_cli("comment-refs", str(tree), "--floors", str(floors),
                              "--list", "--tighten")
    assert code == 0
    assert "reference(s) in" in out


# ---------------------------------------------------------------------------
# RP-25: the scan scope
# ---------------------------------------------------------------------------


def test_a_file_outside_a_model_is_keyed_by_its_folder(stand_in):
    tree = _tree(stand_in)
    code, out, _err = run_cli("comment-refs", str(tree), "--list")
    assert code == 0
    assert "loose/extra.tmdl:1  [inline]" in out


def test_an_untracked_file_with_a_reference_is_not_counted(stand_in, tmp_path):
    tree = _tree(stand_in)
    subprocess.run(["git", "init", "-q", str(tree)], check=True)
    subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tree), "-c", "user.name=T", "-c", "user.email=t@e.com",
                    "commit", "-q", "-m", "base"], check=True)
    (tree / "untracked.tmdl").write_text("expression Y = 1 // ticket #500\n", encoding="utf-8")
    code, out, _err = run_cli("comment-refs", str(tree), "--list")
    assert code == 0
    assert "untracked.tmdl" not in out


# ---------------------------------------------------------------------------
# RP-26: an unclosed quote does not hide a comment
# ---------------------------------------------------------------------------


def test_an_unclosed_quote_does_not_hide_a_comment(tmp_path):
    root = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
    root.mkdir(parents=True)
    (root / "Sales.tmdl").write_text(
        "table 'Sales'\n\tlineageTag: 00000000-0000-0000-0000-000000000001\n\n"
        '\tmeasure X = "open -- #405\n', encoding="utf-8")
    code, out, _err = run_cli("comment-refs", str(tmp_path), "--list")
    assert code == 0
    assert "1 reference(s) in 1 model(s)" in out


def test_a_byte_order_mark_keeps_a_description_a_description(tmp_path):
    root = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
    root.mkdir(parents=True)
    (root / "Sales.tmdl").write_bytes(
        "﻿table 'Sales'\n\tlineageTag: 00000000-0000-0000-0000-000000000001\n\n"
        "\t/// see #45 for why\n".encode("utf-8"))
    code, out, _err = run_cli("comment-refs", str(tmp_path), "--list")
    assert code == 0
    assert "[description]" in out
    assert "[inline]" not in out
