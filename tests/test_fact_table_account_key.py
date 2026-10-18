"""Every fact table actively joins the conformed account dimension
(spec A-fact-conformed-dimension-join).

A fact is account-filterable iff an ACTIVE relationship runs from it to
``_Accounts[account_x_id]``; the from-column name is irrelevant (a fact may
join through ``service_account_x_id``). A fact without that join cannot be
filtered by account at all: the account filter has nothing to propagate
through and the visual silently shows unfiltered data.

Flagged facts are classified: the fact carries ``account_x_id`` but no active
join ("missing relationship") or carries neither ("missing key column").
Declared exemptions (with a mandatory reason) pass.

Ratchet (same shape as the original floor file,
``{"<folder>/<Model>": [table, ...]}``): recorded offenders do not fail, new
ones do, a model with no entry at all fails ("record it deliberately"), fixed
offenders print a tighten hint.

Stand-in (tests/fixtures/b3-a2/fact_table_account_key/roastery, model
``ak_db/Roastery``): Campaigns joins actively through service_account_x_id
(pass), Ads has account_x_id but an inactive relationship (missing
relationship), Sitemap has neither (missing key column), Transactions is
exempt.
"""
from __future__ import annotations

import json

import pytest

from conftest import run_check, violations

RULE = "fact-conformed-dimension-join"
MODEL = "ak_db/Roastery"

OPTIONS = {
    "dimension_table": "_Accounts",
    "key_column": "account_x_id",
    "exempt": {"Transactions": "Client-database transaction fact, loaded outside the "
                               "account-scoped ingestion, so no account key exists upstream."},
    "fail_without_baseline_entry": True,
}

FLOORS = [
    pytest.param({}, "fail", ["Ads", "Sitemap"], id="no-floor-entry"),
    pytest.param({MODEL: ["Ads", "Sitemap"]}, "pass", [], id="full-floor"),
    pytest.param({MODEL: ["Ads"]}, "fail", ["Sitemap"], id="partial-floor"),
]


@pytest.mark.parametrize("floor,verdict,new", FLOORS)
def test_fact_tables_have_account_key(stand_in, tmp_path, floor, verdict, new):
    root = stand_in("b3-a2/fact_table_account_key/roastery")
    base = tmp_path / "account_key_floors.json"
    base.write_text(json.dumps(floor, indent=1) + "\n", encoding="utf-8")
    cfg = {"rules": {RULE: dict(OPTIONS, baseline=str(base))}}
    code, payload = run_check(root, RULE, config=cfg)
    found = violations(payload)
    assert (code == 0) == (verdict == "pass"), payload
    if not floor:
        # the model has no recorded entry: fails as "record it deliberately"
        assert any("baseline" in v["message"].lower() or "record" in v["message"].lower()
                   for v in found)
        return
    assert sorted(v["object"] for v in found) == sorted(new)
    for v in found:
        if v["object"] == "Sitemap":
            assert "missing key column" in v["message"]
        if v["object"] == "Ads":
            assert "missing relationship" in v["message"]
    for passing in ("Campaigns", "Transactions"):
        assert not any(v["object"] == passing for v in found)


def test_unratcheted_run_classifies_offenders(stand_in):
    """Without a baseline every flagged fact is reported with its class."""
    root = stand_in("b3-a2/fact_table_account_key/roastery")
    opts = {k: v for k, v in OPTIONS.items() if k != "fail_without_baseline_entry"}
    code, payload = run_check(root, RULE, config={"rules": {RULE: opts}})
    found = {v["object"]: v["message"] for v in violations(payload)}
    assert code == 1
    assert set(found) == {"Ads", "Sitemap"}
    assert "missing relationship" in found["Ads"]
    assert "missing key column" in found["Sitemap"]
