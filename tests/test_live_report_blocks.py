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


# ---------------------------------------------------------------------------
# PB152: the connection parameter audit
# ---------------------------------------------------------------------------

def _set_param(model, old: str, new: str) -> None:
    f = model / "definition" / "expressions.tmdl"
    text = f.read_text(encoding="utf-8")
    assert text.count(old) == 1
    f.write_text(text.replace(old, new), encoding="utf-8")


def test_the_parameter_audit_report(tmp_path):
    import shutil

    model = tmp_path / "Coffee.SemanticModel"
    shutil.copytree(MODEL, model)
    code, out = live_text("params-calendar-730", "live-parameter-audit", model=model)
    assert code == 0
    lines = out.splitlines()
    assert lines[1:12] == [
        "",
        "=" * 80,
        "CONNECTION PARAMETER AUDIT REPORT",
        "=" * 80,
        "",
        "1. PARAMETER CONFIGURATION",
        "-" * 80,
        "",
        "  Time/Data Filters:",
        "    v-daysAgo: 90",
        "    v-fromdate: #date(2024, 1, 1)",
    ]
    assert "  ✅ No critical issues detected" in lines
    assert "3. LIVE DATA VALIDATION" in lines
    assert "    __Calendar: 730 rows" in lines
    assert "    _Accounts: 40 rows" in lines
    assert "✅ Audit report generated successfully" in lines
    assert lines[-1] == "pass   live-parameter-audit: 0 parameter issue(s)"


def test_a_warning_is_numbered_and_the_critical_issue_follows_it(tmp_path):
    import shutil

    model = tmp_path / "Coffee.SemanticModel"
    shutil.copytree(MODEL, model)
    _set_param(model, 'v-rows_limit = " "', 'v-rows_limit = "LIMIT 500"')
    _set_param(model, "#date(2024, 1, 1)", "#date(2027, 10, 18)")
    code, out = live_text("params-calendar-730", "live-parameter-audit", model=model)
    assert code == 0
    assert "    ⚠️  WARNING: v-rows_limit" in out
    assert "       Issue: Row limit applied - data incomplete" in out
    assert "       Recommendation: Review limit value for environment" in out
    assert "    🔴 CRITICAL: v-fromdate" in out
    assert "       Issue: Future date (365 days ahead) - no historical data" in out
    # the critical issue is the second one, so it is numbered 2
    assert "    2. Change to past date (e.g., 2023-01-01)" in out
    assert "    1. Change to ' ' (blank) for production" not in out


def test_only_limit_one_is_critical(tmp_path):
    import shutil

    for value, severity in (("LIMIT 1", "CRITICAL"), ("LIMIT 10", "WARNING"),
                             ("LIMIT 100", "WARNING"), ("LIMIT  1", "WARNING")):
        model = tmp_path / value.replace(" ", "_") / "Coffee.SemanticModel"
        shutil.copytree(MODEL, model)
        _set_param(model, 'v-rows_limit = " "', f'v-rows_limit = "{value}"')
        code, payload = live("params-calendar-730", "live-parameter-audit", model=model)
        issues = check_result(payload, "live-parameter-audit")["details"]["issues"]
        assert [i["severity"] for i in issues] == [severity], value


def test_the_audit_never_fails_the_run(tmp_path):
    import shutil

    model = tmp_path / "Coffee.SemanticModel"
    shutil.copytree(MODEL, model)
    _set_param(model, 'v-rows_limit = " "', 'v-rows_limit = "LIMIT 1"')
    code, payload = live("params-calendar-730", "live-parameter-audit", model=model)
    assert code == 0
    assert check_result(payload, "live-parameter-audit")["outcome"] == "pass"


# ---------------------------------------------------------------------------
# PB153: the table sample
# ---------------------------------------------------------------------------

def test_the_table_sample_lines():
    code, out = live_text("tables-mostly-empty", "live-table-sample")
    assert code == 1
    lines = [line for line in out.splitlines() if line.startswith("  ")]
    assert len(lines) == 4
    assert lines[0].startswith("  ❌ FAIL Table 'Sales' has data: Table 'Sales' is empty (0 rows) (")
    assert lines[1].startswith("  ❌ FAIL Table '_Beans' has data: Table '_Beans' is empty (0 rows) (")
    assert lines[2].startswith("  ✅ PASS Table '_Days' has data: Table '_Days' has 30 rows (")
    assert out.splitlines()[-1] == \
        "fail   live-table-sample: Only 1/4 tables have data (25.0%). Expected at least 60%."


# ---------------------------------------------------------------------------
# PB154: the dimension rows
# ---------------------------------------------------------------------------

def test_the_dimension_rows_lines():
    code, out = live_text("dims-one-empty", "live-dimension-rows")
    assert code == 1
    assert "  ❌ FAIL Table '_Days' has data: Table '_Days' is empty (0 rows) (" in out
    assert "  ✅ PASS Table '_Beans'" not in out
    assert "⚠️  Warning: 1 dimension tables are empty: ['_Days']" in out
    assert out.splitlines()[-1] == (
        "fail   live-dimension-rows: Only 2/3 dimension tables have data (66.7%). "
        "Failed tables: ['_Days']")


def test_no_dimension_table_is_a_failure():
    code, payload = live("tables-populated", "live-dimension-rows",
                         model=LIVE / "models" / "coffee-no-dims" / "Coffee.SemanticModel")
    result = check_result(payload, "live-dimension-rows")
    assert result["outcome"] == "fail"
    assert result["message"] == "No dimension tables found starting with '_'"
    assert code == 1


# ---------------------------------------------------------------------------
# PB155: the measure sample
# ---------------------------------------------------------------------------

def test_a_falsy_is_blank_means_the_measure_returned_a_value():
    code, payload = live("measures-isblank-zero", "live-measure-sample")
    result = check_result(payload, "live-measure-sample")
    assert result["outcome"] == "pass"
    assert result["details"]["passed"] == 1
    assert result["details"]["values"]["!Cups Sold"] == 42


def test_the_measure_sample_lines():
    code, out = live_text("measures-all-blank", "live-measure-sample")
    assert code == 1
    assert "  ❌ FAIL Measure '[!Revenue]' not blank: Measure '[!Revenue]' returned BLANK (" in out
    assert "⚠️  Warning: Only 0.0% of measures returned non-blank values" in out
    assert out.splitlines()[-1] == (
        "fail   live-measure-sample: Only 0/5 measures returned non-blank (0.0%). "
        "Expected at least 20%.")


# ---------------------------------------------------------------------------
# PB156: the parameter-table measures
# ---------------------------------------------------------------------------

def test_the_parameter_table_measures_are_skipped():
    code, payload = live("measures-one-of-five", "live-parameter-table-measures")
    result = check_result(payload, "live-parameter-table-measures")
    assert result["outcome"] == "skip"
    assert result["message"] == ("Report tables are parameter tables, not measure tables. "
                                 "Skipping for now.")
    assert code == 0


def test_no_parameter_table_measure_table(tmp_path):
    from conftest import write_config

    cfg = write_config(tmp_path, {"live": {"parameter_table_measures": True}})
    code, out, err = run_cli("live", str(MODEL), "--workspace", "ws-coffee", "--dataset",
                             "ds-coffee", "--replay", str(LIVE / "measures-one-of-five"),
                             "--checks", "live-parameter-table-measures", "--config", str(cfg))
    assert code == 1
    assert "No x-Selector measure tables found" in out


# ---------------------------------------------------------------------------
# PB157: the refresh status
# ---------------------------------------------------------------------------

def test_the_refresh_status_lines():
    code, out = live_text("refresh-failed", "live-refresh-status")
    assert code == 0
    lines = out.splitlines()
    assert lines[1].startswith("  ❌ FAIL Latest refresh status: Latest refresh status: Failed (")
    assert lines[2] == ""
    assert lines[3] == "⚠️  WARNING: Latest refresh status: Failed"
    assert lines[4] == ("    Details: {'status': 'Failed', 'end_time': '2026-10-17T05:00:00Z', "
                        "'request_id': 'r2'}")
    assert lines[5] == ("warn   live-refresh-status: Refresh status check failed "
                        "(non-blocking): Latest refresh status: Failed")


def test_the_refresh_status_pass_line():
    code, out = live_text("refresh-completed", "live-refresh-status")
    assert code == 0
    assert out.splitlines()[1].startswith(
        "  ✅ PASS Latest refresh status: Latest refresh completed successfully at "
        "2026-10-17T05:00:00Z (")


def test_no_refresh_history():
    code, out = live_text("refresh-none", "live-refresh-status")
    assert "    Details: {'refresh_count': 0}" in out


# ---------------------------------------------------------------------------
# PB158: the data freshness
# ---------------------------------------------------------------------------

def test_the_freshness_lines():
    code, out = live_text("stale-48h", "live-freshness")
    assert code == 0
    lines = out.splitlines()
    assert lines[1].startswith("  ❌ FAIL Data freshness (max 24h): Data is 48.0 hours old "
                               "(exceeds 24h threshold) (")
    assert lines[3] == "⚠️  WARNING: Data is 48.0 hours old (exceeds 24h threshold)"
    assert lines[4].startswith("    Details: {'end_time': '2026-10-16T12:00:00Z', 'age_hours': 48.0")
    assert lines[5] == ("warn   live-freshness: Data freshness check failed (non-blocking): "
                        "Data is 48.0 hours old (exceeds 24h threshold)")


def test_the_freshness_pass_line():
    code, out = live_text("fresh-10h", "live-freshness")
    assert code == 0
    assert out.splitlines()[1].startswith(
        "  ✅ PASS Data freshness (max 24h): Data refreshed 10.0 hours ago (within 24h threshold) (")


# ---------------------------------------------------------------------------
# PB159: the smoke suite
# ---------------------------------------------------------------------------

def test_the_smoke_report():
    code, out = live_text("smoke-degraded", "live-smoke")
    assert code == 1
    lines = out.splitlines()
    assert lines[1:11] == [
        "",
        "=" * 80,
        "COMPREHENSIVE SMOKE TEST SUITE",
        "=" * 80,
        "",
        "-" * 80,
        "SUMMARY",
        "-" * 80,
        "Total tests: 10",
        "Passed: 5 (50.0%)",
    ]
    assert lines[11] == "Failed: 5"
    assert lines[12] == ""
    assert lines[13] == "Failed tests:"
    failed = [line for line in lines if line.startswith("  ❌ ")]
    assert len(failed) == 5
    assert lines[-4].startswith("Total execution time: ")
    assert lines[-4].endswith("ms (0.00s)")
    assert lines[-3] == "=" * 80
    assert lines[-2] == ""
    assert "fail   live-smoke: Smoke test suite failed. Pass rate: 50.0% (expected >= 80%). " \
           "5 tests failed." in out


def test_the_smoke_suite_passes_when_enough_passes():
    code, out = live_text("smoke-healthy", "live-smoke")
    assert code == 0
    # one item fails, but the suite passes on the rate
    assert "Failed tests:" in out
    assert "pass   live-smoke: 9 of 10 smoke items passed" in out
