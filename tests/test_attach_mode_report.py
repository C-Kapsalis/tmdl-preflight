"""PA13: the M013 attach mode's scope, its counters and its report.

Attach mode repairs only the files under `tables/`, and its report counts
occurrences in a dry run and removed blank lines in a live run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli, write_config

RULE = "=" * 80

ATTACH = {"rules": {"M013": {"fix_mode": "attach"}}}


def _model(tmp_path: Path, body: str) -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    (definition / "tables" / "Beans.tmdl").write_text(body, encoding="utf-8")
    return definition


TWO_BLANKS = (
    "table Beans\n"
    "\t/// Kilograms sold\n"
    "\n"
    "\n"
    "\tmeasure Kg = SUM(Beans[kg])\n"
)


def _run(d: Path, *args: str) -> tuple[int, str, str]:
    cfg = write_config(d, ATTACH)
    return run_cli("fix", d, "--select", "M013", "--config", str(cfg), *args)


def test_the_attach_mode_leaves_the_files_outside_tables_alone(tmp_path):
    """PA13: only the files under tables/ are repaired."""
    d = _model(tmp_path, TWO_BLANKS)
    (d / "expressions.tmdl").write_text(
        "expression A = 1\n\t/// A note.\n\n\n", encoding="utf-8")
    _run(d)
    assert "\n\n" in (d / "expressions.tmdl").read_text(encoding="utf-8")


def test_the_dry_run_counts_occurrences(tmp_path):
    """PA13: a description followed by two blank lines counts as one."""
    d = _model(tmp_path, TWO_BLANKS)
    code, out, err = _run(d, "--dry-run")
    assert "  - Beans.tmdl: 1 blank lines" in out, out
    assert (d / "tables" / "Beans.tmdl").read_text(encoding="utf-8") == TWO_BLANKS


def test_the_dry_run_lists_the_files_only_when_verbose(tmp_path):
    """PA13: the per-file line waits for --verbose."""
    d = _model(tmp_path, TWO_BLANKS)
    code, out, err = _run(d, "--dry-run")
    assert "Removed 1 blank line(s)" not in out, out
    code, out, err = _run(d, "--dry-run", "--verbose")
    assert "  ✓ Beans.tmdl: Removed 1 blank line(s)" in out, out


def test_the_live_run_counts_removed_blank_lines(tmp_path):
    """PA13: the live run removes both blank lines and says so."""
    d = _model(tmp_path, TWO_BLANKS)
    code, out, err = _run(d)
    assert "Removed 2 blank line(s)" in out, out
    assert (d / "tables" / "Beans.tmdl").read_text(encoding="utf-8") == (
        "table Beans\n\t/// Kilograms sold\n\tmeasure Kg = SUM(Beans[kg])\n")


def test_the_attach_mode_report(tmp_path):
    """PA13: the report of the comment-spacing cleanup."""
    d = _model(tmp_path, TWO_BLANKS)
    code, out, err = _run(d)
    assert f"{RULE}\nCLEANUP TMDL COMMENT SPACING\n{RULE}\n" in out, out
    assert "  ✓ Beans.tmdl: Removed 2 blank line(s)" in out, out
    assert "Scanned 1 tables" in out, out
    assert "Fixed 1 tables" in out, out
    assert "  - 2 blank lines removed" in out, out
    assert "Files fixed:" in out, out
    assert "  - Beans.tmdl: 2 blank lines" in out, out


def test_the_attach_mode_report_of_a_clean_model(tmp_path):
    """PA13: the clean verdict."""
    d = _model(tmp_path, "table Beans\n\tmeasure Kg = SUM(Beans[kg])\n")
    code, out, err = _run(d)
    assert "✓ No issues found - all tables are clean" in out, out


def test_the_attach_mode_dry_run_report(tmp_path):
    """PA13: the dry run header and its closing hint."""
    d = _model(tmp_path, TWO_BLANKS)
    code, out, err = _run(d, "--dry-run")
    assert "🔍 DRY RUN MODE - No changes will be written" in out, out
    assert "⚠️  Run without --dry-run to apply fixes" in out, out
