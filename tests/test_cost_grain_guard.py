"""Cost-grain guard coverage (spec A-grain-guard-coverage, variant A), its OR-chain
depth (B-dax-or-chain-depth), raw-cost ratios (B-measure-reference-contract) and the
narrow population-policy exception (B-grain-policy-exception).

Two earlier tests map to this file: the generic two-model gate (class TestGeneric)
and the one-model copy for the spinout-05 Growth model (class TestOneModel).
Both run on the fictional stand-in fleet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FIXTURES, run_check, violations

FLEET = "layer1_contract_fleet"
GROWTH_A = "spinout_12_db/Growth.SemanticModel"
GROWTH_E = "spinout_05_db/Growth.SemanticModel"
TEMPLATE = "universal/Performance.SemanticModel"
_MUTATIONS = json.loads((FIXTURES / f"{FLEET}.mutations.json").read_text(encoding="utf-8"))


def mutate(root: Path, name: str) -> None:
    """Apply one recorded stand-in mutation (the same edit the reference run used)."""
    for edit in _MUTATIONS[name]:
        rel, old, new = edit[:3]
        nth = edit[3] if len(edit) > 3 else None
        path = root / rel
        if old == "":
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            if text and not text.endswith("\n\n"):
                text += "\n"
            path.write_text(text + new, encoding="utf-8")
            continue
        text = path.read_text(encoding="utf-8")
        if nth is None:
            assert text.count(old) == 1, f"{name}: expected one match in {rel}"
            text = text.replace(old, new)
        else:
            idx = -1
            for _ in range(nth + 1):
                idx = text.index(old, idx + 1)
            text = text[:idx] + new + text[idx + len(old):]
        path.write_text(text, encoding="utf-8")


def mentioning(payload: dict, *needles: str) -> list[dict]:
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in violations(payload) if all(n in v["message"] for n in needles)]

pytestmark = [pytest.mark.layer1, pytest.mark.client]

GRAIN = "grain-guard-coverage"
OR_CHAIN = "dax-or-chain-depth"
CONTRACT = "measure-reference-contract"
POLICY = "grain-policy-exception"
GUARD = "-helper Cost Grain Valid"

CLIENTS = {
    "spinout-05": dict(
        model=GROWTH_E,
        guard_table="#Backend Measures",
        guard_measure=GUARD,
        blocked_tables=["_Attribution LM", "_Accounts", "_Campaigns", "_Devices", "_Landing Pages"],
        permitted_tables=["_Countries", "_CC1 Attribution"],
    ),
    "spinout-12": dict(
        model=GROWTH_A,
        guard_table="Client-a Measures",
        guard_measure=GUARD,
        blocked_tables=["_Offers", "_Accounts", "_Campaigns", "_Devices",
                        "_Landing Pages", "_Keywords", "_Queries", "_Countries", "_Ads",
                        "_Crawl", "_Assets", "_Competitors", "_Email Marketing Lists",
                        "_FB Organic Comments", "_FB Organic Pages", "_FB Organic Posts",
                        "_Youtube Channel", "_Youtube Playlist", "_Youtube Video"],
        permitted_tables=["_CC1 Attribution", "__Calendar", "_Users", "_CC1 Touch Role", "_Conversions"],
        reach_guard="-helper Slicer Cannot Reach Users",
        guarded_ratios=["Cost/ Account", "^Cost/ Account", "Cost/ New Client", "^Cost/ New Client"],
        reach_guard_overrides={"New Clients #": "-helper Slicer Cannot Reach Transactions"},
        guarded_counts=["Accounts #", "New Clients #",
                        "Paying Subscriptions from New Accounts #",
                        "Trial Starts from New Accounts #",
                        "Never Started from New Accounts #"],
    ),
}
# Tables with no registered axis column in the stand-in: the earlier check skips them
# (require_registered_columns = false).
UNREGISTERED = {("spinout-12", t) for t in CLIENTS["spinout-12"]["blocked_tables"]
                if t not in ("_Campaigns", "_Devices", "_Countries")}

GENERIC_CONFIG = {"rules": {GRAIN: {
    "axis_prefixes": ["y-Selector", "y-Plot Specific"],
    "models": {cid: cfg for cid, cfg in CLIENTS.items()},
}}}

ONE_MODEL_CONFIG = {"rules": {GRAIN: {
    "axis_prefixes": ["y-Selector", "y-Plot Specific"],
    "models": {"spinout-05": dict(
        model=GROWTH_E,
        guard_table="#Backend Measures",
        guard_measure=GUARD,
        blocked_tables=["_Attribution LM", "_Accounts", "_Campaigns", "_Devices", "_Landing Pages"],
        permitted_grains=["'_Countries'[Country Official Name]",
                          "'_Report Attribution'[m_main_attribution]",
                          "'_Report Attribution Resolved'[m_main_attribution_resolved]"],
        require_registered_columns=True,
    )},
}}}

OR_CHAIN_CONFIG = {"rules": {OR_CHAIN: {"max_or_chain": 60, "or_chain_measures": [GUARD]}}}
CONTRACT_CONFIG = {"rules": {CONTRACT: {"contracts": [{
    "kind": "must_not_divide", "model": GROWTH_E, "table": "#Backend Measures",
    "measures": "*Cost/*", "raw_measure": "Cost",
}]}}}
POLICY_CONFIG = {"rules": {POLICY: {
    "model": GROWTH_E,
    "helper": "-helper Lead Policy Filter Only",
    "guard": GUARD,
    "policy_column": "'_Attribution LM'[merch_custom_group_advanced]",
    "floor_min": 0.9,
    "floor_max_exclusive": 1.0,
}}}


def _run(stand_in, rule, config, mutation=None, path=None):
    root = stand_in(FLEET)
    if mutation:
        mutate(root, mutation)
    return run_check(root if path is None else root / path, rule, config=config)


def _model_findings(payload, cid, *needles):
    model = CLIENTS[cid]["model"].split("/")[0]
    return [v for v in mentioning(payload, *needles)
            if model in (v.get("path") or "") or model in (v.get("file") or "") or cid in v["message"]]


def _params(kind):
    return [pytest.param(cid, t, id=f"{cid}:{t}") for cid, cfg in CLIENTS.items() for t in cfg[kind]]


def _consumers(kind):
    return [pytest.param(cid, m, id=f"{cid}:{m}") for cid, cfg in CLIENTS.items() for m in cfg.get(kind, ())]


class TestGeneric:
    @pytest.mark.p0
    @pytest.mark.parametrize("cid,table", _params("blocked_tables"))
    def test_blocked_table_has_isfiltered(self, stand_in, cid, table):
        _code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG)
        assert not _model_findings(payload, cid, f"ISFILTERED('{table}')")
        assert not mentioning(payload, "not declared")

    @pytest.mark.p0
    @pytest.mark.parametrize("cid,table", _params("blocked_tables"))
    def test_blocked_table_covers_every_fieldparam_column(self, stand_in, cid, table):
        _code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG)
        if (cid, table) in UNREGISTERED:
            # no axis field parameter exposes a column of this table: skipped, never a finding
            assert not _model_findings(payload, cid, f"'{table}'[")
            pytest.skip(f"no y-Selector field parameter exposes a {table} column")
        assert not _model_findings(payload, cid, "ISINSCOPE", f"'{table}'[")

    @pytest.mark.p0
    @pytest.mark.parametrize("cid,table", _params("permitted_tables"))
    def test_conformed_column_block_is_member_conditional(self, stand_in, cid, table):
        _code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG)
        assert not _model_findings(payload, cid, "SELECTEDVALUE", f"'{table}'[")

    @pytest.mark.p0
    @pytest.mark.parametrize("cid,table", _params("permitted_tables"))
    def test_conformed_table_never_blocked_tablewide(self, stand_in, cid, table):
        _code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG)
        assert not _model_findings(payload, cid, f"ISFILTERED('{table}')")

    @pytest.mark.p0
    @pytest.mark.parametrize("cid", list(CLIENTS))
    def test_guard_or_chain_stays_shallow(self, stand_in, cid):
        code, payload = _run(stand_in, OR_CHAIN, OR_CHAIN_CONFIG, path=CLIENTS[cid]["model"])
        assert mentioning(payload) == []
        assert code == 0

    @pytest.mark.p0
    @pytest.mark.parametrize("cid,measure", _consumers("guarded_ratios"))
    def test_ratio_consults_the_grain_guard(self, stand_in, cid, measure):
        _code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG)
        assert not _model_findings(payload, cid, f"'{measure}'")
        assert not _model_findings(payload, cid, f"[{measure}]")

    @pytest.mark.p0
    @pytest.mark.parametrize("cid,measure", _consumers("guarded_counts"))
    def test_count_consults_the_reach_guard(self, stand_in, cid, measure):
        _code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG)
        assert not _model_findings(payload, cid, f"'{measure}'")
        assert not _model_findings(payload, cid, f"[{measure}]")

    def test_whole_generic_config_is_clean(self, stand_in):
        code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG)
        assert mentioning(payload) == []
        assert code == 0


class TestGenericNegativeControls:
    def test_blocked_table_covers_every_fieldparam_column(self, stand_in):
        code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG, "grain_drops_devices_column")
        assert code == 1
        found = mentioning(payload, "'_Devices'[device]")
        assert len(found) == 1

    def test_conformed_column_block_is_member_conditional(self, stand_in):
        code, payload = _run(stand_in, GRAIN, GENERIC_CONFIG, "grain_conformed_blocked")
        assert code == 1
        assert mentioning(payload, "'_Countries'[Country Official Name]")
        assert mentioning(payload, "_Countries")

    def test_guard_or_chain_stays_shallow(self, stand_in):
        code, payload = _run(stand_in, OR_CHAIN, OR_CHAIN_CONFIG, "or_chain_61", path=GROWTH_E)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1 and GUARD in found[0]["message"]


class TestOneModel:
    BLOCKED_TABLES = ("'_Attribution LM'", "'_Accounts'", "'_Campaigns'", "'_Devices'", "'_Landing Pages'")
    MUST_NOT_BLOCK = (
        "'_Countries'[Country Official Name]",
        "'_Report Attribution'[m_main_attribution]",
        "'_Report Attribution Resolved'[m_main_attribution_resolved]",
    )

    @pytest.mark.p0
    @pytest.mark.parametrize("table", BLOCKED_TABLES)
    def test_blocked_table_has_isfiltered(self, stand_in, table):
        _code, payload = _run(stand_in, GRAIN, ONE_MODEL_CONFIG)
        assert not mentioning(payload, f"ISFILTERED({table})")

    @pytest.mark.p0
    @pytest.mark.parametrize("table", BLOCKED_TABLES)
    def test_blocked_table_covers_every_fieldparam_column(self, stand_in, table):
        _code, payload = _run(stand_in, GRAIN, ONE_MODEL_CONFIG)
        # require_registered_columns: a blocked table with no axis column is a finding
        assert not mentioning(payload, f"{table}[")
        assert not mentioning(payload, table, "exposes")

    @pytest.mark.p0
    @pytest.mark.parametrize("grain", MUST_NOT_BLOCK)
    def test_conformed_grains_stay_permitted(self, stand_in, grain):
        _code, payload = _run(stand_in, GRAIN, ONE_MODEL_CONFIG)
        assert not mentioning(payload, grain)

    @pytest.mark.p0
    def test_no_cost_ratio_divides_raw_cost(self, stand_in):
        code, payload = _run(stand_in, CONTRACT, CONTRACT_CONFIG)
        assert mentioning(payload) == []
        assert code == 0

    @pytest.mark.p0
    def test_guard_or_chain_stays_shallow(self, stand_in):
        code, payload = _run(stand_in, OR_CHAIN, OR_CHAIN_CONFIG, path=GROWTH_E)
        assert mentioning(payload) == []
        assert code == 0

    @pytest.mark.p0
    def test_policy_exception_leaves_the_shared_guard_alone(self, stand_in):
        _code, payload = _run(stand_in, POLICY, POLICY_CONFIG)
        assert not mentioning(payload, GUARD, "Lead Policy Filter Only")

    @pytest.mark.p0
    def test_policy_exception_is_coverage_bounded(self, stand_in):
        _code, payload = _run(stand_in, POLICY, POLICY_CONFIG)
        assert not mentioning(payload, "coverageFloor")

    @pytest.mark.p0
    def test_policy_exception_never_admits_an_axis(self, stand_in):
        _code, payload = _run(stand_in, POLICY, POLICY_CONFIG)
        assert not mentioning(payload, "ISINSCOPE")

    @pytest.mark.p0
    def test_policy_exception_only_forgives_the_policy_filter(self, stand_in):
        code, payload = _run(stand_in, POLICY, POLICY_CONFIG)
        assert mentioning(payload) == []
        assert code == 0

    def test_whole_one_model_config_is_clean(self, stand_in):
        code, payload = _run(stand_in, GRAIN, ONE_MODEL_CONFIG)
        assert mentioning(payload) == []
        assert code == 0


class TestOneModelNegativeControls:
    def test_blocked_table_covers_every_fieldparam_column(self, stand_in):
        code, payload = _run(stand_in, GRAIN, ONE_MODEL_CONFIG, "grain_drops_devices_column")
        assert code == 1
        assert len(mentioning(payload, "'_Devices'[device]")) == 1

    def test_conformed_grains_stay_permitted(self, stand_in):
        code, payload = _run(stand_in, GRAIN, ONE_MODEL_CONFIG, "grain_conformed_blocked")
        assert code == 1
        assert mentioning(payload, "'_Countries'[Country Official Name]")

    def test_guard_or_chain_stays_shallow(self, stand_in):
        code, payload = _run(stand_in, OR_CHAIN, OR_CHAIN_CONFIG, "or_chain_61", path=GROWTH_E)
        assert code == 1 and len(violations(payload)) == 1

    def test_no_cost_ratio_divides_raw_cost(self, stand_in):
        code, payload = _run(stand_in, CONTRACT, CONTRACT_CONFIG, "ratio_divides_raw_cost")
        assert code == 1
        assert mentioning(payload, "Cost/ Merchant")

    def test_policy_exception_is_coverage_bounded(self, stand_in):
        code, payload = _run(stand_in, POLICY, POLICY_CONFIG, "policy_floor_085")
        assert code == 1
        assert len(mentioning(payload, "coverageFloor")) == 1

    def test_policy_exception_only_forgives_the_policy_filter(self, stand_in):
        code, payload = _run(stand_in, POLICY, POLICY_CONFIG, "policy_recheck_unused")
        assert code == 1
        assert len(violations(payload)) == 1

    def test_whitespace_inside_terms_is_free(self, stand_in):
        """BUGFIX (project decision): the one-model copy matched only `ISINSCOPE( 'T'[c] )`
        with single spaces; `ISINSCOPE ( 'T'[c] )` is the same DAX and passes."""
        root = stand_in(FLEET)
        guard_file = root / GROWTH_E / "definition" / "tables" / "#Backend Measures.tmdl"
        text = guard_file.read_text(encoding="utf-8")
        guard_file.write_text(text.replace("ISINSCOPE( '_Devices'[device] )",
                                           "ISINSCOPE ( '_Devices'[device] )"), encoding="utf-8")
        code, payload = run_check(root, GRAIN, config=ONE_MODEL_CONFIG)
        assert mentioning(payload) == []
        assert code == 0
