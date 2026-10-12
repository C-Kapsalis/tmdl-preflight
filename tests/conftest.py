"""Shared fixtures: a clean fictional model ("Pedal & Sprocket Bike Co.")
plus a helper that copies it into tmp_path so tests can break it safely."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN_PROJECT = FIXTURES / "pedal-and-sprocket"


@pytest.fixture
def clean_project() -> Path:
    """The pristine fixture project (read-only — never mutate this)."""
    return CLEAN_PROJECT


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A disposable copy of the fixture project, safe to mutate."""
    dest = tmp_path / "pedal-and-sprocket"
    shutil.copytree(CLEAN_PROJECT, dest)
    return dest


@pytest.fixture
def definition(project: Path) -> Path:
    return project / "BikeShop.SemanticModel" / "definition"


@pytest.fixture
def report_dir(project: Path) -> Path:
    return project / "BikeShop.Report"


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"expected exactly one {old!r} in {path.name}"
    path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.fixture
def replace_in():
    """``replace_in(path, old, new)``: plant a defect by replacing one exact
    snippet (the test fails loudly if the snippet is missing or ambiguous)."""
    return _replace_once
