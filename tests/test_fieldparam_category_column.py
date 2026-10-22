"""Every x-Selector row needs its category.

A 3-field row (label, NAMEOF, order) whose label has no 4-field twin in the
same table drops out of every category filter: the picker shows the field,
but no filter ever finds it.

Rule: F005 fieldparam-category-column. The original checked the numbered x
tables `x-Selector 1` to `x-Selector 9` by default, reading only fenced
calculated sources; the tool keeps that scope and takes other tables from
the `category_column_tables` option.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = [pytest.mark.p0]


def _model(stand_in):
    return stand_in("fieldparam_category_column") / "Model.SemanticModel"


def test_a_row_without_a_category_is_reported(stand_in):
    model = _model(stand_in)
    code, payload = run_check(model, "F005")
    found = violations(payload, "F005")
    assert code == 1
    assert len(found) == 1
    assert found[0]["message"] == 'x-Selector 2: "Pace"'


def test_a_table_outside_the_default_scope_is_not_read(stand_in):
    model = _model(stand_in)
    code, payload = run_check(model, "F005")
    found = violations(payload, "F005")
    assert not [v for v in found if "x-Selector 10" in v["message"]]


def test_the_rule_reads_the_configured_tables(stand_in):
    model = _model(stand_in)
    config = {"rules": {"fieldparam-category-column": {
        "category_column_tables": ["x-Selector 10"]}}}
    code, payload = run_check(model, "F005", config=config)
    found = violations(payload, "F005")
    assert len(found) == 1
    assert found[0]["message"] == 'x-Selector 10: "Pace"'
