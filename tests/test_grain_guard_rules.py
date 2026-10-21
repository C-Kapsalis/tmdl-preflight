"""The contract and grain-guard rules: the numeric floor of a guarded ratio,
the re-check gate of the policy exception, the below-grain skip, the helper
discovery of the reach guards and the two reach-guard self-tests.

Every fixture here is fictional: a delivery model with a cost fact, a
backend fact and the helpers that guard them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check

TAG = "3c4d5e6f-0000-4000-8000-{:012d}"

GUARD = "-helper Cost Grain Valid"
HELPER = "-helper Filter Misses Users"
REACH = "-helper Slicer Cannot Reach Users"


def _table(d: Path, name: str, cols: list[str], extra: str = "", n: int = 1) -> None:
    body = f"table '{name}'\n\tlineageTag: {TAG.format(n)}\n\n"
    for k, c in enumerate(cols):
        body += (f"\tcolumn {c}\n\t\tdataType: string\n\t\tlineageTag: {TAG.format(n * 100 + k)}\n"
                 f"\t\tsourceColumn: {c}\n\n")
    body += extra
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = Sql.Database(\"s\", \"d\")\n"
    (d / f"{name}.tmdl").write_text(body, encoding="utf-8")


def _engine_term(table: str, key: str) -> str:
    return (f"\t\t\tISFILTERED ( '{table}' ) && NOT CALCULATE ( ISCROSSFILTERED ( Campaigns ), "
            f"REMOVEFILTERS (), VALUES ( '{table}'[{key}] ) )")


def _model(tmp_path: Path, guard_body: str, helpers: dict[str, str],
           ratio: str = "", policy: str = "", rels: str = "") -> Path:
    d = tmp_path / "Delivery.SemanticModel" / "definition"
    t = d / "tables"
    t.mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    _table(t, "Campaigns", ["campaign_id", "country_id", "user_id"], n=1)
    _table(t, "Transactions", ["transaction_id", "user_id", "country_id"], n=2)
    _table(t, "_Users", ["user_id", "country_id"], n=3)
    _table(t, "_Countries", ["country_id", "Country"], n=4)
    measures = f"\tmeasure '{GUARD}' = ```\n{guard_body}\n\t\t\t```\n" \
               f"\t\tlineageTag: {TAG.format(2001)}\n\n"
    for name, body in helpers.items():
        measures += (f"\tmeasure '{name}' = ```\n{body}\n\t\t\t```\n"
                     f"\t\tlineageTag: {TAG.format(2100 + len(measures))}\n\n")
    if ratio:
        measures += (f"\tmeasure 'Cost/ Lead' =\n\t\t\t{ratio}\n"
                     f"\t\tlineageTag: {TAG.format(2900)}\n\n")
    if policy:
        measures += f"\tmeasure '-helper Lead Policy Filter Only' = ```\n{policy}\n\t\t\t```\n" \
                    f"\t\tlineageTag: {TAG.format(2950)}\n\n"
    _table(t, "#Backend Measures", [], n=20, extra=measures)
    (t / "y-Selector 1.tmdl").write_text(
        "table 'y-Selector 1'\n\tlineageTag: {TAG.format(30)}\n\n"
        "\tpartition 'y-Selector 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\t{ (\"Country\", NAMEOF('_Countries'[Country]), 0) }\n", encoding="utf-8")
    (d / "relationships.tmdl").write_text(rels, encoding="utf-8")
    return d.parent


def _violations(payload: dict, *needles: str) -> list[dict]:
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in payload["violations"] if all(n in v["message"] for n in needles)]


RELS = (
    "relationship r1\n\tfromColumn: Campaigns.user_id\n\ttoColumn: _Users.user_id\n\n"
    "relationship r2\n\tfromColumn: Transactions.user_id\n\ttoColumn: _Users.user_id\n\n"
    "relationship r3\n\tfromColumn: Campaigns.country_id\n\ttoColumn: _Countries.country_id\n\n"
)


# ---------------------------------------------------------------------------
# CG-6: the numeric floor of a guarded ratio
# ---------------------------------------------------------------------------


def test_a_numeric_floor_with_free_whitespace_is_reported(tmp_path):
    """A floor written with two spaces on each side of the sign is a floor."""
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {},
                   ratio="IF ( [-helper Cost Grain Valid], DIVIDE ( [Cost], [Leads #] ), "
                         "IF ( [Leads #]  <  5, BLANK (), [Cost] ) )")
    config = {"rules": {"grain-guard-coverage": {"models": {"m": {
        "model": "Delivery",
        "guard_table": "#Backend Measures",
        "guard_measure": GUARD,
        "guarded_ratios": ["Cost/ Lead"],
    }}}}}
    code, payload = run_check(model, "grain-guard-coverage", config=config)
    assert code == 1
    assert _violations(payload, "numeric floor")


def test_a_ratio_without_a_floor_is_not_reported(tmp_path):
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {},
                   ratio="IF ( [-helper Cost Grain Valid], DIVIDE ( [Cost], [Leads #] ), [Cost] )")
    config = {"rules": {"grain-guard-coverage": {"models": {"m": {
        "model": "Delivery",
        "guard_table": "#Backend Measures",
        "guard_measure": GUARD,
        "guarded_ratios": ["Cost/ Lead"],
    }}}}}
    code, payload = run_check(model, "grain-guard-coverage", config=config)
    assert code == 0
    assert _violations(payload, "numeric floor") == []


# ---------------------------------------------------------------------------
# CG-7: the OR-chain depth applies to every measure by default
# ---------------------------------------------------------------------------


def test_an_over_long_chain_in_any_measure_is_reported(tmp_path):
    """The rule reads every measure and calculated column, not only the
    configured grain-guard measure."""
    terms = " || ".join(f"ISFILTERED('_Countries'[c{i}])" for i in range(62))
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {},
                   ratio=f"VAR a = {terms}\nRETURN a")
    code, payload = run_check(model, "dax-or-chain-depth")
    assert code == 1
    assert len(_violations(payload, "61")) == 1


def test_the_configured_measure_list_narrows_the_scope(tmp_path):
    terms = " || ".join(f"ISFILTERED('_Countries'[c{i}])" for i in range(62))
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {},
                   ratio=f"VAR a = {terms}\nRETURN a")
    config = {"rules": {"dax-or-chain-depth": {"or_chain_measures": [GUARD]}}}
    code, payload = run_check(model, "dax-or-chain-depth", config=config)
    assert code == 0
    assert _violations(payload) == []


# ---------------------------------------------------------------------------
# CG-8: the re-check gate matches the whole variable name
# ---------------------------------------------------------------------------


POLICY_GOOD = (
    "\t\t\tVAR coverageFloor = 0.95\n"
    "\t\t\tVAR recheck = CALCULATE ( [-helper Cost Grain Valid], REMOVEFILTERS ( '_Users'[country_id] ) )\n"
    "\t\t\tRETURN IF ( NOT ISINSCOPE ( '_Users'[country_id] ) && recheck = 1, coverageFloor, 0 )"
)

POLICY_PREFIXED = (
    "\t\t\tVAR coverageFloor = 0.95\n"
    "\t\t\tVAR recheck = CALCULATE ( [-helper Cost Grain Valid], REMOVEFILTERS ( '_Users'[country_id] ) )\n"
    "\t\t\tRETURN IF ( NOT ISINSCOPE ( '_Users'[country_id] ) && notrecheck = 1, coverageFloor, 0 )"
)


def _policy_config() -> dict:
    return {"rules": {"grain-policy-exception": {
        "model": "Delivery",
        "helper": "-helper Lead Policy Filter Only",
        "guard": GUARD,
        "policy_column": "'_Users'[country_id]",
    }}}


def test_the_re_check_gate_needs_the_whole_variable_name(tmp_path):
    """`notrecheck = 1` is not the re-check the rule asks for."""
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {}, policy=POLICY_PREFIXED)
    code, payload = run_check(model, "grain-policy-exception", config=_policy_config())
    assert code == 1
    assert _violations(payload, "does not require")


def test_the_re_check_gate_accepts_the_whole_variable_name(tmp_path):
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {}, policy=POLICY_GOOD)
    code, payload = run_check(model, "grain-policy-exception", config=_policy_config())
    assert code == 0
    assert _violations(payload) == []


# ---------------------------------------------------------------------------
# CG-9: the below-grain check reports its skip
# ---------------------------------------------------------------------------


def test_the_below_grain_check_names_its_skip(tmp_path):
    """A model without the host table skips the check, and says so."""
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {})
    config = {"rules": {"grain-guard-coverage": {"below": {
        "model": "Delivery",
        "host_table": "#Absent Measures",
        "guards": {"Cost/ Lead": ["_Countries"]},
    }}}}
    code, payload = run_check(model, "grain-guard-coverage", config=config)
    assert code == 0
    assert payload["violations"] == []
    notes = " ".join(payload["notes"])
    assert "below-grain" in notes and "#Absent Measures" in notes


# ---------------------------------------------------------------------------
# CG-10: the reach guards find their own helpers
# ---------------------------------------------------------------------------


def _reach_config(helpers: list[str], reference: str = HELPER) -> dict:
    return {"rules": {"reach-guard-helper-consistency": {
        "model": "Delivery",
        "host_table": "#Backend Measures",
        "helpers": helpers,
        "reference_helper": reference,
        "min_filter_misses": 1,
        "canary": ["_Users", "user_id"],
        "exclusions": {"_Countries": "conformed"},
        "natural_keys": {},
    }}}


def test_a_helper_outside_the_configuration_is_still_checked(tmp_path):
    """A helper with the family prefix is discovered and compared with the
    reference, even when the configuration does not name it."""
    helpers = {
        HELPER: _engine_term("_Users", "user_id"),
        REACH: _engine_term("_Users", "user_id"),
        "-helper Filter Misses Campaigns": _engine_term("_Users", "user_id"),
    }
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", helpers, rels=RELS)
    code, payload = run_check(model, "reach-guard-helper-consistency",
                              config=_reach_config([HELPER, REACH]))
    assert code == 0
    assert _violations(payload) == []

    # the same model, with the discovered helper naming another dimension
    other = dict(helpers)
    other["-helper Filter Misses Campaigns"] = _engine_term("_Countries", "country_id")
    model = _model(tmp_path / "b", "\t\t\tISFILTERED ( '_Countries' )", other, rels=RELS)
    code, payload = run_check(model, "reach-guard-helper-consistency",
                              config=_reach_config([HELPER, REACH]))
    assert code == 1
    assert _violations(payload, "-helper Filter Misses Campaigns", "misses")


# ---------------------------------------------------------------------------
# CG-11: the reach-guard self-tests
# ---------------------------------------------------------------------------


def _guard_config(min_active_edges=None) -> dict:
    guard = {"fact": "Campaigns", "guarded": ["_Offers"], "controls": ["_Users"],
             "guard_measure": {"table": "#Backend Measures", "measure": GUARD}}
    if min_active_edges is not None:
        guard["min_active_edges"] = min_active_edges
    return {"rules": {"model-contract-relationships": {"reach_guards": [guard]}}}


def test_a_fact_with_no_active_edge_is_reported(tmp_path):
    """The 'some active relationship touches the fact' self-test runs for
    every reach guard, even without a floor."""
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {},
                   rels="relationship r1\n\tfromColumn: Transactions.user_id\n"
                        "\ttoColumn: _Users.user_id\n\n")
    code, payload = run_check(model, "model-contract-relationships",
                              config=_guard_config())
    assert code == 1
    assert _violations(payload, "no active relationship touches 'Campaigns'")


def test_two_parallel_active_edges_count_once_against_the_floor(tmp_path):
    """Two active relationships between the same two tables are one edge."""
    rels = RELS + (
        "relationship r4\n\tfromColumn: Campaigns.country_id\n"
        "\ttoColumn: _Users.country_id\n\n"
    )
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {}, rels=rels)
    code, payload = run_check(model, "model-contract-relationships",
                              config=_guard_config(min_active_edges=4))
    assert code == 1
    assert _violations(payload, "only 3 active relationship(s) parsed")


# ---------------------------------------------------------------------------
# CG-12: no relationships file means the axis contract is skipped
# ---------------------------------------------------------------------------


def test_a_model_without_a_relationships_file_skips_the_axis_contract(tmp_path):
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Countries' )", {}, rels=RELS)
    (model / "definition" / "relationships.tmdl").unlink()
    config = {"rules": {"model-contract-relationships": {"axes": [{
        "model": "Delivery",
        "dimension": "_Users",
        "sanctioned": [{"table": "Campaigns", "column": "user_id"}],
    }]}}}
    code, payload = run_check(model, "model-contract-relationships", config=config)
    assert code == 0
    assert _violations(payload, "contracted edge") == []


pytestmark = pytest.mark.layer1
