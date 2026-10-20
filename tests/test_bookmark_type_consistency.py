"""Layer 3.5: bookmark integer types (B001).

Power BI requires ``howCreated``, ``ComparisonKind`` and ``Version`` to be
JSON integers. Check is read-only; repair is the explicit ``fix`` verb
followed by a re-check.
"""
from __future__ import annotations

import json

import pytest

from conftest import run_check, run_fix, violations

STANDIN = "layer3_integration_standin"


def _report(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Roastery.Report"
class TestBookmarkTypeConsistency:
    def test_bookmark_integer_types(self, stand_in):
        code, payload = run_check(_report(stand_in), "B001")
        assert code == 0, payload

    def test_string_types_fail_without_writing(self, stand_in):
        report = _report(stand_in, "failing_db")
        bad = report / "definition" / "bookmarks" / "bad.bookmark.json"
        before = bad.read_bytes()
        code, payload = run_check(report, "B001")
        assert code == 1
        assert violations(payload, "B001")
        assert bad.read_bytes() == before

    def test_fix_then_recheck_is_clean(self, stand_in):
        report = _report(stand_in, "failing_db")
        code, payload = run_fix(report, "B001")
        assert code == 0, payload
        data = json.loads((report / "definition" / "bookmarks" / "bad.bookmark.json").read_text(encoding="utf-8"))
        assert data["howCreated"] == 0 and data["Version"] == 2
        code, payload = run_check(report, "B001")
        assert code == 0

    def test_no_bookmarks_folder_is_clean(self, stand_in):
        import shutil
        report = _report(stand_in)
        shutil.rmtree(report / "definition" / "bookmarks")
        code, payload = run_check(report, "B001")
        assert code == 0
