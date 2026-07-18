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
from .rules import default_ruleset
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
        ruleset = default_ruleset().select(
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
