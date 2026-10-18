"""Measure-name classes (D-measure-name-classes): the shared name-only
classifier behind the helper / user-facing / noise checks.

API: ``tmdl_preflight.measure_classes.classify_measure_name(name, options=None)``
returning an object with ``is_helper`` (bool), ``subcategory`` (str | None)
and ``is_noise`` (bool). Expected values were recorded from the original
classifier on these exact names (see parity-expected.json).
"""
from __future__ import annotations

import pytest


CASES = [
    # name, is_helper, subcategory, is_noise
    ("Total Revenue", False, None, False),
    ("-helper Margin Base", True, "measure_helper", False),
    ("_tmp Beans", True, "measure_helper", True),
    ("-Visual Bar Label", True, "visual_helper", False),
    ("w-Card Text", True, "visual_helper", False),
    ("i-Row Count", True, "diagnostic_helper", False),
    ("f-Espresso", True, "slicer_helper", False),
    ("-Base Cups", True, "intermediary_helper", False),
    ("q-Something", True, "intermediary_helper", False),
    ("z-Toggle Price", False, None, False),
    ("Z-Toggle", True, "intermediary_helper", False),
    ("Cohort Test 2", True, "test_measure", False),
    ("Latest Order", False, None, False),
    ("#Cups Sold", False, None, False),
    ("^Gross Sales", False, None, False),
    ("!Revenue", False, None, False),
    ("i-Simple Test", True, "diagnostic_helper", False),
    ("TestRun", True, "test_measure", False),
    ("test_x", True, "test_measure", True),
    ("", False, None, False),
    ("Blank Measure", False, None, True),
    ("min date", False, None, True),
    ("value", False, None, True),
    ("Beans_Per_Bag", False, None, True),
    ("Cups Sold", False, None, False),
]


@pytest.mark.parametrize("name,is_helper,subcategory,is_noise", CASES, ids=[c[0] or "<empty>" for c in CASES])
def test_classification(name, is_helper, subcategory, is_noise):
    from tmdl_preflight.measure_classes import classify_measure_name

    c = classify_measure_name(name)
    assert c.is_helper is is_helper
    assert c.subcategory == subcategory
    assert c.is_noise is is_noise


def test_user_facing_letters_are_configurable():
    from tmdl_preflight.measure_classes import classify_measure_name

    c = classify_measure_name("z-Toggle Price", options={"user_facing_letters": []})
    assert c.is_helper is True and c.subcategory == "intermediary_helper"
