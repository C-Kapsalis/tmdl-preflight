"""Live checks that explain truncated or empty published datasets: the
row-limit shape checks (E-live-row-limit-detection) and the import-parameter
audit (E-live-parameter-audit).

Every test runs ``tmdl-preflight live`` in replay mode over a recorded-response
folder under ``tests/fixtures/live/`` (no network). A non-blocking
finding is outcome ``warn``, a blocking one ``fail``; a missing input file is
``skip``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import FIXTURES, run_cli

LIVE = FIXTURES / "live"


def live(scenario: str, *checks: str, model: Path | None = None, strict: bool = False,
         args: tuple = ()) -> tuple[int, dict]:
    model = model or LIVE / "models" / "coffee" / "Coffee.SemanticModel"
    argv = ["live", str(model), "--workspace", "ws-coffee", "--dataset", "ds-coffee",
            "--replay", str(LIVE / scenario), "--json"]
    if checks:
        argv += ["--checks", ",".join(checks)]
    if strict:
        argv.append("--strict")
    code, out, err = run_cli(*argv, *args)
    return code, json.loads(out) if out.strip() else {"stderr": err}


def check_result(payload: dict, check_id: str) -> dict:
    found = [c for c in payload["checks"] if c["id"] == check_id]
    assert len(found) == 1, f"{check_id} missing from {payload}"
    return found[0]


def coffee_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "coffee" / "Coffee.SemanticModel"
    shutil.copytree(LIVE / "models" / "coffee" / "Coffee.SemanticModel", dest)
    return dest


EXIT = {"fail": 1, "error": 1, "warn": 0, "pass": 0, "skip": 0}


# ---------------------------------------------------------------------------
# E-live-row-limit-detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario, outcome, message", [
    # fail: every table has exactly one row
    pytest.param("uniform-all-one", "fail", "exactly one row", id="uniform-all-one"),
    # warn: uniform 1000-row limit, acceptable for testing
    pytest.param("uniform-all-1000", "warn", "1000", id="uniform-all-1000"),
    # pass: counts vary
    pytest.param("uniform-varied", "pass", None, id="uniform-varied"),
    # warn: no count could be read
    pytest.param("uniform-all-error", "warn", "could not retrieve any row counts", id="uniform-all-error"),
])
def test_detect_uniform_row_limit_pattern(scenario, outcome, message):
    code, payload = live(scenario, "live-uniform-row-limit")
    result = check_result(payload, "live-uniform-row-limit")
    assert result["outcome"] == outcome
    assert code == EXIT[outcome]
    if message:
        assert message in result["message"]
    if outcome == "pass":
        assert result["details"]["min"] == 1
        assert result["details"]["max"] == 365


@pytest.mark.parametrize("scenario, outcome, note", [
    pytest.param("calendar-rows-1", "fail", None, id="calendar-rows-1"),
    pytest.param("calendar-rows-50", "warn", None, id="calendar-rows-50"),
    pytest.param("calendar-rows-200", "pass", "less than one year", id="calendar-rows-200"),
    pytest.param("calendar-rows-730", "pass", None, id="calendar-rows-730"),
])
def test_calendar_table_row_count_realistic(scenario, outcome, note):
    code, payload = live(scenario, "live-calendar-rows")
    result = check_result(payload, "live-calendar-rows")
    assert result["outcome"] == outcome
    assert code == EXIT[outcome]
    if note:
        assert note in result["message"]
    else:
        assert "less than one year" not in result["message"]


@pytest.mark.parametrize("scenario, outcome, single_row", [
    pytest.param("dims-all-one", "fail", None, id="dims-all-one"),
    # 4 of 5 probed tables hold one row: 4 > 5 // 2 -> warn listing them
    pytest.param("dims-mostly-one", "warn",
                 ["_Accounts", "_Campaigns", "_Conversions", "_Countries"], id="dims-mostly-one"),
    # 2 single-row tables: 2 > 2 is false -> pass
    pytest.param("dims-varied", "pass", None, id="dims-varied"),
    # every probe failed: no known count above 1 -> fail
    pytest.param("dims-all-error", "fail", None, id="dims-all-error"),
])
def test_dimension_tables_have_multiple_rows(scenario, outcome, single_row):
    code, payload = live(scenario, "live-dimension-multirow")
    result = check_result(payload, "live-dimension-multirow")
    assert result["outcome"] == outcome
    assert code == EXIT[outcome]
    if single_row:
        assert sorted(result["details"]["single_row_tables"]) == single_row


# ---------------------------------------------------------------------------
# E-live-parameter-audit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario, drop_expressions, outcome", [
    pytest.param("params-calendar-730", False, "pass", id="params-calendar-730"),
    # one calendar row: the range cannot be validated (warn)
    pytest.param("params-calendar-1", False, "warn", id="params-calendar-1"),
    # no expressions.tmdl: the check does not apply (skip)
    pytest.param("params-calendar-730", True, "skip", id="no-expressions"),
])
def test_calendar_date_range_vs_parameters(tmp_path, scenario, drop_expressions, outcome):
    model = coffee_copy(tmp_path)
    if drop_expressions:
        (model / "definition" / "expressions.tmdl").unlink()
    code, payload = live(scenario, "live-calendar-vs-parameters", model=model)
    result = check_result(payload, "live-calendar-vs-parameters")
    assert result["outcome"] == outcome
    assert code == 0
    if outcome == "pass":
        details = result["details"]
        assert details["v-fromdate"] == "2024-01-01"
        assert details["v-isRolling"] == "0"
        assert details["v-daysAgo"] == "90"
        assert details["row_count"] == 730


def _set_param(model: Path, old: str, new: str) -> None:
    f = model / "definition" / "expressions.tmdl"
    text = f.read_text(encoding="utf-8")
    assert text.count(old) == 1
    f.write_text(text.replace(old, new), encoding="utf-8")


@pytest.mark.parametrize("edit, issues", [
    pytest.param(('v-rows_limit = " "', 'v-rows_limit = "LIMIT 1"'),
                 [("CRITICAL", "v-rows_limit")], id="limit-1"),
    pytest.param(('v-rows_limit = " "', 'v-rows_limit = "LIMIT 500"'),
                 [("WARNING", "v-rows_limit")], id="limit-500"),
    # BUGFIX: matching the substring 'LIMIT 1' reported LIMIT 10/100 as
    # CRITICAL. LIMIT 100 is a WARNING.
    pytest.param(('v-rows_limit = " "', 'v-rows_limit = "LIMIT 100"'),
                 [("WARNING", "v-rows_limit")], id="limit-100"),
    pytest.param(None, [], id="blank-limit"),
    # one year after the replay clock (2026-10-18)
    pytest.param(("#date(2024, 1, 1)", "#date(2027, 10, 18)"),
                 [("CRITICAL", "v-fromdate")], id="future-fromdate"),
    pytest.param("drop", None, id="no-expressions"),
])
def test_generate_connection_parameter_audit_report(tmp_path, edit, issues):
    model = coffee_copy(tmp_path)
    if edit == "drop":
        (model / "definition" / "expressions.tmdl").unlink()
    elif edit:
        _set_param(model, *edit)
    code, payload = live("params-calendar-730", "live-parameter-audit", model=model)
    result = check_result(payload, "live-parameter-audit")
    assert code == 0  # informational: the audit never fails the run
    if issues is None:
        assert result["outcome"] == "skip"
        return
    assert result["outcome"] == "pass"
    details = result["details"]
    assert [(i["severity"], i["parameter"]) for i in details["issues"]] == issues
    assert sorted(details["time_parameters"]) == ["v-daysAgo", "v-fromdate", "v-isRolling", "v-rows_limit"]
    assert details["live_sample"] == {"__Calendar": 730, "_Accounts": 40}
    critical = [i for i in details["issues"] if i["severity"] == "CRITICAL"]
    assert len(details["recommendations"]) == len(critical)
