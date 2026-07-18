"""The tmdl_preflight pytest fixture."""

from __future__ import annotations

import re

import pytest


def _break_lineage(definition):
    products = (definition / "tables" / "Products.tmdl").read_text(encoding="utf-8")
    tag = re.search(r"lineageTag:\s*(\S+)", products).group(1)
    stores_file = definition / "tables" / "Stores.tmdl"
    stores = stores_file.read_text(encoding="utf-8")
    old = re.search(r"lineageTag:\s*(\S+)", stores).group(1)
    stores_file.write_text(stores.replace(old, tag, 1), encoding="utf-8")


def test_assert_clean_passes_on_clean_model(tmdl_preflight, project):
    report = tmdl_preflight.assert_clean(project)
    assert report.violations == []


def test_assert_clean_fails_with_violation_list(tmdl_preflight, project, definition):
    _break_lineage(definition)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        tmdl_preflight.assert_clean(project)
    assert "M003" in str(excinfo.value)


def test_autofix_repairs_before_asserting(tmdl_preflight, project, definition):
    _break_lineage(definition)
    report = tmdl_preflight.assert_clean(project, autofix=True)
    assert report.fixes_applied


def test_select_scopes_the_run(tmdl_preflight, project, definition):
    _break_lineage(definition)
    # scoped to an unrelated rule, the broken model still asserts clean
    tmdl_preflight.assert_clean(project, select={"d001"})
