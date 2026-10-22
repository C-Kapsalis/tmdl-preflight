"""The whole comment-refs session of the golden output, byte for byte.

The session walks the whole gate: the first run with no floor file, the
listing, the seeding of the floor file, the run that passes, a hand-edited
floor file with a model that is gone, the tighten, and the run that fails
again because a floor was lowered by hand.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli

TREE = "rp_comment_refs"


def _session(tmp_path: Path, tree: Path) -> list[str]:
    floors = tmp_path / "comment_issue_ref_floors.json"
    log: list[str] = []

    def run(*argv):
        code, out, err = run_cli(*argv)
        shown = [a for a in argv[1:] if a != str(tree)]
        log.append(f"$ comment-refs" + (" " + " ".join(shown) if shown else ""))
        log.extend(out.splitlines())
        log.append(f"[exit {code}]")
        return code, out

    run("comment-refs", str(tree), "--floors", str(floors))
    run("comment-refs", str(tree), "--list")
    run("comment-refs", str(tree), "--list", "shop_a")
    run("comment-refs", str(tree), "--floors", str(floors), "--tighten")
    log.append("floors file bytes:")
    log.extend(floors.read_text(encoding="utf-8").splitlines())
    run("comment-refs", str(tree), "--floors", str(floors))

    data = json.loads(floors.read_text(encoding="utf-8"))
    data["shop_a/Growth.SemanticModel"]["inline"] = 5
    data["gone/Old.SemanticModel"] = {"description": 3, "inline": 0}
    floors.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run("comment-refs", str(tree), "--floors", str(floors))
    run("comment-refs", str(tree), "--floors", str(floors), "--tighten")
    log.append("floors file after:")
    log.extend(floors.read_text(encoding="utf-8").splitlines())
    run("comment-refs", str(tree), "--floors", str(floors), "--tighten")

    data = json.loads(floors.read_text(encoding="utf-8"))
    data["shop_b/Growth.SemanticModel"]["inline"] = 1
    floors.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run("comment-refs", str(tree), "--floors", str(floors))
    return log


def test_the_whole_session_matches_the_golden(stand_in, tmp_path):
    tree = stand_in(TREE)
    log = _session(tmp_path, tree)
    expected = [
        "$ comment-refs --floors " + str(tmp_path / "comment_issue_ref_floors.json"),
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
        "   Fix the comment, or (human edit, justified in the PR) raise "
        + str(tmp_path / "comment_issue_ref_floors.json") + ".",
        "[exit 1]",
        "$ comment-refs --list",
        "loose/extra.tmdl:1  [inline]  expression X = 1 // ticket #99",
        "shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:4  [description]  "
        "/// see #45 for why",
        "shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:5  [inline]  "
        "measure Revenue = SUM(Sales[amount]) -- #12 note",
        "shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:15  [inline]  "
        "RETURN a + b // PR #7",
        "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:4  [description]  "
        "/// see #45 for why",
        "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:5  [inline]  "
        "measure Revenue = SUM(Sales[amount]) -- #12 note",
        "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:15  [inline]  "
        "RETURN a + b // PR #7",
        "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:43  [inline]  "
        'measure Extra = "text -- #400" & "#1E90FF" /* block #401',
        "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:44  [inline]  "
        "still #402 */ & 1 -- tail #403 and #404",
        "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:44  [inline]  "
        "still #402 */ & 1 -- tail #403 and #404",
        "shop_b/Growth.SemanticModel/definition/tables/Sales.tmdl:44  [inline]  "
        "still #402 */ & 1 -- tail #403 and #404",
        "",
        "11 reference(s) in 3 model(s)",
        "[exit 0]",
        "$ comment-refs --list shop_a",
        "shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:4  [description]  "
        "/// see #45 for why",
        "shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:5  [inline]  "
        "measure Revenue = SUM(Sales[amount]) -- #12 note",
        "shop_a/Growth.SemanticModel/definition/tables/Sales.tmdl:15  [inline]  "
        "RETURN a + b // PR #7",
        "",
        "3 reference(s) in 1 model(s)",
        "[exit 0]",
        "$ comment-refs --floors " + str(tmp_path / "comment_issue_ref_floors.json") + " --tighten",
        "no floors file yet — seeding from the current scan",
        "[exit 0]",
        "floors file bytes:",
        "{",
        '  "loose": {',
        '    "description": 0,',
        '    "inline": 1',
        "  },",
        '  "shop_a/Growth.SemanticModel": {',
        '    "description": 1,',
        '    "inline": 2',
        "  },",
        '  "shop_b/Growth.SemanticModel": {',
        '    "description": 1,',
        '    "inline": 6',
        "  }",
        "}",
        "$ comment-refs --floors " + str(tmp_path / "comment_issue_ref_floors.json"),
        "✅ comment issue-ref ratchet: 11 reference(s) across 3 model(s), none above floor",
        "[exit 0]",
        "$ comment-refs --floors " + str(tmp_path / "comment_issue_ref_floors.json"),
        "✅ comment issue-ref ratchet: 11 reference(s) across 3 model(s), none above floor",
        "   below floor — tighten with --tighten:",
        "   gone/Old.SemanticModel [description]: 3 -> 0",
        "   shop_a/Growth.SemanticModel [inline]: 5 -> 2",
        "[exit 0]",
        "$ comment-refs --floors " + str(tmp_path / "comment_issue_ref_floors.json") + " --tighten",
        "gone/Old.SemanticModel description: 3 -> 0",
        "shop_a/Growth.SemanticModel inline: 5 -> 2",
        "[exit 0]",
        "floors file after:",
        "{",
        '  "loose": {',
        '    "description": 0,',
        '    "inline": 1',
        "  },",
        '  "shop_a/Growth.SemanticModel": {',
        '    "description": 1,',
        '    "inline": 2',
        "  },",
        '  "shop_b/Growth.SemanticModel": {',
        '    "description": 1,',
        '    "inline": 6',
        "  }",
        "}",
        "$ comment-refs --floors " + str(tmp_path / "comment_issue_ref_floors.json") + " --tighten",
        "nothing to tighten",
        "[exit 0]",
        "$ comment-refs --floors " + str(tmp_path / "comment_issue_ref_floors.json"),
        "❌ issue/PR references in TMDL comments ROSE above the committed floor "
        "in 1 model/class(es):",
        "   shop_b/Growth.SemanticModel [inline]: 1 -> 6",
        "",
        "   Offending lines (new refs are among these; comments carry the mechanism, "
        "the commit carries the issue):",
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
        "   Fix the comment, or (human edit, justified in the PR) raise "
        + str(tmp_path / "comment_issue_ref_floors.json") + ".",
        "[exit 1]",
    ]
    assert log == expected
