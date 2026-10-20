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
