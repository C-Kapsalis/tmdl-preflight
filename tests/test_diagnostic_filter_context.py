"""Live diagnostics for "every table shows one row": identity, filter-context
comparison, metadata (E-live-filter-context-diagnostics) and the calendar full
scan (E-live-row-limit-detection). Replay mode, no network."""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURES, run_cli

LIVE = FIXTURES / "live"
MODEL = LIVE / "models" / "coffee" / "Coffee.SemanticModel"


def live(scenario: str, *checks: str) -> tuple[int, dict]:
    argv = ["live", str(MODEL), "--workspace", "ws-coffee", "--dataset", "ds-coffee",
            "--replay", str(LIVE / scenario), "--json", "--checks", ",".join(checks)]
    code, out, err = run_cli(*argv)
    return code, json.loads(out) if out.strip() else {"stderr": err}


def check_result(payload: dict, check_id: str) -> dict:
    found = [c for c in payload["checks"] if c["id"] == check_id]
    assert len(found) == 1, f"{check_id} missing from {payload}"
    return found[0]


@pytest.mark.parametrize("scenario", [pytest.param("filter-compare", id="filter-compare")])
def test_check_rls_roles_applied(scenario):
    code, payload = live(scenario, "live-identity")
    result = check_result(payload, "live-identity")
    assert result["outcome"] == "pass"
    assert code == 0
    details = result["details"]
    assert details["user_principal_name"] == "reader@example.com"
    assert details["dataset_name"] == "Coffee"


@pytest.mark.parametrize("scenario", [pytest.param("filter-compare", id="filter-compare")])
def test_compare_countrows_vs_actual_evaluate(scenario):
    code, payload = live(scenario, "live-filter-compare")
    result = check_result(payload, "live-filter-compare")
    assert result["outcome"] == "pass"  # informational
    assert code == 0
    # _Accounts: plain COUNTROWS 1 vs ALL() 40 -> filter context or RLS
    assert result["details"]["flagged"] == ["_Accounts"]
    rows = {r["table"]: r for r in result["details"]["tables"]}
    assert rows["_Accounts"]["countrows"] == 1
    assert rows["_Accounts"]["countrows_all"] == 40
    assert rows["_Accounts"]["topn_actual"] == 1
    assert set(rows) == {"_Accounts", "_Campaigns", "_Conversions", "__Calendar", "Ads"}


@pytest.mark.parametrize("scenario, outcome", [
    pytest.param("calendar-scan-1", "fail", id="calendar-scan-1"),
    pytest.param("calendar-scan-60", "pass", id="calendar-scan-60"),
    pytest.param("calendar-scan-730", "pass", id="calendar-scan-730"),
])
def test_query_large_table_full_scan(scenario, outcome):
    code, payload = live(scenario, "live-calendar-scan")
    result = check_result(payload, "live-calendar-scan")
    assert result["outcome"] == outcome
    assert code == (1 if outcome == "fail" else 0)
    details = result["details"]
    expected_rows = {"calendar-scan-1": 1, "calendar-scan-60": 50, "calendar-scan-730": 50}[scenario]
    assert details["returned_rows"] == expected_rows
    assert len(details["sample_values"]) == min(5, expected_rows)
    if outcome == "fail":
        assert "365" in result["message"]


@pytest.mark.parametrize("scenario", [pytest.param("filter-compare", id="filter-compare")])
def test_connection_metadata_investigation(scenario):
    code, payload = live(scenario, "live-metadata")
    result = check_result(payload, "live-metadata")
    assert result["outcome"] == "pass"
    assert code == 0
    details = result["details"]
    assert details["dataset"]["name"] == "Coffee"
    assert details["refreshes"][0]["status"] == "Completed"
    assert len(details["datasources"]) == 1


@pytest.mark.parametrize("scenario, outcome, levels", [
    pytest.param("diag-calendar-one", "fail", {"CRITICAL": 1}, id="diag-calendar-one"),
    # calendar 50 -> WARNING; _Accounts 3 vs 3 -> OK; refresh Completed -> OK
    pytest.param("diag-calendar-50", "pass", {"WARNING": 1}, id="diag-calendar-50"),
    # a failing calendar query is an ERROR finding, not a failure
    pytest.param("diag-calendar-error", "pass", {"ERROR": 1}, id="diag-calendar-error"),
])
def test_comprehensive_filter_diagnostic_report(scenario, outcome, levels):
    code, payload = live(scenario, "live-filter-diagnostic")
    result = check_result(payload, "live-filter-diagnostic")
    assert result["outcome"] == outcome
    assert code == (1 if outcome == "fail" else 0)
    findings = result["details"]["findings"]
    counted = {}
    for f in findings:
        if f["level"] in ("CRITICAL", "WARNING", "ERROR"):
            counted[f["level"]] = counted.get(f["level"], 0) + 1
    assert counted == levels
