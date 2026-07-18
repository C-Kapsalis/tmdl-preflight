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
