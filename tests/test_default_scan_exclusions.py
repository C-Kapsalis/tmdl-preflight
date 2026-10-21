"""PA1: the default scan exclusions for archived copies.

With no `exclude` configured, every file whose path relative to the scan
root has a folder segment that holds `legacy`, `_backup` or `_b2` is
skipped. A configured `exclude` list replaces the default; an empty list
(`exclude = []`) turns it off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_cli, write_config


def _model(root: Path, name: str) -> Path:
    """A tiny model with one dangling description (an M013 finding)."""
    definition = root / f"{name}.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    (definition / "tables" / "Sales.tmdl").write_text(
        "table Sales\n"
        "\tlineageTag: 00000000-0000-4000-8000-000000000001\n"
        "\n"
        "\t/// An orphaned note nobody attached.\n"
        "\n"
        "\tmeasure 'Revenue' = 1\n"
        "\t\tlineageTag: 00000000-0000-4000-8000-000000000002\n",
        encoding="utf-8")
    return root / f"{name}.SemanticModel"


def _tree(root: Path) -> tuple[Path, Path]:
    """A live model and an archived copy of it."""
    live = _model(root / "live", "M")
    archived = _model(root / "x_backup", "M")
    return live, archived


def test_an_archived_copy_is_skipped_by_default(tmp_path):
    """PA1: only the live model is reported."""
    live, _archived = _tree(tmp_path)
    code, payload = run_check(tmp_path, "M013")
    files = {v["file"] for v in payload.get("violations", [])}
    assert code == 1, payload
    assert all("x_backup" not in f for f in files), files
    assert any("live" in f for f in files), files


def test_a_folder_above_the_scan_root_never_counts(tmp_path):
    """PA1: the same tree under a parent named `legacy` is still scanned."""
    parent = tmp_path / "legacy"
    parent.mkdir()
    _live, _archived = _tree(parent)
    code, payload = run_check(parent, "M013")
    files = {v["file"] for v in payload.get("violations", [])}
    assert code == 1, payload
    assert any("live" in f for f in files), files


def test_a_configured_exclude_replaces_the_default(tmp_path):
    """PA1: the default is replaced, not added to."""
    live, _archived = _tree(tmp_path)
    cfg = write_config(tmp_path, {"exclude": ["live/**"]})
    code, payload = run_check(tmp_path, "M013", config=cfg)
    files = {v["file"] for v in payload.get("violations", [])}
    assert not any("live" in f for f in files), files
    assert any("x_backup" in f for f in files), files


def test_an_empty_exclude_turns_the_default_off(tmp_path):
    """PA1: `exclude = []` scans everything."""
    _live, _archived = _tree(tmp_path)
    cfg = write_config(tmp_path, {"exclude": []})
    code, payload = run_check(tmp_path, "M013", config=cfg)
    files = {v["file"] for v in payload.get("violations", [])}
    assert any("x_backup" in f for f in files), files
    assert any("live" in f for f in files), files


def test_a_model_whose_name_holds_the_word_is_skipped(tmp_path):
    """PA1: a folder segment marks the archive, and the model's own folder
    is a segment."""
    _model(tmp_path / "live", "M_legacy")
    code, payload = run_check(tmp_path, "M013")
    assert code == 0, payload
    assert not payload.get("violations"), payload
