"""Live smoke checks on a published dataset: tables hold rows
(E-live-table-row-presence), measures evaluate (E-live-measure-not-blank),
latest refresh status (E-live-refresh-status), freshness
(E-live-data-freshness) and the aggregated suite (E-live-smoke-suite), plus the
static dimension-prefix floor N020.

Replay mode over ``tests/fixtures/live/<scenario>/``; the local model is the
fictional coffee roastery under ``tests/fixtures/live/models/``. A
non-blocking finding is outcome ``warn``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import FIXTURES, run_check, run_cli, violations, write_config

LIVE = FIXTURES / "live"
MODELS = LIVE / "models"


def live(scenario: str, *checks: str, model: str = "coffee", strict: bool = False,
         config: Path | None = None) -> tuple[int, dict]:
    argv = ["live", str(MODELS / model / "Coffee.SemanticModel"), "--workspace", "ws-coffee",
            "--dataset", "ds-coffee", "--replay", str(LIVE / scenario), "--json"]
    if checks:
        argv += ["--checks", ",".join(checks)]
    if strict:
        argv.append("--strict")
    if config is not None:
        argv += ["--config", str(config)]
    code, out, err = run_cli(*argv)
    return code, json.loads(out) if out.strip() else {"stderr": err}


def check_result(payload: dict, check_id: str) -> dict:
    found = [c for c in payload["checks"] if c["id"] == check_id]
    assert len(found) == 1, f"{check_id} missing from {payload}"
    return found[0]


# ---------------------------------------------------------------------------
# E-live-table-row-presence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario, outcome, probed, passed", [
    # _Beans 120, _Days 30, _Shops 8, Sales 5000 -> 4/4
    pytest.param("tables-populated", "pass", 4, 4, id="tables-populated"),
    # _Beans 0, _Shops 0, _Days 30, Sales BLANK -> 1/4 = 25% < 60%
    pytest.param("tables-mostly-empty", "fail", 4, 1, id="tables-mostly-empty"),
])
def test_sample_tables_have_data(scenario, outcome, probed, passed):
    code, payload = live(scenario, "live-table-sample")
    result = check_result(payload, "live-table-sample")
    assert result["outcome"] == outcome
    assert code == (1 if outcome == "fail" else 0)
    details = result["details"]
    assert details["probed"] == probed
    assert details["passed"] == passed
    # measure-only tables cannot be counted and are never queried
    assert "Coffee Measures" not in details["tables"]
    assert details["tables"] == ["Sales", "_Beans", "_Days", "_Shops"]


@pytest.mark.parametrize("scenario, model, outcome, empty", [
    pytest.param("tables-populated", "coffee", "pass", [], id="tables-populated"),
    # 2 of 3 dimension tables hold rows: 66.7% < 70%
    pytest.param("dims-one-empty", "coffee", "fail", ["_Days"], id="dims-one-empty"),
    pytest.param("tables-populated", "coffee-no-dims", "fail", None, id="no-dimension-tables"),
])
def test_dimension_tables_have_data(scenario, model, outcome, empty):
    code, payload = live(scenario, "live-dimension-rows", model=model)
    result = check_result(payload, "live-dimension-rows")
    assert result["outcome"] == outcome
    assert code == (1 if outcome == "fail" else 0)
    if empty is None:
        assert result["message"] == "No dimension tables found starting with '_'"
    else:
        assert result["details"]["empty_tables"] == empty


# ---------------------------------------------------------------------------
# E-live-measure-not-blank
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario, outcome", [
    # 1 value, 3 blank, 1 query error (counts as blank) -> 20% >= 20%
    pytest.param("measures-one-of-five", "pass", id="measures-one-of-five"),
    pytest.param("measures-all-blank", "fail", id="measures-all-blank"),
])
def test_sample_measures_not_blank(scenario, outcome):
    code, payload = live(scenario, "live-measure-sample")
    result = check_result(payload, "live-measure-sample")
    assert result["outcome"] == outcome
    assert code == (1 if outcome == "fail" else 0)
    assert result["details"]["probed"] == 5
    if outcome == "pass":
        assert result["details"]["passed"] == 1
        # below 50% a note is added
        assert result["details"].get("note")


def test_report_measures_not_blank(tmp_path):
    """Parameter tables normally hold no measures, so the parameter-table
    check is disabled by default."""
    code, payload = live("measures-one-of-five", "live-parameter-table-measures")
    assert check_result(payload, "live-parameter-table-measures")["outcome"] == "skip"
    assert code == 0

    cfg = write_config(tmp_path, {"live": {"parameter_table_measures": True}})
    code, payload = live("measures-one-of-five", "live-parameter-table-measures", config=cfg)
    result = check_result(payload, "live-parameter-table-measures")
    assert result["outcome"] == "fail"
    assert result["message"] == "No x-Selector measure tables found"
    assert code == 1


# ---------------------------------------------------------------------------
# E-live-smoke-suite (local half): N020 dimension-prefix-floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model, expected_count", [
    # a floor of 20 dimension tables: 3 warns
    pytest.param("coffee", 3, id="three-dimension-tables"),
    pytest.param("coffee-20-dims", 20, id="twenty-dimension-tables"),
])
def test_dimension_tables_naming_convention(tmp_path, model, expected_count):
    target = tmp_path / model
    shutil.copytree(MODELS / model, target)
    cfg = {"rules": {"N020": {"enabled": True, "min_dimension_tables": 20}}}
    code, payload = run_check(target, "N020", config=cfg, strict=True)
    found = violations(payload, "N020")
    if expected_count < 20:
        assert len(found) == 1
        assert found[0]["severity"] == "error"
        assert found[0]["message"] == (
            "Expected at least 20 dimension tables starting with '_', "
            f"found {expected_count}")
        assert code == 1
    else:
        assert len(found) == 1
        assert found[0]["severity"] == "info"
        assert found[0]["message"].split("\n")[0] == (
            "✅ Found 20 dimension tables starting with '_'")
        assert found[0]["message"].split("\n")[1] == "Sample dimension tables:"
        assert code == 0
    # disabled by default: no finding without the opt-in
    code, payload = run_check(target, "N020")
    assert violations(payload, "N020") == []


# ---------------------------------------------------------------------------
# E-live-refresh-status
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario, outcome, message", [
    pytest.param("refresh-completed", "pass", None, id="refresh-completed"),
    pytest.param("refresh-failed", "warn", "Failed", id="refresh-failed"),
    pytest.param("refresh-none", "warn", "No refresh history found", id="refresh-none"),
])
def test_refresh_status(scenario, outcome, message):
    code, payload = live(scenario, "live-refresh-status")
    result = check_result(payload, "live-refresh-status")
    assert result["outcome"] == outcome
    assert code == 0  # non-blocking by default
    if message:
        assert message in result["message"]
    else:
        assert result["details"]["end_time"] == "2026-10-17T05:00:00Z"
        assert result["details"]["request_id"] == "r1"
    if outcome == "warn":
        code, _ = live(scenario, "live-refresh-status", strict=True)
        assert code == 1


# ---------------------------------------------------------------------------
# E-live-data-freshness (replay clock: 2026-10-18T12:00:00Z)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario, outcome, age_hours, message", [
    pytest.param("fresh-10h", "pass", 10.0, None, id="fresh-10h"),
    # the newest record is still running; the newest Completed one is exactly 24 h old
    pytest.param("fresh-24h-behind-running", "pass", 24.0, None, id="fresh-24h-behind-running"),
    pytest.param("stale-48h", "warn", 48.0, "48", id="stale-48h"),
    pytest.param("only-failed", "warn", None, "No successful refresh found in history",
                 id="only-failed"),
])
def test_data_freshness(scenario, outcome, age_hours, message):
    code, payload = live(scenario, "live-freshness")
    result = check_result(payload, "live-freshness")
    assert result["outcome"] == outcome
    assert code == 0
    if age_hours is not None:
        assert result["details"]["age_hours"] == pytest.approx(age_hours)
    if message:
        assert message in result["message"]


# ---------------------------------------------------------------------------
# E-live-smoke-suite
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario, outcome, passed, total", [
    # 3 dimension tables + 4/5 measures + refresh + freshness -> 9/10
    pytest.param("smoke-healthy", "pass", 9, 10, id="smoke-healthy"),
    # refresh Failed (and so no completed refresh) + 3 blank measures -> 5/10
    pytest.param("smoke-degraded", "fail", 5, 10, id="smoke-degraded"),
])
def test_comprehensive_smoke_test_suite(scenario, outcome, passed, total):
    code, payload = live(scenario, "live-smoke")
    result = check_result(payload, "live-smoke")
    assert result["outcome"] == outcome
    assert code == (1 if outcome == "fail" else 0)
    details = result["details"]
    assert details["passed"] == passed
    assert details["total"] == total
    assert len(details["failed_items"]) == total - passed
    assert "elapsed_ms" in details
