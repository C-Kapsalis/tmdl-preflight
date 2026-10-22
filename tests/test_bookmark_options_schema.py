"""Layer 3.5: no bookmark may carry an ``options`` key outside Fabric's schema (B003).

Fabric validates ``options`` against a closed schema on report import and
rejects the whole report when it meets an unknown key. The allowed set is
targetVisualNames, applyOnlyToTargetVisuals, suppressData,
suppressActiveSection and suppressDisplay.

The test builds a tree of more than 100 bookmark files: two reports x 60 bookmarks, one carrying
``preserveNewVisualVisibility``, plus an archived report under ``legacy/``
that also carries it (ignored by the default archive markers).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, run_cli, run_fix, violations



def build_tree(root: Path, dirty: bool = True) -> Path:
    for rep in ("Beans.Report", "Cups.Report"):
        d = root / "shop" / rep / "definition"
        (d / "pages" / "p1" / "visuals" / "v1").mkdir(parents=True, exist_ok=True)
        (d / "report.json").write_text('{\n  "config": {}\n}\n', encoding="utf-8")
        (d / "pages" / "p1" / "page.json").write_text('{\n  "name": "p1"\n}\n', encoding="utf-8")
        (d / "pages" / "p1" / "visuals" / "v1" / "visual.json").write_text('{\n  "name": "v1"\n}\n', encoding="utf-8")
        b = d / "bookmarks"
        b.mkdir(parents=True, exist_ok=True)
        for i in range(60):
            options = {"targetVisualNames": ["v1"], "suppressData": True}
            if dirty and rep == "Beans.Report" and i == 7:
                options = {"targetVisualNames": ["v1"], "preserveNewVisualVisibility": True,
                           "suppressData": True}
            data = {"name": f"bm{i:03d}", "displayName": f"View {i}", "options": options,
                    "explorationState": {"version": "1.3", "activeSection": "p1"}}
            (b / f"bm{i:03d}.bookmark.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    legacy = root / "shop" / "legacy" / "Old.Report" / "definition" / "bookmarks"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "old.bookmark.json").write_text(json.dumps(
        {"name": "old", "options": {"preserveNewVisualVisibility": True}}, indent=2) + "\n", encoding="utf-8")
    return root


def test_no_bookmark_carries_an_unknown_options_key(tmp_path):
    root = build_tree(tmp_path / "repo", dirty=False)
    code, payload = run_check(root, "B003")
    assert payload["scanned"]["bookmarks"] > 100, (
        "the glob is broken, not the repo: a zero must never read as 'nothing to check'")
    assert code == 0, payload
    assert violations(payload, "B003") == []


def test_dirty_tree_fails_listing_each_offender_without_writing(tmp_path):
    root = build_tree(tmp_path / "repo")
    target = root / "shop" / "Beans.Report" / "definition" / "bookmarks" / "bm007.bookmark.json"
    before = target.read_bytes()
    code, payload = run_check(root, "B003")
    assert payload["scanned"]["bookmarks"] > 100
    assert code == 1
    found = violations(payload, "B003")
    assert len(found) == 1
    assert found[0]["path"].endswith("bm007.bookmark.json")
    assert "preserveNewVisualVisibility" in found[0]["message"]
    assert target.read_bytes() == before


def test_fix_exits_zero_and_recheck_exits_zero(tmp_path):
    root = build_tree(tmp_path / "repo")
    legacy = root / "shop" / "legacy" / "Old.Report" / "definition" / "bookmarks" / "old.bookmark.json"
    legacy_before = legacy.read_bytes()
    code, payload = run_fix(root, "B003")
    assert code == 0, payload
    code, payload = run_check(root, "B003")
    assert code == 0, payload
    text = (root / "shop" / "Beans.Report" / "definition" / "bookmarks" / "bm007.bookmark.json").read_text(encoding="utf-8")
    assert "preserveNewVisualVisibility" not in text
    assert json.loads(text)["options"] == {"targetVisualNames": ["v1"], "suppressData": True}
    assert legacy.read_bytes() == legacy_before  # archived reports are never touched


def test_fix_on_tree_without_bookmarks_exits_2(tmp_path):
    """New tool contract (F-bookmark-options-schema): nothing to repair -> usage exit 2."""
    root = build_tree(tmp_path / "repo")
    for f in root.rglob("*.bookmark.json"):
        f.unlink()
    code, _ = run_fix(root, "B003")
    assert code == 2


def test_every_allowed_options_key_is_accepted(tmp_path):
    """The closed allowed set (ported from the kernel allowed-key list)."""
    root = build_tree(tmp_path / "repo", dirty=False)
    bm = root / "shop" / "Cups.Report" / "definition" / "bookmarks" / "bm000.bookmark.json"
    data = json.loads(bm.read_text(encoding="utf-8"))
    data["options"] = {"targetVisualNames": ["v1"], "applyOnlyToTargetVisuals": True,
                       "suppressData": True, "suppressActiveSection": True, "suppressDisplay": True}
    bm.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    code, payload = run_check(root, "B003")
    assert code == 0 and violations(payload, "B003") == []


class TestBookmarkOptionsOutput:
    """The findings, the fix lines and the summaries the repair script wrote."""

    def _tree(self, tmp_path):
        return build_tree(tmp_path / "repo")

    def test_the_finding_names_the_path_and_the_key(self, tmp_path):
        root = self._tree(tmp_path)
        code, payload = run_check(root, "B003")
        assert code == 1
        found = violations(payload, "B003")
        assert len(found) == 1
        assert found[0]["message"] == (
            "shop/Beans.Report/definition/bookmarks/bm007.bookmark.json"
            "  ->  options.preserveNewVisualVisibility")

    def test_the_check_sums_up(self, tmp_path):
        root = self._tree(tmp_path)
        code, payload = run_check(root, "B003")
        assert code == 1
        assert any("1 illegal options key(s) across 120 bookmark file(s):" in n
                   for n in payload["notes"])

    def test_a_clean_tree_says_so(self, tmp_path):
        root = build_tree(tmp_path / "repo", dirty=False)
        code, payload = run_check(root, "B003")
        assert code == 0, payload
        assert any("clean: 120 bookmark file(s), no illegal options keys" in n
                   for n in payload["notes"])

    def test_the_fix_line_names_the_path(self, tmp_path):
        root = self._tree(tmp_path)
        code, payload = run_fix(root, "B003")
        assert code == 0, payload
        assert payload["fixes"] == [
            "B003: shop/Beans.Report/definition/bookmarks/bm007.bookmark.json"
            "  ->  removed options.preserveNewVisualVisibility"]

    def test_the_fix_sums_up(self, tmp_path):
        root = self._tree(tmp_path)
        code, payload = run_fix(root, "B003")
        assert code == 0, payload
        assert any("fixed 1 illegal options key(s):" in n for n in payload["notes"])

    def test_nothing_to_fix_says_so(self, tmp_path):
        root = build_tree(tmp_path / "repo", dirty=False)
        code, payload = run_fix(root, "B003")
        assert code == 0, payload
        assert any("nothing to fix: 120 bookmark file(s) already clean" in n
                   for n in payload["notes"])

    def test_two_reports_with_the_same_bookmark_name_are_told_apart(self, tmp_path):
        root = tmp_path / "repo"
        for rep in ("Beans.Report", "Cups.Report"):
            folder = root / "shop" / rep / "definition" / "bookmarks"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "same.bookmark.json").write_text(
                json.dumps({"options": {"bogus": True}}, indent=2) + "\n",
                encoding="utf-8")
        code, payload = run_fix(root, "B003")
        assert code == 0, payload
        named = [f for f in payload["fixes"] if "removed options.bogus" in f]
        assert len(named) == 2
        assert any("shop/Beans.Report/definition/bookmarks/same.bookmark.json" in f
                   for f in named)
        assert any("shop/Cups.Report/definition/bookmarks/same.bookmark.json" in f
                   for f in named)

    def test_a_key_with_an_object_value_is_removed(self, tmp_path):
        """BUGFIX: the original refused to repair a value it could not cut out."""
        root = tmp_path / "repo"
        folder = root / "shop" / "Beans.Report" / "definition" / "bookmarks"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "bm.bookmark.json"
        target.write_text(
            '{"options": {"targetVisualNames": [], "extra": {"a": 1}}}\n',
            encoding="utf-8")
        code, payload = run_fix(root, "B003")
        assert code == 0, payload
        assert target.read_text(encoding="utf-8") == (
            '{"options": {"targetVisualNames": []}}\n')

    def test_no_bookmark_file_is_a_usage_error(self, tmp_path):
        root = build_tree(tmp_path / "repo")
        for f in root.rglob("*.bookmark.json"):
            f.unlink()
        code, _out, err = run_cli("fix", str(root), "--select", "B003", "--no-config")
        assert code == 2
        assert "no bookmark files under" in err
        assert "the glob is broken, not the repo" in err
