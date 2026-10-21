"""The DAX contracts: the universe self-test of the reference contracts, the
predicate whitespace of the flag check, the canary literal, the tolerant
numerator brackets of the guarded ratio and the arm label of the scoped
filter.

Every fixture is fictional: a delivery model with a cost measure, a flag
table and a blended measure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check

TAG = "3c4d5e6f-0000-4000-8000-{:012d}"


def _table(d: Path, name: str, cols: list[str], extra: str = "", n: int = 1) -> None:
    body = f"table '{name}'\n\tlineageTag: {TAG.format(n)}\n\n"
    for k, (c, t) in enumerate(cols):
        body += (f"\tcolumn {c}\n\t\tdataType: {t}\n\t\tlineageTag: {TAG.format(n * 100 + k)}\n"
                 f"\t\tsourceColumn: {c}\n\n")
    body += extra
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = Sql.Database(\"s\", \"d\")\n"
    (d / f"{name}.tmdl").write_text(body, encoding="utf-8")


def _model(tmp_path: Path, measures: str, flags: list[tuple[str, str]] | None = None,
           selector: str = "z-Selector Attribution Basis") -> Path:
    d = tmp_path / "Delivery.SemanticModel" / "definition"
    t = d / "tables"
    t.mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    _table(t, "Campaigns", [("cost", "decimal"), ("leads", "int64")], n=1)
    _table(t, "Accounts", [("account_id", "string")], n=2)
    _table(t, selector, [("basis", "string")], n=3)
    if flags is None:
        flags = [("has_new", "int64"), ("has_limbo", "boolean")]
    _table(t, "Subscriptions", flags, n=4)
    _table(t, "#Report Measures", [], n=5, extra=measures)
    return d.parent


def _violations(payload: dict, *needles: str) -> list[dict]:
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in payload["violations"] if all(n in v["message"] for n in needles)]


# ---------------------------------------------------------------------------
# CG-15: the universe self-test
# ---------------------------------------------------------------------------


def test_one_model_with_the_anchor_reports_the_universe_finding(tmp_path):
    """A contract that names a template model and a minimum universe reports
    the discovery when the run sees too few models."""
    measures = ("\tmeasure '-helper Paid Surface' =\n\t\t\t1\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    config = {"rules": {"measure-reference-contract": {"contracts": [{
        "kind": "must_not_reference",
        "table": "#Report Measures",
        "measure": "-helper Paid Surface",
        "tables": ["_Queries"],
        "template": "Delivery",
        "min_universe": 2,
    }]}}}
    code, payload = run_check(model, "measure-reference-contract", config=config)
    assert code == 1
    found = _violations(payload, "universe")
    assert len(found) == 1
    assert "discovery is broken" in found[0]["message"]


def test_the_minimum_universe_defaults_to_two(tmp_path):
    """A contract that only names a template still needs two models."""
    measures = ("\tmeasure '-helper Paid Surface' =\n\t\t\t1\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    config = {"rules": {"measure-reference-contract": {"contracts": [{
        "kind": "must_not_reference",
        "table": "#Report Measures",
        "measure": "-helper Paid Surface",
        "tables": ["_Queries"],
        "template": "Delivery",
    }]}}}
    code, payload = run_check(model, "measure-reference-contract", config=config)
    assert code == 1
    assert len(_violations(payload, "universe")) == 1


# ---------------------------------------------------------------------------
# CG-16: a commented-out DIVIDE is not live DAX
# ---------------------------------------------------------------------------


def test_a_commented_out_divide_is_not_reported(tmp_path):
    measures = ("\tmeasure 'Cost/ Lead' =\n"
                "\t\t\t-- DIVIDE([Cost], [Leads])\n"
                "\t\t\tDIVIDE([^Cost], [Leads])\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    config = {"rules": {"measure-reference-contract": {"contracts": [{
        "kind": "must_not_divide",
        "table": "#Report Measures",
        "measures": "*Cost/*",
        "raw_measure": "Cost",
    }]}}}
    code, payload = run_check(model, "measure-reference-contract", config=config)
    assert code == 0
    assert _violations(payload, "divides the raw") == []


def test_a_live_divide_of_the_raw_measure_is_reported(tmp_path):
    measures = ("\tmeasure 'Cost/ Lead' =\n"
                "\t\t\tDIVIDE([Cost], [Leads])\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    config = {"rules": {"measure-reference-contract": {"contracts": [{
        "kind": "must_not_divide",
        "table": "#Report Measures",
        "measures": "*Cost/*",
        "raw_measure": "Cost",
    }]}}}
    code, payload = run_check(model, "measure-reference-contract", config=config)
    assert code == 1
    assert _violations(payload, "divides the raw")


# ---------------------------------------------------------------------------
# CG-17: the predicate whitespace
# ---------------------------------------------------------------------------


def _flag_config(min_predicates: int = 0, canaries=None) -> dict:
    return {"rules": {"typed-flag-predicates": {
        "model": "Delivery",
        "table": "Subscriptions",
        "prefix": "has_",
        "measures_files": ["#Report Measures"],
        "min_predicates": min_predicates,
        "canaries": canaries or [],
    }}}


def test_a_predicate_with_free_whitespace_is_recognised(tmp_path):
    measures = ("\tmeasure 'Subs #' =\n"
                "\t\t\tCOUNTROWS(FILTER(Subscriptions, Subscriptions[has_new ]  >  0))\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    code, payload = run_check(model, "typed-flag-predicates", config=_flag_config(
        min_predicates=1, canaries=[["has_new", ">", "0"]]))
    assert code == 0
    assert _violations(payload) == []


def test_a_tab_separated_predicate_is_recognised(tmp_path):
    measures = ("\tmeasure 'Subs #' =\n"
                "\t\t\tCOUNTROWS(FILTER(Subscriptions, Subscriptions[has_new]\t>\t0))\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    code, payload = run_check(model, "typed-flag-predicates", config=_flag_config(
        min_predicates=1, canaries=[["has_new", ">", "0"]]))
    assert code == 0
    assert _violations(payload) == []


def test_a_count_flag_compared_to_one_is_reported_with_free_whitespace(tmp_path):
    measures = ("\tmeasure 'Subs #' =\n"
                "\t\t\tCOUNTROWS(FILTER(Subscriptions, Subscriptions[has_new ]  =  1))\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    code, payload = run_check(model, "typed-flag-predicates", config=_flag_config())
    assert code == 1
    assert _violations(payload, "has_new is a count")


# ---------------------------------------------------------------------------
# CG-18: the canary literal
# ---------------------------------------------------------------------------


def test_the_canary_literal_drops_a_trailing_pair_of_parentheses(tmp_path):
    """The model writes `= TRUE()`, the canary asks for `= TRUE`."""
    measures = ("\tmeasure 'Subs #' =\n"
                "\t\t\tCOUNTROWS(FILTER(Subscriptions, Subscriptions[has_limbo] = TRUE()))\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    code, payload = run_check(model, "typed-flag-predicates", config=_flag_config(
        min_predicates=1, canaries=[["has_limbo", "=", "TRUE"]]))
    assert code == 0
    assert _violations(payload) == []


def test_the_canary_literal_stays_case_sensitive(tmp_path):
    """The model writes `= true()`, the canary asks for `= TRUE`."""
    measures = ("\tmeasure 'Subs #' =\n"
                "\t\t\tCOUNTROWS(FILTER(Subscriptions, Subscriptions[has_limbo] = true()))\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n")
    model = _model(tmp_path, measures)
    code, payload = run_check(model, "typed-flag-predicates", config=_flag_config(
        min_predicates=1, canaries=[["has_limbo", "=", "TRUE"]]))
    assert code == 1
    assert len(_violations(payload, "canary predicate")) == 1


# ---------------------------------------------------------------------------
# CG-19: the tolerant numerator brackets
# ---------------------------------------------------------------------------


def test_a_ratio_with_whitespace_inside_the_numerator_is_wrapped(tmp_path):
    """`DIVIDE ( [ Cost ] , [Accounts #] )` is the same ratio."""
    measures = ("\tmeasure 'Cost/ Account' =\n"
                "\t\t\tDIVIDE ( [ Cost ] , [Accounts #] )\n"
                "\t\tlineageTag: " + TAG.format(2001) + "\n\n"
                "\tmeasure 'Accounts #' =\n"
                "\t\t\tCALCULATE ( COUNTROWS ( Accounts ), SELECTEDVALUE ( 'z-Selector "
                "Attribution Basis'[basis] ) )\n"
                "\t\tlineageTag: " + TAG.format(2002) + "\n\n")
    model = _model(tmp_path, measures)
    config = {"rules": {"guarded-ratio-wrapper": {
        "model": "Delivery",
        "host_table": "#Report Measures",
        "selector_table": "z-Selector Attribution Basis",
        "numerators": ["Cost"],
        "guard": "-helper Window Guard",
        "boundary": "-helper Window Boundary",
        "measured_option": "measured",
        "enhanced_option": "enhanced",
    }}}
    code, payload = run_check(model, "guarded-ratio-wrapper", config=config)
    assert code == 1
    found = _violations(payload, "not wrapped in")
    assert len(found) == 1
    assert "Cost/ Account" in found[0]["message"]


# ---------------------------------------------------------------------------
# CG-20: the arm label outside every arm
# ---------------------------------------------------------------------------


def test_a_mention_outside_every_arm_is_named_outside_any_arm(tmp_path):
    measures = ("\tmeasure 'Blended Cost' =\n"
                "\t\t\tVAR outside = Campaigns[campaign_id]\n"
                "\t\t\tRETURN\n"
                "\t\t\t\t\"search_term\",\n"
                "\t\t\t\t\tCALCULATE ( [Cost], KEEPFILTERS ( NOT Campaigns[campaign_id] "
                "IN { \"x\" } ) )\n")
    model = _model(tmp_path, measures)
    config = {"rules": {"measure-arm-scoped-filter": {
        "template": "Delivery",
        "host_table": "#Report Measures",
        "measure": "Blended Cost",
        "column": "Campaigns[campaign_id]",
        "target_arm": "search_term",
    }}}
    code, payload = run_check(model, "measure-arm-scoped-filter", config=config)
    assert code == 1
    found = _violations(payload, "'outside any arm' arm")
    assert len(found) == 1


pytestmark = pytest.mark.layer1
