"""The live command's report blocks: every check prints its block before the
result line (PB147), and the blocks of the row-limit, calendar, dimension and
parameter checks (PB148-PB151).

Replay mode over ``tests/fixtures/live/<scenario>/``; no network.
"""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURES, run_cli

LIVE = FIXTURES / "live"
MODEL = LIVE / "models" / "coffee" / "Coffee.SemanticModel"
INDENTED = LIVE / "models" / "coffee-indented" / "Coffee.SemanticModel"


def live(scenario: str, *checks: str, model=None) -> tuple[int, dict]:
    model = model or MODEL
    argv = ["live", str(model), "--workspace", "ws-coffee", "--dataset", "ds-coffee",
            "--replay", str(LIVE / scenario), "--json"]
    if checks:
        argv += ["--checks", ",".join(checks)]
    code, out, err = run_cli(*argv)
    return code, json.loads(out) if out.strip() else {"stderr": err}


def live_text(scenario: str, *checks: str, model=None) -> tuple[int, str]:
    model = model or MODEL
    argv = ["live", str(model), "--workspace", "ws-coffee", "--dataset", "ds-coffee",
            "--replay", str(LIVE / scenario)]
    if checks:
        argv += ["--checks", ",".join(checks)]
    code, out, _err = run_cli(*argv)
    return code, out


def check_result(payload: dict, check_id: str) -> dict:
    found = [c for c in payload["checks"] if c["id"] == check_id]
    assert len(found) == 1, f"{check_id} missing from {payload}"
    return found[0]


# ---------------------------------------------------------------------------
# PB147: the block comes before the result line, in the original order
# ---------------------------------------------------------------------------

def test_the_default_check_order():
    from tmdl_preflight import live

    assert list(live.CHECKS) == [
        "live-uniform-row-limit", "live-calendar-rows", "live-dimension-multirow",
        "live-calendar-vs-parameters", "live-parameter-audit", "live-table-sample",
        "live-dimension-rows", "live-measure-sample", "live-parameter-table-measures",
        "live-refresh-status", "live-freshness", "live-smoke", "live-identity",
        "live-filter-compare", "live-calendar-scan", "live-metadata",
        "live-filter-diagnostic", "live-bpa"]


def test_the_block_comes_before_the_result_line():
    code, out = live_text("calendar-rows-200", "live-calendar-rows")
    assert code == 0
    assert out.splitlines() == [
        "dataset: Coffee (workspace Coffee Roastery)",
        "",
        "=== Calendar Table Validation ===",
        "",
        "  Row count: 200",
        "  Min date: 2024-01-01T00:00:00",
        "  Max date: 2025-12-30T00:00:00",
        "  ⚠️  Calendar has 200 rows (less than 1 year)",
        "     This may indicate date filtering or limited data range",
        "pass   live-calendar-rows: 200 calendar rows",
    ]


def test_the_blocks_come_in_the_order_the_checks_run():
    code, out = live_text("calendar-rows-730", "live-calendar-rows", "live-uniform-row-limit")
    assert code == 0
    assert out.index("=== Calendar Table Validation ===") < \
        out.index("=== Row Count Pattern Detection ===")


# ---------------------------------------------------------------------------
# PB148: the row-count pattern block
# ---------------------------------------------------------------------------

def test_the_row_count_block():
    code, out = live_text("uniform-varied", "live-uniform-row-limit")
    assert code == 0
    assert out.splitlines()[1:] == [
        "",
        "=== Row Count Pattern Detection ===",
        "",
        "  __Calendar: 365 rows",
        "  _Accounts: 1 rows",
        "  _Campaigns: 12 rows",
        "  _Conversions: 4 rows",
        "  _Devices: 40 rows",
        "",
        "📊 Analysis:",
        "  Unique row counts: [1, 4, 12, 40, 365]",
        "  ✅ Row counts vary (1 to 365) - no uniform limit detected",
        "pass   live-uniform-row-limit: row counts vary (1 to 365)",
    ]


def test_an_empty_result_set_reads_as_unknown():
    code, payload = live("uniform-one-empty", "live-uniform-row-limit")
    result = check_result(payload, "live-uniform-row-limit")
    assert result["outcome"] == "fail"
    assert "All 4 tables have exactly 1 row" in result["message"]
    assert code == 1


def test_the_uniform_limit_warning():
    code, payload = live("uniform-all-1000", "live-uniform-row-limit")
    result = check_result(payload, "live-uniform-row-limit")
    assert result["outcome"] == "warn"
    assert result["message"] == (
        "⚠️  WARNING: All tables have exactly 1000 rows. This suggests "
        "v-rows_limit='LIMIT 1000' is set. This is acceptable for testing but not production.")


def test_no_count_at_all_stops_the_block():
    code, out = live_text("uniform-all-error", "live-uniform-row-limit")
    assert "📊 Analysis:" not in out
    assert "  __Calendar: ERROR - Table '__Calendar' cannot be queried" in out
    code, payload = live("uniform-all-error", "live-uniform-row-limit")
    assert check_result(payload, "live-uniform-row-limit")["message"] == \
        "Could not retrieve any row counts"


# ---------------------------------------------------------------------------
# PB149: the calendar block
# ---------------------------------------------------------------------------

def test_the_calendar_block_for_a_healthy_calendar():
    code, out = live_text("calendar-rows-730", "live-calendar-rows")
    assert code == 0
    assert "  ✅ Calendar has realistic row count" in out


def test_the_calendar_fail_text():
    code, payload = live("calendar-rows-1", "live-calendar-rows")
    result = check_result(payload, "live-calendar-rows")
    assert result["outcome"] == "fail"
    assert result["message"] == (
        "🔴 CRITICAL: Calendar has only 1 row (expected 365+). This indicates "
        "v-rows_limit='LIMIT 1' is set. Change to ' ' (blank) for full data.")
    assert code == 1


def test_the_calendar_warn_text():
    code, payload = live("calendar-rows-50", "live-calendar-rows")
    result = check_result(payload, "live-calendar-rows")
    assert result["outcome"] == "warn"
    assert result["message"] == (
        "⚠️  WARNING: Calendar has only 50 rows (expected 365+). Check v-rows_limit and "
        "v-fromdate parameters.")


# ---------------------------------------------------------------------------
# PB150: the dimension block
# ---------------------------------------------------------------------------

def test_the_dimension_block():
    code, out = live_text("dims-varied", "live-dimension-multirow")
    assert code == 0
    assert out.splitlines()[1:9] == [
        "",
        "=== Dimension Table Validation ===",
        "",
        "  🔴 _Accounts: 1 rows",
        "  🔴 _Campaigns: 1 rows",
        "  ✅ _Conversions: 7 rows",
        "  ✅ _Devices: 9 rows",
        "  ✅ _Countries: 3 rows",
    ]


def test_the_dimension_warn_text():
    code, payload = live("dims-mostly-one", "live-dimension-multirow")
    result = check_result(payload, "live-dimension-multirow")
    assert result["outcome"] == "warn"
    assert result["message"] == (
        "⚠️  WARNING: 4/5 dimension tables have only 1 row. Check v-rows_limit parameter. "
        "Single-row tables: ['_Accounts', '_Campaigns', '_Conversions', '_Countries']")


def test_the_dimension_fail_text():
    code, payload = live("dims-all-one", "live-dimension-multirow")
    result = check_result(payload, "live-dimension-multirow")
    assert result["outcome"] == "fail"
    assert result["message"] == (
        "🔴 CRITICAL: All dimension tables have ≤1 row. This indicates v-rows_limit='LIMIT 1' "
        "or empty source data. Results: {'_Accounts': 1, '_Campaigns': 1, '_Conversions': 1, "
        "'_Devices': 1, '_Countries': 1}")
    assert code == 1


# ---------------------------------------------------------------------------
# PB151: the date-range block and the parameter reading
# ---------------------------------------------------------------------------

def test_the_date_range_block():
    code, out = live_text("params-calendar-730", "live-calendar-vs-parameters")
    assert code == 0
    assert out.splitlines()[1:] == [
        "",
        "=== Date Range Validation ===",
        "",
        "  Parameter Configuration:",
        "    v-fromdate: 2024-01-01",
        "    v-isRolling: 0",
        "    v-daysAgo: 90",
        "",
        "  Actual Data:",
        "    Min date: 2024-01-01T00:00:00",
        "    Max date: 2025-12-30T00:00:00",
        "    Row count: 730",
        "",
        "  ✅ Date range retrieved (validation informational)",
        "pass   live-calendar-vs-parameters: calendar 2024-01-01T00:00:00 to "
        "2025-12-30T00:00:00 (730 rows)",
    ]


def test_an_indented_expression_is_read():
    code, payload = live("params-calendar-730", "live-calendar-vs-parameters", model=INDENTED)
    details = check_result(payload, "live-calendar-vs-parameters")["details"]
    assert details["v-daysAgo"] == "30"


def test_the_date_range_warn_text():
    code, payload = live("params-calendar-1", "live-calendar-vs-parameters")
    result = check_result(payload, "live-calendar-vs-parameters")
    assert result["outcome"] == "warn"
    assert result["message"] == (
        "Only 1 row in calendar - cannot validate date range (LIMIT 1 applied)")


def test_the_date_range_skip_text(tmp_path):
    import shutil

    model = tmp_path / "Coffee.SemanticModel"
    shutil.copytree(MODEL, model)
    (model / "definition" / "expressions.tmdl").unlink()
    code, payload = live("params-calendar-730", "live-calendar-vs-parameters", model=model)
    result = check_result(payload, "live-calendar-vs-parameters")
    assert result["outcome"] == "skip"
    assert result["message"] == \
        f"expressions.tmdl not found under {model / 'definition'}"
