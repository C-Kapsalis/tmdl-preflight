"""Rules B001-B002: bookmark JSON integer types and visual references."""

from __future__ import annotations

import json

from tmdl_preflight.rules.base import Context
from tmdl_preflight.rules.report import (
    BookmarkIntegerTypesRule,
    BookmarkVisualRefsRule,
)


def _bookmark(report_dir):
    return (
        report_dir / "definition" / "bookmarks" / "spotlight-revenue.bookmark.json"
    )


class TestBookmarkIntegerTypes:
    def test_clean_passes(self, project):
        assert BookmarkIntegerTypesRule().check(Context(project)) == []

    def _stringify_ints(self, report_dir):
        bf = _bookmark(report_dir)
        data = json.loads(bf.read_text(encoding="utf-8"))
        data["howCreated"] = "User"
        flt = data["explorationState"]["visualContainers"]["a1b2c3d4e5f6"][
            "filters"
        ]["byExpr"][0]["filter"]
        flt["Version"] = "2"
        flt["ComparisonKind"] = "2"
        bf.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return bf

    def test_string_ints_detected(self, project, report_dir):
        self._stringify_ints(report_dir)
        violations = BookmarkIntegerTypesRule().check(Context(project))
        fields = {v.message.split(" ")[0] for v in violations}
        assert fields == {"howCreated", "Version", "ComparisonKind"}
        assert all(v.fixable for v in violations)

    def test_fix_coerces_to_integers(self, project, report_dir):
        bf = self._stringify_ints(report_dir)
        ctx = Context(project)
        rule = BookmarkIntegerTypesRule()
        assert rule.check(ctx)

        applied = rule.fix(ctx)
        assert len(applied) == 3

        ctx.reload()
        assert rule.check(ctx) == []
        data = json.loads(bf.read_text(encoding="utf-8"))
        assert data["howCreated"] == 0  # 'User' mapped to 0
        flt = data["explorationState"]["visualContainers"]["a1b2c3d4e5f6"][
            "filters"
        ]["byExpr"][0]["filter"]
        assert flt["Version"] == 2 and flt["ComparisonKind"] == 2

    def test_unmappable_string_stays_a_violation(self, project, report_dir):
        bf = _bookmark(report_dir)
        data = json.loads(bf.read_text(encoding="utf-8"))
        data["howCreated"] = "someday"  # no known integer meaning
        bf.write_text(json.dumps(data, indent=2), encoding="utf-8")

        ctx = Context(project)
        rule = BookmarkIntegerTypesRule()
        rule.fix(ctx)
        ctx.reload()
        assert rule.check(ctx)  # fixer must not invent a value


class TestBookmarkVisualRefs:
    def test_clean_passes(self, project):
        assert BookmarkVisualRefsRule().check(Context(project)) == []

    def test_dangling_reference_detected(self, project, report_dir):
        bf = _bookmark(report_dir)
        bf.write_text(
            bf.read_text(encoding="utf-8").replace("a1b2c3d4e5f6", "deadbeef0000"),
            encoding="utf-8",
        )
        violations = BookmarkVisualRefsRule().check(Context(project))
        assert violations
        assert all("deadbeef0000" in v.message for v in violations)
        assert not violations[0].fixable
