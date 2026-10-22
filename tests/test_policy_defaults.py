"""Policy thresholds as documented rule option defaults. A boolean toggle set to false SKIPS its
check (reported as skipped, exit 0); the skip behaviour itself is exercised
next to each rule's test (see the ``test_disabled_by_policy_is_skipped``
tests). Policy keys no check reads have no option.
"""
from __future__ import annotations

import json

import pytest

from conftest import run_check, run_cli, violations

# (rule id or name, option, default) - one row per consumed policy key
DEFAULTS = [
    ("D001", "min_success_rate", 0.90),                                   # dax_parsing.min_success_rate
    ("R001", "min_endpoint_success_rate", 0.95),                          # relationships.min_endpoint_success_rate
    ("fact-calendar-coverage", "require_fact_link", True),                # calendar_relationships.require_fact_table_calendar_link
    ("fact-calendar-coverage", "min_fact_coverage_percent", 90.0),        # calendar_relationships.min_calendar_coverage_percent
    ("user-facing-measure-description", "enabled", True),                 # documentation.require_user_facing_descriptions
    ("user-facing-measure-description", "min_length", 10),                # documentation.min_description_length
    ("dimension-key-columns", "require_dimension_keys", True),            # keys.require_dimension_primary_keys
    ("field-parameter-partition-shape", "validate_field_parameter_pattern", True),  # partitions.validate_field_parameter_pattern
    ("required-calc-groups", "format_selector", True),                    # calc_groups.require_format_selector
    ("required-calc-groups", "time_intelligence_selector", True),         # calc_groups.require_time_intelligence_selector
    ("fieldparam-category-required", "require_category", True),           # field_parameters.require_4_parameter_pattern
    ("mapping-table-required-columns", "enabled", True),                  # z_map.require_z_map_table
]


@pytest.fixture(scope="module")
def catalog():
    code, out, _ = run_cli("rules", "--json")
    assert code == 0
    return json.loads(out)


@pytest.mark.parametrize("rule,option,default", DEFAULTS, ids=[f"{r}.{o}" for r, o, _ in DEFAULTS])
def test_policy_default_value(catalog, rule, option, default):
    entry = next((r for r in catalog if rule in (r["id"], r["name"])), None)
    assert entry is not None, f"rule {rule} missing from the catalog"
    assert entry["options"][option] == default


def test_dax_success_rate_threshold_never_suppresses_per_expression_errors(project, definition):
    """With the share of clean expressions above the threshold there is no
    summary finding, but the per-measure D001 error still fails the run
    (STRICTER: every unbalanced expression is an error). The example model
    has 7 expressions, so the threshold is lowered to 0.8 to sit above 6/7."""
    f = definition / "tables" / "Sales Measures.tmdl"
    text = f.read_text(encoding="utf-8")
    f.write_text(text.rstrip("\n") + "\n\n\tmeasure 'Broken Paren' = SUM(Sales[quantity]\n"
                 "\t\tlineageTag: 8b6c7d9e-af01-4c12-d3e4-5f6a7b8c9d0e\n", encoding="utf-8")
    code, payload = run_check(project, "D001", config={"rules": {"D001": {"min_success_rate": 0.8}}})
    assert code == 1
    found = violations(payload, "D001")
    assert len(found) == 1 and "Broken Paren" in (found[0]["object"] or found[0]["message"])


def test_endpoint_success_rate_never_suppresses_r001_errors(project, definition):
    rel = definition / "relationships.tmdl"
    rel.write_text(rel.read_text(encoding="utf-8")
                   + "relationship 00000000-0000-4000-8000-00000000abcf\n"
                     "\tfromColumn: Sales.store_id\n\ttoColumn: Stores.no_such_column\n\n",
                   encoding="utf-8")
    code, payload = run_check(project, "R001", config={"rules": {"R001": {"min_endpoint_success_rate": 0.1}}})
    assert code == 1
    assert len(violations(payload, "R001")) == 1
