"""Layer 3.5: bookmark visual-container reference integrity (B002).

Every ``singleVisual.visualName`` a bookmark lists must name a visual folder
under ``definition/pages/<page>/visuals/``. Dangling references need human
judgement, so this is report-only (no fixer).
"""
from __future__ import annotations

import json

import pytest

from conftest import run_check, violations

STANDIN = "layer3_integration_standin"


def _report(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Roastery.Report"
class TestBookmarkVisualRefs:
    def test_no_dangling_visual_refs(self, stand_in):
        code, payload = run_check(_report(stand_in), "B002")
        assert code == 0, payload
        assert violations(payload, "B002") == []

    def test_dangling_visual_ref_fails(self, stand_in):
        code, payload = run_check(_report(stand_in, "failing_db"), "B002")
        assert code == 1
        found = violations(payload, "B002")
        assert len(found) == 1
        assert "bad.bookmark.json" in found[0]["path"]
        assert "v9" in found[0]["message"]

    def test_unparseable_bookmark_is_reported(self, stand_in):
        report = _report(stand_in)
        (report / "definition" / "bookmarks" / "broken.bookmark.json").write_text("{", encoding="utf-8")
        code, payload = run_check(report, "B002")
        assert code == 1
        assert violations(payload)

    def test_no_bookmarks_folder_is_clean(self, stand_in):
        import shutil
        report = _report(stand_in)
        shutil.rmtree(report / "definition" / "bookmarks")
        code, payload = run_check(report, "B002")
        assert code == 0 and violations(payload) == []

    def test_target_visual_names_dangling_is_stricter(self, stand_in):
        """STRICTER: options.targetVisualNames is checked too (earlier versions passed)."""
        report = _report(stand_in)
        bm = report / "definition" / "bookmarks" / "ok.bookmark.json"
        data = json.loads(bm.read_text(encoding="utf-8"))
        data["options"]["targetVisualNames"] = ["v9"]
        bm.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        code, payload = run_check(report, "B002")
        assert code == 1 and len(violations(payload, "B002")) == 1


class TestBookmarkVisualScope:
    """The set of existing visuals, and the bookmarks that are read."""

    def test_a_visual_folder_outside_the_pages_does_not_count(self, project, report_dir):
        """A folder named 'visuals' anywhere else holds no visual."""
        bm = report_dir / "definition" / "bookmarks" / "spotlight-revenue.bookmark.json"
        data = json.loads(bm.read_text(encoding="utf-8"))
        data["options"]["targetVisualNames"] = ["v9"]
        bm.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        static = report_dir / "StaticResources" / "visuals" / "v9"
        static.mkdir(parents=True, exist_ok=True)
        (static / "image.png").write_bytes(b"\x89PNG\r\n")
        code, payload = run_check(report_dir, "B002")
        assert code == 1
        found = violations(payload, "B002")
        assert len(found) == 1
        assert "v9" in found[0]["message"]

    def test_a_bookmark_in_a_sub_folder_is_not_read(self, project, report_dir):
        bm = report_dir / "definition" / "bookmarks" / "spotlight-revenue.bookmark.json"
        data = json.loads(bm.read_text(encoding="utf-8"))
        data["options"]["targetVisualNames"] = ["v9"]
        sub = report_dir / "definition" / "bookmarks" / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "copy.bookmark.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8")
        code, payload = run_check(report_dir, "B002")
        assert code == 0, payload
        assert violations(payload, "B002") == []

    def test_the_finding_carries_the_original_wording(self, project, report_dir):
        bm = report_dir / "definition" / "bookmarks" / "spotlight-revenue.bookmark.json"
        data = json.loads(bm.read_text(encoding="utf-8"))
        data["options"]["targetVisualNames"] = ["v9"]
        bm.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        code, payload = run_check(report_dir, "B002")
        assert code == 1
        found = violations(payload, "B002")
        assert len(found) == 1
        assert found[0]["message"] == (
            "spotlight-revenue.bookmark.json: visualName 'v9' has no matching visual directory")

    def test_an_unreadable_bookmark_says_so(self, project, report_dir):
        broken = report_dir / "definition" / "bookmarks" / "broken.bookmark.json"
        broken.write_text("{", encoding="utf-8")
        code, payload = run_check(report_dir, "B002")
        assert code == 1
        found = violations(payload, "B002")
        assert len(found) == 1
        assert found[0]["message"].startswith(f"Could not parse {broken}: ")
