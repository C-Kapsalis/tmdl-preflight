"""The generated rule catalog (spec H-rule-catalog-markdown)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli
from tmdl_preflight.catalog import cell, render_markdown_catalog, summary_line
from tmdl_preflight.rules import full_ruleset

REPO = Path(__file__).resolve().parent.parent


def test_cell_escaping():
    assert cell("Use A | B\nthen C") == "Use A \\| B then C"


def test_summary_line_skips_rule_lines():
    assert summary_line("═════\n\nFlags bean tables without a key.\nMore.") == (
        "Flags bean tables without a key.")
    assert summary_line("=====\n-----") == ""


def test_counts_match_rules_json():
    code, out, _ = run_cli("rules", "--json")
    rules = json.loads(out)
    page = render_markdown_catalog(full_ruleset())
    fixable = sum(1 for r in rules if r["fixable"])
    baselinable = sum(1 for r in rules if r["baselinable"])
    assert (f"Rules: **{len(rules)}** · auto-fixable: **{fixable}** · "
            f"baselinable: **{baselinable}**.") in page
    assert page.endswith("|\n") and not page.endswith("\n\n")
    assert render_markdown_catalog(full_ruleset()) == page


def test_check_reports_missing_and_drift(tmp_path):
    out = tmp_path / "docs" / "rules.md"
    code, _o, err = run_cli("rules", "--format", "markdown", "--out", out, "--check")
    assert code == 1 and "MISSING:" in err
    assert run_cli("rules", "--format", "markdown", "--out", out)[0] == 0
    assert run_cli("rules", "--format", "markdown", "--out", out, "--check")[0] == 0
    out.write_bytes(out.read_bytes() + b" ")
    code, _o, err = run_cli("rules", "--format", "markdown", "--out", out, "--check")
    assert code == 1 and "DRIFT:" in err
    assert run_cli("rules", "--format", "markdown", "--check")[0] == 2


def test_committed_catalog_is_current():
    """docs/rules.md is generated; regenerate it after changing a rule."""
    code, out, err = run_cli("rules", "--format", "markdown", "--out",
                             REPO / "docs" / "rules.md", "--check")
    assert code == 0, err
