"""The check -> fix -> re-check engine (imposition pattern)."""

from __future__ import annotations

import json
import re

from tmdl_preflight.engine import check, fix
from tmdl_preflight.rules import default_ruleset
from tmdl_preflight.rules.base import Context


def _seed_fixable_violations(definition, report_dir):
    """Introduce one violation for each auto-fixable rule."""
    # M003: duplicate lineage tag
    products = (definition / "tables" / "Products.tmdl").read_text(encoding="utf-8")
    tag = re.search(r"lineageTag:\s*(\S+)", products).group(1)
    stores_file = definition / "tables" / "Stores.tmdl"
    stores = stores_file.read_text(encoding="utf-8")
    old = re.search(r"lineageTag:\s*(\S+)", stores).group(1)
    stores_file.write_text(stores.replace(old, tag, 1), encoding="utf-8")

    # M004: malformed lineage tag
    cal_file = definition / "tables" / "Calendar.tmdl"
    cal = cal_file.read_text(encoding="utf-8")
    cal_tag = re.search(r"lineageTag:\s*(\S+)", cal).group(1)
    cal_file.write_text(cal.replace(cal_tag, "placeholder-tag", 1), encoding="utf-8")

    # F001: orphan comma in the field-parameter source
    ms_file = definition / "tables" / "Metric Selector.tmdl"
    ms = ms_file.read_text(encoding="utf-8")
    ms_file.write_text(
        ms.replace(
            '\t\t\t\t    ( "Orders #", NAMEOF ( [Orders #] ), 1 ),',
            "\t\t\t\t    ,",
        ),
        encoding="utf-8",
    )

    # B001: string-typed bookmark int
    bf = report_dir / "definition" / "bookmarks" / "spotlight-revenue.bookmark.json"
    data = json.loads(bf.read_text(encoding="utf-8"))
    data["howCreated"] = "0"
    bf.write_text(json.dumps(data, indent=2), encoding="utf-8")


class TestCheck:
    def test_clean_project_has_no_violations(self, project):
        report = check(Context(project), default_ruleset())
        assert report.violations == []
        assert report.exit_code() == 0

    def test_check_never_mutates(self, project, definition, report_dir):
        _seed_fixable_violations(definition, report_dir)
        before = {
            f: f.read_bytes() for f in sorted(project.rglob("*")) if f.is_file()
        }
        report = check(Context(project), default_ruleset())
        assert report.violations
        after = {f: f.read_bytes() for f in sorted(project.rglob("*")) if f.is_file()}
        assert before == after

    def test_exit_codes(self, project, definition):
        # a WARNING-only project: malformed lineage tag (M004)
        cal_file = definition / "tables" / "Calendar.tmdl"
        cal = cal_file.read_text(encoding="utf-8")
        cal_tag = re.search(r"lineageTag:\s*(\S+)", cal).group(1)
        cal_file.write_text(cal.replace(cal_tag, "oops", 1), encoding="utf-8")

        report = check(Context(project), default_ruleset())
        assert report.errors == [] and report.warnings
        assert report.exit_code() == 0
        assert report.exit_code(strict=True) == 1


class TestFixImposition:
    def test_fix_then_recheck_clean(self, project, definition, report_dir):
        _seed_fixable_violations(definition, report_dir)
        ruleset = default_ruleset()

        first = check(Context(project), ruleset)
        assert {v.rule_id for v in first.violations} >= {"M003", "M004", "F001", "B001"}

        report = fix(Context(project), ruleset)
        assert report.fixes_applied
        assert set(report.fixed_rule_ids) == {"M003", "M004", "F001", "B001"}
        # everything fixable was repaired; nothing else was broken
        assert report.violations == []
        assert report.exit_code() == 0

    def test_fix_leaves_unfixable_violations(self, project, definition):
        # break a measure's delimiters (D001 has no fixer)
        f = definition / "tables" / "Sales Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "measure Revenue = SUM(Sales[net_amount])",
                "measure Revenue = SUM(Sales[net_amount]",
            ),
            encoding="utf-8",
        )
        report = fix(Context(project), default_ruleset())
        assert report.fixes_applied == []
        assert any(v.rule_id == "D001" for v in report.violations)
        assert report.exit_code() == 1

    def test_fix_on_clean_project_is_a_no_op(self, project):
        before = {
            f: f.read_bytes() for f in sorted(project.rglob("*")) if f.is_file()
        }
        report = fix(Context(project), default_ruleset())
        assert report.fixes_applied == [] and report.violations == []
        after = {f: f.read_bytes() for f in sorted(project.rglob("*")) if f.is_file()}
        assert before == after

    def test_report_serialization(self, project, definition, report_dir):
        _seed_fixable_violations(definition, report_dir)
        report = fix(Context(project), default_ruleset())
        payload = report.to_dict()
        assert payload["summary"]["fixes_applied"] == len(report.fixes_applied)
        assert payload["summary"]["errors"] == 0
