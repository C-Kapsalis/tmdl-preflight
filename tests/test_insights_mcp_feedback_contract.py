"""The MCP Feedback contract (specs A-model-contract-objects,
A-model-contract-relationships, A-fieldparam-registration-contract).

Invariants the model would otherwise lose silently:

1. EXACTLY ONE ACTIVE RELATIONSHIP out of 'MCP Feedback'. Feedback gets org /
   user / date / category by riding an existing chain, not by direct
   relationships; a second active one forms a second path and Power BI
   resolves that by silently deactivating a relationship someone chose.
2. THE __Calendar RELATIONSHIP IS INACTIVE. Every measure in this family
   activates its own date relationship via USERELATIONSHIP; an active one
   would change every existing measure's result with no code change.
3. 'MCP Feedback'[user_id] IS TEXT, to match the user dimension it is looked
   up against; "aligning" it to an int64 sibling silently blanks the
   internal/external split (most early rows were internal staff).
4. The analysis category is RECONSTRUCTED by a calculated column (last
   categorised call strictly before the feedback, TOPN with an id tiebreaker),
   coverage measures render 0 not BLANK, and the rate scopes its denominator.
5. The measures and dimensions are registered in the field parameters inside
   their free ordinal gaps, with no duplicate ordinals.

The earlier check pinned these on one model through module constants;
the tool
expresses each as a declared contract in the tool config and asserts the
contract rule is clean on the stand-in (tests/fixtures/b3-a2/insights_contract,
model ``spinout_02_db/insights``, fictional rows). Each test also breaks the
stand-in once and expects the finding.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

MODEL = "b3-a2/insights_contract/roastery"
DEFINITION = "spinout_02_db/insights.SemanticModel/definition"
TABLES = DEFINITION + "/tables"

EXPECTED_MEASURES = [
    "MCP Feedback #",
    "MCP Feedback Open #",
    "MCP Feedback Bugs #",
    "MCP Feedback Feature Requests #",
    "MCP Customer Feedback #",
    "MCP Feedback Orgs #",
    "MCP Feedback Oldest Open (days)",
    "MCP Feedback Unlinked #",
    "MCP Feedback Untrusted Text #",
    "MCP Feedback Uncategorized #",
    "MCP Feedback per 100 Tool Calls",
]
COVERAGE_MEASURES = ["MCP Feedback Unlinked #", "MCP Feedback Uncategorized #"]

# mcp_activity_y ends at 1485 and the next group starts at 1500;
# mcp_activity_x ends at 1615 and the next group starts at 1700.
Y_ORDINAL_RANGE = [1486, 1499]
X_ORDINAL_RANGE = [1616, 1699]


@pytest.fixture
def model(stand_in):
    return stand_in(MODEL)


def _check(root, rule, contracts):
    return run_check(root, rule, config={"contracts": contracts})


def _clean(root, rule, contracts):
    code, payload = _check(root, rule, contracts)
    assert code == 0 and violations(payload) == [], payload


def _breaks(root, rule, contracts, rel_path, old, new):
    f = root / rel_path
    text = f.read_text(encoding="utf-8")
    assert old in text, old
    f.write_text(text.replace(old, new, 1), encoding="utf-8")
    code, payload = _check(root, rule, contracts)
    assert code == 1 and violations(payload), payload


def test_mcp_feedback_table_exists(model):
    c = {"objects": [{"kind": "table_exists", "table": "MCP Feedback"}]}
    _clean(model, "model-contract-objects", c)
    (model / TABLES / "MCP Feedback.tmdl").unlink()
    code, payload = _check(model, "model-contract-objects", c)
    assert code == 1 and violations(payload)


def test_mcp_feedback_has_exactly_one_active_relationship(model):
    c = {"relationships": [{"kind": "table_edges", "from_table": "MCP Feedback", "active": 1,
                            "active_edge": ["'MCP Feedback'.last_tool_call_id", "'MCP Tool Calls'.id"]}]}
    _clean(model, "model-contract-relationships", c)
    # a second active edge out of the table
    _breaks(model, "model-contract-relationships", c, DEFINITION + "/relationships.tmdl",
            "\tisActive: false\n\tfromColumn: 'MCP Feedback'.org_id", "\tfromColumn: 'MCP Feedback'.org_id")


def test_mcp_feedback_calendar_relationship_is_inactive(model):
    c = {"relationships": [{"kind": "edge_to", "from_table": "MCP Feedback", "to": "__Calendar.Date",
                            "count": 1, "active": False}]}
    _clean(model, "model-contract-relationships", c)
    _breaks(model, "model-contract-relationships", c, DEFINITION + "/relationships.tmdl",
            "\tisActive: false\n\tfromColumn: 'MCP Feedback'.date", "\tfromColumn: 'MCP Feedback'.date")


def test_mcp_feedback_user_id_is_text(model):
    """Guards the deliberate divergence from an int64 sibling column."""
    c = {"objects": [{"kind": "column_datatype", "table": "MCP Feedback", "column": "user_id",
                      "dataType": "string"}]}
    _clean(model, "model-contract-objects", c)
    f = model / TABLES / "MCP Feedback.tmdl"
    text = f.read_text(encoding="utf-8")
    f.write_text(text.replace("column user_id\n\t\tdataType: string", "column user_id\n\t\tdataType: int64"),
                 encoding="utf-8")
    code, payload = _check(model, "model-contract-objects", c)
    assert code == 1 and violations(payload)


def test_feedback_analysis_category_is_reconstructed_not_joined(model):
    c = {"objects": [
        {"kind": "calculated_column_exists", "table": "MCP Feedback", "column": "Session Key"},
        {"kind": "calculated_column_contains", "table": "MCP Feedback",
         "column": "Analysis Category at Submit",
         "tokens": ["'MCP Tool Calls'[created_at] < SubmittedAt", "TOPN", "NOT ISBLANK",
                    "'MCP Tool Calls'[id], DESC"]},
    ]}
    _clean(model, "model-contract-objects", c)
    # TOPN without the id tiebreaker is non-deterministic on ties
    _breaks(model, "model-contract-objects", c, TABLES + "/MCP Feedback.tmdl",
            ", 'MCP Tool Calls'[id], DESC)", ")")


def test_mcp_feedback_measures_present_and_date_aware(model):
    c = {"objects": [
        {"kind": "measures_exist", "table": "MCP Feedback Measures", "measures": EXPECTED_MEASURES},
        {"kind": "measure_contains", "table": "MCP Feedback Measures", "measure": "MCP Feedback #",
         "tokens": ["USERELATIONSHIP", "'MCP Feedback'[date]"]},
    ]}
    _clean(model, "model-contract-objects", c)
    _breaks(model, "model-contract-objects", c, TABLES + "/MCP Feedback Measures.tmdl",
            ", USERELATIONSHIP(__Calendar[Date], 'MCP Feedback'[date])", "")


def test_coverage_measures_render_zero_not_blank(model):
    c = {"objects": [
        {"kind": "measure_contains", "table": "MCP Feedback Measures", "measure": name,
         "tokens": ["COALESCE", "ISBLANK(Total)"], "until": "displayFolder"}
        for name in COVERAGE_MEASURES
    ]}
    _clean(model, "model-contract-objects", c)
    _breaks(model, "model-contract-objects", c, TABLES + "/MCP Feedback Measures.tmdl",
            "COALESCE(CALCULATE([MCP Feedback #], ISBLANK('MCP Feedback'[last_tool_call_id])), 0)",
            "CALCULATE([MCP Feedback #], ISBLANK('MCP Feedback'[last_tool_call_id]))")


def test_feedback_rate_scopes_its_denominator_by_category(model):
    c = {"objects": [
        {"kind": "measure_contains", "table": "MCP Feedback Measures",
         "measure": "MCP Feedback per 100 Tool Calls", "until": "formatString",
         "tokens": ["ISFILTERED('MCP Feedback'[Analysis Category at Submit])", "TREATAS",
                    "'MCP Tool Calls'[Analysis Category]"]},
    ]}
    _clean(model, "model-contract-objects", c)
    _breaks(model, "model-contract-objects", c, TABLES + "/MCP Feedback Measures.tmdl",
            "TREATAS(", "KEEPFILTERS(")


def test_feedback_measures_registered_in_x_selector_1(model):
    c = {"fieldparam": [
        {"kind": "group_labels", "table": "x-Selector 1", "group": "mcp_feedback_x",
         "labels": EXPECTED_MEASURES},
        {"kind": "group_ordinal_range", "table": "x-Selector 1", "group": "mcp_feedback_x",
         "marker": "Feedback", "range": X_ORDINAL_RANGE},
    ]}
    _clean(model, "fieldparam-registration-contract", c)
    _breaks(model, "fieldparam-registration-contract", c, TABLES + "/x-Selector 1.tmdl",
            "[MCP Feedback Orgs #]), 1621,", "[MCP Feedback Orgs #]), 1700,")


def test_feedback_dimensions_registered_in_y_selector_1_without_collision(model):
    c = {"fieldparam": [
        {"kind": "group_table_rows", "table": "y-Selector 1", "group": "mcp_feedback_y",
         "references": "'MCP Feedback'", "count": 8},
        {"kind": "group_ordinal_range", "table": "y-Selector 1", "group": "mcp_feedback_y",
         "marker": "'MCP Feedback'", "range": Y_ORDINAL_RANGE},
        {"kind": "group_unique_ordinals", "table": "y-Selector 1", "group": "mcp_feedback_y"},
    ]}
    _clean(model, "fieldparam-registration-contract", c)
    # a duplicate ordinal inside the group
    _breaks(model, "fieldparam-registration-contract", c, TABLES + "/y-Selector 1.tmdl",
            "[status]), 1490,", "[status]), 1489,")
