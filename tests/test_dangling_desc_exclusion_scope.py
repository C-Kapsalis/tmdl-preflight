"""Scan exclusions match the path RELATIVE TO THE SCAN ROOT, never the absolute one.

Ported from the original suite's exclusion-scope tests (spec
A-scan-exclusions-relative). Archived and backup trees are skipped by folder
name; matching that against an absolute path also matches any ANCESTOR folder,
so a checkout under ``~/legacy/`` (or a worktree named ``rm-legacy-m``) would
exclude everything and the check would pass having scanned zero files: a false
clean that looks exactly like a clean run.

Each test plants an ``expressions.tmdl`` with one orphan ``///`` run (an M013
finding) and runs ``tmdl-preflight check --select M013`` with the parity
exclude list; the JSON summary's ``files_scanned`` / ``excluded`` counts say
what was looked at.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, violations

# Parity profile of the original gate: a relative path segment CONTAINING
# legacy, _backup or _b2.
PARITY_EXCLUDES = {"exclude": ["**/*legacy*/**", "**/*_backup*/**", "**/*_b2*/**"]}


def _plant(definition: Path) -> Path:
    definition.mkdir(parents=True, exist_ok=True)
    f = definition / "expressions.tmdl"
    f.write_text('expression v-example = "ok"\n\n/// orphan description\n\n',
                 encoding="utf-8", newline="")
    return f


def _scan(root: Path, tmp_path: Path):
    cfg = tmp_path / "parity-excludes.json"
    cfg.write_text(json.dumps(PARITY_EXCLUDES), encoding="utf-8")
    return run_check(root, "M013", config=cfg, strict=True)


def test_ancestor_named_legacy_does_not_disable_the_gate(tmp_path):
    """The regression. A scan root under a `legacy`-named parent must still scan."""
    root = tmp_path / "legacy" / "PBI"
    _plant(root / "spinout_02_db" / "M.SemanticModel" / "definition")
    _code, payload = _scan(root, tmp_path)
    assert payload["summary"]["files_scanned"] >= 1, (
        "gate found nothing because an ANCESTOR was named 'legacy'")
    assert len(violations(payload, "M013")) == 1


@pytest.mark.parametrize("parent", ["legacy", "rm-legacy-m", "pbi_backup", "wt_b2"])
def test_every_excluded_substring_is_safe_in_an_ancestor(tmp_path, parent):
    root = tmp_path / parent / "PBI"
    _plant(root / "spinout_02_db" / "M.SemanticModel" / "definition")
    _code, payload = _scan(root, tmp_path)
    assert payload["summary"]["files_scanned"] >= 1, (
        f"ancestor named {parent!r} disabled the gate")


@pytest.mark.parametrize("skipped", [
    "legacy", "spinout_05_db_backup", "spinout_05_db_b2", "spinout_07_db_legacy",
])
def test_excluded_trees_inside_the_repo_are_still_skipped(tmp_path, skipped):
    """The exclusion must keep working for what it was built for."""
    root = tmp_path / "PBI"
    _plant(root / skipped / "M.SemanticModel" / "definition")
    code, payload = _scan(root, tmp_path)
    assert payload["summary"]["files_scanned"] == 0, f"{skipped!r} should be excluded"
    assert payload["summary"]["excluded"] >= 1
    assert violations(payload) == []
    assert code == 0


def test_live_client_dirs_are_scanned(tmp_path):
    root = tmp_path / "PBI"
    _plant(root / "spinout_02_db" / "M.SemanticModel" / "definition")
    _plant(root / "universal" / "Performance.SemanticModel" / "definition")
    _code, payload = _scan(root, tmp_path)
    assert payload["summary"]["files_scanned"] == 2
    assert payload["scanned"]["models"] == 2


def test_a_target_outside_the_repo_is_still_scanned(tmp_path):
    """A temp fixture below no repository must not be silently skipped, and a
    bare definition/ folder without tables/ is accepted as a model."""
    definition = tmp_path / "fixture" / "Broken.SemanticModel" / "definition"
    _plant(definition)
    code, payload = _scan(definition, tmp_path)
    assert code != 2, "a bare definition/ folder must be accepted"
    assert payload["summary"]["files_scanned"] >= 1
