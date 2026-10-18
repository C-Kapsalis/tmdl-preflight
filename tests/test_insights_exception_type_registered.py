"""'MCP Tool Calls'[exception_type] exists and stays registered on the error axis
(specs A-model-contract-objects, A-fieldparam-registration-contract).

A column present in the model but registered in no field parameter is
silently unreachable: nothing fails, the dimension simply never appears in
any slicer or query tool that resolves fields through the field parameters.
The original pinned this with module constants pointing at one model; the port
expresses the same two assertions as declared contracts in the tool config.

Stand-in: tests/fixtures/b3-a2/insights_contract/roastery (model
``spinout_02_db/insights``), fictional rows.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

MODEL = "b3-a2/insights_contract/roastery"
DEFINITION = "spinout_02_db/insights.SemanticModel/definition"


@pytest.fixture
def model(stand_in):
    return stand_in(MODEL)


def _check(root, rule, contracts):
    return run_check(root, rule, config={"contracts": contracts})


def test_exception_type_column_exists(model):
    """The column itself. If this fails the sync dropped it."""
    contracts = {"objects": [{"kind": "column_exists", "table": "MCP Tool Calls",
                              "column": "exception_type"}]}
    code, payload = _check(model, "model-contract-objects", contracts)
    assert code == 0 and violations(payload) == [], payload

    # negative: the column removed -> one finding
    f = model / DEFINITION / "tables" / "MCP Tool Calls.tmdl"
    f.write_text(f.read_text(encoding="utf-8").replace("column exception_type", "column exception_kind"),
                 encoding="utf-8")
    code, payload = _check(model, "model-contract-objects", contracts)
    assert code == 1 and len(violations(payload)) == 1


def test_exception_type_is_registered_in_mcp_activity_y(model):
    """The registration: without it the column is unreachable."""
    contracts = {"fieldparam": [{"kind": "column_registered", "table": "y-Selector 1",
                                 "column": "exception_type",
                                 "groups": ["mcp_errors_y", "mcp_activity_y"],
                                 "range": [1486, 1499]}]}
    code, payload = _check(model, "fieldparam-registration-contract", contracts)
    assert code == 0 and violations(payload) == [], payload

    # negative: ordinal moved outside the free gap 1486-1499
    f = model / DEFINITION / "tables" / "y-Selector 1.tmdl"
    f.write_text(f.read_text(encoding="utf-8").replace("[exception_type]), 1486,", "[exception_type]), 1500,"),
                 encoding="utf-8")
    code, payload = _check(model, "fieldparam-registration-contract", contracts)
    assert code == 1 and "1500" in violations(payload)[0]["message"]
