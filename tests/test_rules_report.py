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
        fields = {v.message.split("]")[0].lstrip("[") for v in violations}
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


# ---------------------------------------------------------------------------
# B001 surgical fix, B003, B004
# ---------------------------------------------------------------------------

from tmdl_preflight.edits import EditRefused  # noqa: E402
from tmdl_preflight.rules.report import (  # noqa: E402
    BookmarkOptionsSchemaRule,
    ReportDefinitionIntegrityRule,
    strip_illegal_options,
)

import pytest  # noqa: E402


class TestBookmarkIntegerRewrite:
    def test_the_fixed_file_is_rewritten_whole(self, project, report_dir):
        bf = _bookmark(report_dir)
        original = json.loads(bf.read_text(encoding="utf-8"))
        original["howCreated"] = "0"
        bf.write_text(json.dumps(original, separators=(",", ":")), encoding="utf-8")
        assert BookmarkIntegerTypesRule().fix(Context(project))
        text = bf.read_text(encoding="utf-8")
        assert text.endswith("}\n")
        assert '"howCreated": 0' in text
        assert json.loads(text)["howCreated"] == 0

    def test_a_lookalike_inside_a_string_is_untouched(self, project, report_dir):
        bf = _bookmark(report_dir)
        data = json.loads(bf.read_text(encoding="utf-8"))
        data["howCreated"] = "0"
        data["note"] = '"howCreated": "0"'
        bf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        assert BookmarkIntegerTypesRule().fix(Context(project))
        assert json.loads(bf.read_text(encoding="utf-8"))["note"] == '"howCreated": "0"'


class TestBookmarkOptionsSchema:
    def _plant(self, report_dir, extra='"suppressDatta": true'):
        bf = _bookmark(report_dir)
        text = bf.read_text(encoding="utf-8").replace(
            '"targetVisualNames": ["a1b2c3d4e5f6"]',
            f'"targetVisualNames": ["a1b2c3d4e5f6"],\n    {extra}',
        )
        bf.write_text(text, encoding="utf-8")
        return bf

    def test_clean_passes(self, project):
        assert BookmarkOptionsSchemaRule().check(Context(project)) == []

    def test_illegal_key_detected(self, project, report_dir):
        self._plant(report_dir)
        violations = BookmarkOptionsSchemaRule().check(Context(project))
        assert len(violations) == 1 and "options.suppressDatta" in violations[0].message

    def test_fix_is_surgical_and_idempotent(self, project, report_dir):
        original = _bookmark(report_dir).read_text(encoding="utf-8")
        self._plant(report_dir, '"bogus": {"nested": [1, 2]}')
        rule = BookmarkOptionsSchemaRule()
        assert rule.fix(Context(project)) == [
            "BikeShop.Report/definition/bookmarks/spotlight-revenue.bookmark.json"
            "  ->  removed options.bogus"]
        assert _bookmark(report_dir).read_text(encoding="utf-8") == original
        assert rule.check(Context(project)) == []
        assert rule.fix(Context(project)) == []

    def test_strip_first_middle_and_last_members(self):
        text = '{"options": {"a": 1, "targetVisualNames": [], "b": "x", "suppressData": true, "c": null}}'
        new, removed = strip_illegal_options(text)
        assert removed == ["a", "b", "c"]
        assert json.loads(new) == {"options": {"targetVisualNames": [], "suppressData": True}}

    def test_strip_refuses_when_it_cannot_prove_the_edit(self):
        # duplicate keys: json keeps the last one, a textual cut cannot be
        # shown to remove exactly that member
        text = '{"options": {"bad": 1, "bad": 2}}'
        with pytest.raises(EditRefused):
            strip_illegal_options(text)


class TestReportDefinitionIntegrity:
    def _write_pbir(self, report_dir, path):
        (report_dir / "definition.pbir").write_text(
            json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": path}}}),
            encoding="utf-8",
        )

    def test_clean_passes(self, project, report_dir):
        self._write_pbir(report_dir, "../BikeShop.SemanticModel")
        assert ReportDefinitionIntegrityRule().check(Context(project)) == []

    def test_dangling_by_path(self, project, report_dir):
        self._write_pbir(report_dir, "../Renamed.SemanticModel")
        violations = ReportDefinitionIntegrityRule().check(Context(project))
        assert len(violations) == 1 and "../Renamed.SemanticModel" in violations[0].message

    def test_page_order_entry_without_folder(self, project, report_dir):
        (report_dir / "definition" / "pages" / "pages.json").write_text(
            json.dumps({"pageOrder": ["overview", "gone"], "activePageName": "overview"}),
            encoding="utf-8",
        )
        violations = ReportDefinitionIntegrityRule().check(Context(project))
        assert [v.obj for v in violations] == ["gone"]

    def test_unparseable_visual(self, project, report_dir):
        vf = report_dir / "definition" / "pages" / "overview" / "visuals" / "a1b2c3d4e5f6" / "visual.json"
        vf.write_text(vf.read_text(encoding="utf-8")[:-3], encoding="utf-8")
        violations = ReportDefinitionIntegrityRule().check(Context(project))
        assert len(violations) == 1 and "visual.json is not valid JSON" in violations[0].message
