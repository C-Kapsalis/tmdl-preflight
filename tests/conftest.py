"""Shared fixtures: a clean fictional model ("Pedal & Sprocket Bike Co.")
plus a helper that copies it into tmp_path so tests can break it safely.

Stand-in helpers:

* ``stand_in(name)`` copies ``tests/fixtures/<name>`` into ``tmp_path`` and
  returns the copy, so a test may mutate it.
* ``run_check(path, *rules, config=None, strict=False, args=())`` runs
  ``tmdl-preflight check --json`` through the CLI entry point and returns
  ``(exit_code, payload)``. ``rules`` are passed to ``--select``: an
  existing rule id (``M013``) or a rule name. Newer rules are usually
  selected by their name, which is the spec id without its chunk letter
  (``A-dead-fact-tables`` -> ``dead-fact-tables``).
* ``run_fix(...)`` does the same for ``fix``.
* ``run_cli(*argv)`` runs any subcommand and returns
  ``(exit_code, stdout, stderr)``.
* ``write_config(folder, data)`` writes ``.tmdl-preflight.json``.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path
from typing import Any, Optional

import pytest

from tmdl_preflight.cli import main

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


# ---------------------------------------------------------------------------
# Stand-in helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def stand_in(tmp_path: Path):
    """``stand_in("name")`` -> a disposable copy of ``tests/fixtures/name``."""

    def _copy(name: str) -> Path:
        src = FIXTURES / name
        assert src.exists(), f"missing fixture {src}"
        dest = tmp_path / Path(name).name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        return dest

    return _copy


def write_config(folder: Path, data: dict[str, Any]) -> Path:
    target = Path(folder, ".tmdl-preflight.json")
    target.write_text(json.dumps(data, indent=2), "utf-8")
    return target


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main([str(a) for a in argv])
        except SystemExit as exc:  # argparse usage errors
            code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


def _run(verb: str, path, rules, config, strict, args) -> tuple[int, dict]:
    argv = [verb, str(path), "--json"]
    if rules:
        argv += ["--select", ",".join(rules)]
    if config is not None:
        cfg = config if isinstance(config, (str, Path)) else write_config(
            Path(path) if Path(path).is_dir() else Path(path).parent, config
        )
        argv += ["--config", str(cfg)]
    else:
        argv += ["--no-config"]
    if strict:
        argv.append("--strict")
    argv += list(args)
    code, out, err = run_cli(*argv)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        payload = {"raw": out, "stderr": err}
    return code, payload


def run_check(path, *rules: str, config: Optional[Any] = None, strict: bool = False,
              args: tuple = ()) -> tuple[int, dict]:
    return _run("check", path, rules, config, strict, args)


def run_fix(path, *rules: str, config: Optional[Any] = None, strict: bool = False,
            args: tuple = ()) -> tuple[int, dict]:
    return _run("fix", path, rules, config, strict, args)


def violations(payload: dict, rule: Optional[str] = None) -> list[dict]:
    vs = payload.get("violations", [])
    return [v for v in vs if rule is None or v["rule"] == rule]
