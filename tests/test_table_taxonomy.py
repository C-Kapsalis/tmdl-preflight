"""Fact-table identification (D-fact-table-identification, one shared
definition with A-table-roles): name law plus structure law.

API: ``tmdl_preflight.roles.fact_tables(model)`` over a model parsed with
``tmdl_preflight.parser.parse_model``. Stand-in tables cover spec cases 1-9;
only ``Orders`` is a fact (recorded from the earlier check classifier).
"""
from __future__ import annotations

from tmdl_preflight.parser import parse_model

STANDIN = "layer3_integration_standin"


def test_only_orders_is_a_fact(stand_in):
    from tmdl_preflight.roles import fact_tables

    definition = stand_in(STANDIN) / "taxo_db" / "Taxo.SemanticModel" / "definition"
    assert sorted(fact_tables(parse_model(definition))) == ["Orders"]


def test_roastery_facts(stand_in):
    from tmdl_preflight.roles import fact_tables

    root = stand_in(STANDIN)
    assert sorted(fact_tables(parse_model(root / "universal" / "Performance.SemanticModel" / "definition"))) == [
        "Orders", "Visits"]
    assert sorted(fact_tables(parse_model(root / "failing_db" / "Performance.SemanticModel" / "definition"))) == [
        "Orders", "Refunds", "Visits"]
