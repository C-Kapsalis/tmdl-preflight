"""B001 bookmark-int-types: the findings, the fixer and the target scope.

Power BI requires ``howCreated``, ``ComparisonKind`` and ``Version`` to be
JSON integers. The messages and the file the fixer writes are the ones the
bookmark type checker used, and the rule accepts a bookmark file or a
folder of them as a target.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations


def _bookmark(report_dir: Path) -> Path:
    return report_dir / "definition" / "bookmarks" / "spotlight-revenue.bookmark.json"


def _stringify(report_dir: Path, value: str = "User") -> Path:
    bf = _bookmark(report_dir)
    data = json.loads(bf.read_text(encoding="utf-8"))
    data["howCreated"] = value
    bf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return bf


class TestBookmarkIntTypes:
    def test_the_finding_carries_the_original_wording(self, project, report_dir):
        _stringify(report_dir)
        code, payload = run_check(project, "B001")
        assert code == 1
        found = violations(payload, "B001")
        assert len(found) == 1
        assert found[0]["message"] == (
            "[howCreated] at howCreated = 'User' (string, must be int)")

    def test_an_unreadable_bookmark_is_reported(self, project, report_dir):
        bf = _bookmark(report_dir)
        bf.write_text("{ not json", encoding="utf-8")
        code, payload = run_check(project, "B001")
        assert code == 1
        found = violations(payload, "B001")
        assert len(found) == 1
        assert found[0]["message"].startswith(f"ERROR reading {bf}: ")

    def test_the_check_sums_up(self, project, report_dir):
        _stringify(report_dir)
        code, payload = run_check(project, "B001")
        assert code == 1
        assert any("Total: 1 violation(s) across 1 file(s)." in n
                   for n in payload["notes"])

    def test_no_bookmark_file_under_the_target(self, tmp_path):
        code, payload = run_check(tmp_path / "nothing", "B001")
        assert code == 2  # the path does not exist at all


class TestBookmarkIntTypesFixer:
    def test_the_file_is_rewritten_whole(self, project, report_dir):
        bf = _bookmark(report_dir)
        bf.write_text('{"howCreated":"User","Version":"2","keep":"3"}', encoding="utf-8")
        code, payload = run_fix(project, "B001")
        assert code == 0, payload
        assert bf.read_text(encoding="utf-8") == (
            "{\n"
            "  \"howCreated\": 0,\n"
            "  \"Version\": 2,\n"
            "  \"keep\": \"3\"\n"
            "}\n"
        )

    def test_the_fix_line_carries_the_original_wording(self, project, report_dir):
        _stringify(report_dir, "0")
        code, payload = run_fix(project, "B001")
        assert code == 0, payload
        assert any("fix: howCreated: '0' -> 0" in f for f in payload["fixes"])

    def test_the_fix_sums_up(self, project, report_dir):
        _stringify(report_dir, "0")
        code, payload = run_fix(project, "B001")
        assert code == 0, payload
        assert any("Applied 1 fix(es) across 1 file(s)." in n for n in payload["notes"])

    def test_a_value_the_fixer_cannot_convert_is_not_auto_fixable(self, project, report_dir):
        _stringify(report_dir, "x")
        code, payload = run_check(project, "B001")
        assert code == 1
        found = violations(payload, "B001")
        assert len(found) == 1
        assert found[0]["fixable"] is False

    def test_an_unreadable_bookmark_is_not_auto_fixable(self, project, report_dir):
        bf = _bookmark(report_dir)
        bf.write_text("{ not json", encoding="utf-8")
        code, payload = run_check(project, "B001")
        assert code == 1
        assert violations(payload, "B001")[0]["fixable"] is False

    def test_a_negative_how_created_becomes_minus_one(self, project, report_dir):
        """BUGFIX: the original left the string "-1" alone and failed its own re-check."""
        bf = _bookmark(report_dir)
        data = json.loads(bf.read_text(encoding="utf-8"))
        data["howCreated"] = "-1"
        bf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        code, payload = run_fix(project, "B001")
        assert code == 0, payload
        assert json.loads(bf.read_text(encoding="utf-8"))["howCreated"] == -1

    def test_a_bookmark_with_a_byte_order_mark_is_read(self, project, report_dir):
        """BUGFIX: the original counted a bookmark with a BOM as unreadable."""
        bf = _bookmark(report_dir)
        data = json.loads(bf.read_text(encoding="utf-8"))
        data["howCreated"] = "0"
        bf.write_bytes("﻿".encode("utf-8")
                       + (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        code, payload = run_check(project, "B001")
        assert code == 1
        found = violations(payload, "B001")
        assert len(found) == 1
        assert found[0]["message"] == (
            "[howCreated] at howCreated = '0' (string, must be int)")

    def test_the_byte_order_mark_survives_the_fix(self, project, report_dir):
        bf = _bookmark(report_dir)
        bf.write_bytes("﻿".encode("utf-8") + bf.read_bytes())
        code, payload = run_fix(project, "B001")
        assert code == 0, payload
        assert bf.read_bytes().startswith("﻿".encode("utf-8"))


class TestBookmarkTargetScope:
    def test_a_bookmarks_folder_is_a_target(self, project, report_dir):
        _stringify(report_dir)
        folder = report_dir / "definition" / "bookmarks"
        code, payload = run_check(folder, "B001")
        assert code == 1
        found = violations(payload, "B001")
        assert len(found) == 1
        assert found[0]["message"] == (
            "[howCreated] at howCreated = 'User' (string, must be int)")

    def test_a_single_bookmark_file_is_a_target(self, project, report_dir):
        _stringify(report_dir)
        code, payload = run_check(_bookmark(report_dir), "B001")
        assert code == 1
        found = violations(payload, "B001")
        assert len(found) == 1
        assert found[0]["message"] == (
            "[howCreated] at howCreated = 'User' (string, must be int)")

    def test_a_folder_without_a_bookmark_is_still_a_usage_error(self, tmp_path):
        code, _out, err = _run_cli(tmp_path)
        assert code == 2
        assert "no semantic model or report found" in err


def _run_cli(path: Path):
    from conftest import run_cli

    return run_cli("check", str(path), "--select", "B001", "--no-config")
