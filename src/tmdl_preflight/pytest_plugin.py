"""Pytest integration.

tmdl-preflight's rules grew out of a pytest suite, and running them from
pytest is still a first-class path. The plugin registers one fixture:

``tmdl_preflight``
    A small runner object. Call ``tmdl_preflight.assert_clean(path)`` in a
    test to fail with a formatted violation list when the model at ``path``
    is not clean.

The runner honors the imposition pattern: with ``autofix=True`` (or the
environment variable ``TMDL_PREFLIGHT_AUTOFIX=1``) it repairs what it can
and asserts on the *re-check*, mirroring ``tmdl-preflight fix``.

Example::

    def test_model_is_deployable(tmdl_preflight):
        tmdl_preflight.assert_clean("models/Shop.SemanticModel", autofix=True)

    def test_only_lineage_rules(tmdl_preflight):
        tmdl_preflight.assert_clean("models/Shop.SemanticModel",
                                    select={"m003", "m004"})
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

from .engine import PreflightReport, check, fix
from .rules import full_ruleset
from .rules.base import Context, Severity


class PreflightRunner:
    """Thin convenience wrapper used by the ``tmdl_preflight`` fixture."""

    def run(
        self,
        path: str | Path,
        select: Optional[set[str]] = None,
        ignore: Optional[set[str]] = None,
        autofix: Optional[bool] = None,
    ) -> PreflightReport:
        if autofix is None:
            autofix = os.getenv("TMDL_PREFLIGHT_AUTOFIX", "0") == "1"
        ctx = Context(Path(path))
        ruleset = full_ruleset().select(
            {s.lower() for s in select} if select else None,
            {s.lower() for s in ignore} if ignore else None,
        )
        return fix(ctx, ruleset) if autofix else check(ctx, ruleset)

    def assert_clean(
        self,
        path: str | Path,
        select: Optional[set[str]] = None,
        ignore: Optional[set[str]] = None,
        autofix: Optional[bool] = None,
        strict: bool = False,
    ) -> PreflightReport:
        report = self.run(path, select=select, ignore=ignore, autofix=autofix)
        blocking = report.errors + (report.warnings if strict else [])
        if blocking:
            lines = [
                f"  {v.rule_id} {v.severity.value}: {v.message}"
                + (f" [{v.obj}]" if v.obj else "")
                + (f" ({v.location()})" if v.file else "")
                for v in blocking
            ]
            fixed_note = (
                f"\n  ({len(report.fixes_applied)} fix(es) were applied but "
                f"violations remain)"
                if report.fixes_applied
                else ""
            )
            pytest.fail(
                f"tmdl-preflight found {len(blocking)} blocking violation(s) "
                f"in {path}:{fixed_note}\n" + "\n".join(lines),
                pytrace=False,
            )
        return report


@pytest.fixture
def tmdl_preflight() -> PreflightRunner:
    """Run tmdl-preflight rules inside a pytest test."""
    return PreflightRunner()


# ---------------------------------------------------------------------------
# Advisory models: failures on them are reported as expected failures
# ---------------------------------------------------------------------------

_ADVISORY_KEY = pytest.StashKey[Optional[list[str]]]() if hasattr(pytest, "StashKey") else None


def _advisory_models(config) -> list[str]:
    """The ``advisory`` list of the project configuration (pyproject.toml
    ``[tool.tmdl-preflight]`` or ``.tmdl-preflight.toml``/``.json``)."""
    if _ADVISORY_KEY is not None and _ADVISORY_KEY in config.stash:
        return config.stash[_ADVISORY_KEY] or []
    found: list[str] = []
    try:
        from .config import find_config, read_config_file

        path = find_config(Path(str(config.rootpath)))
        raw = read_config_file(path) if path else {}
        value = raw.get("advisory") if isinstance(raw, dict) else None
        if isinstance(value, list):
            found = [str(v) for v in value if str(v).strip()]
    except Exception:  # a broken config must not break unrelated test runs
        found = []
    if _ADVISORY_KEY is not None:
        config.stash[_ADVISORY_KEY] = found
    return found


def _advisory_subject(item, advisory: list[str]) -> Optional[str]:
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return None
    for model in advisory:
        if model in callspec.id:
            return model
    root = Path(str(item.config.rootpath)).resolve()
    for value in callspec.params.values():
        if not isinstance(value, (str, Path)):
            continue
        try:
            rel = Path(value).resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            rel = str(value).replace("\\", "/")
        for model in advisory:
            m = model.replace("\\", "/").strip("/")
            if rel == m or rel.startswith(m + "/"):
                return model
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    advisory = _advisory_models(item.config)
    if not advisory:
        return
    subject = _advisory_subject(item, advisory)
    if subject is None:
        return
    report.outcome = "skipped"
    report.wasxfail = f"advisory model {subject}: failures are reported, not gated"
