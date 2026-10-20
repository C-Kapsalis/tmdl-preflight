"""Live best-practice analysis over the published model's metadata (E-live-bpa)
and the live client's health check (E-live-connection), in replay mode.

Stand-in metadata (``tests/fixtures/live/bpa``): measures ``!Revenue``
(``[Sales] / [Orders]``, no description), ``!Margin`` (``DIVIDE([P], [S])``,
described), ``Helper Ratio`` (``[A]/[B]``, no description); one calculated
column ``Sales[Band]``; 3 measures + 12 columns.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from conftest import FIXTURES, run_cli


def ReplayClient(path):
    # imported lazily so the module collects before the live API exists
    from tmdl_preflight.live import ReplayClient as _ReplayClient
    return _ReplayClient(path)


def LiveBPA(client):
    from tmdl_preflight.live import LiveBPA as _LiveBPA
    return _LiveBPA(client)

LIVE = FIXTURES / "live"
MODEL = LIVE / "models" / "coffee" / "Coffee.SemanticModel"


@pytest.fixture(scope="module")
def client():
    return ReplayClient(LIVE / "bpa")


@pytest.fixture(scope="module")
def bpa_engine(client):
    return LiveBPA(client)


@pytest.fixture(scope="module")
def bpa_report(bpa_engine):
    return bpa_engine.analyze_model()


class TestFabricBPAEngine:
    def test_bpa_engine_initialization(self, client):
        engine = LiveBPA(client)
        assert engine.client is not None
        assert len(engine.rules) > 0
        for rule in engine.rules:
            assert "id" in rule
            assert "name" in rule
            assert "severity" in rule
            assert 1 <= rule["severity"] <= 5

    def test_bpa_analysis_execution(self, bpa_engine):
        report = bpa_engine.analyze_model()
        assert report.total_objects_analyzed >= 0
        assert report.analysis_duration_ms > 0
        assert isinstance(report.timestamp, datetime)
        total_calculated = (report.critical_count + report.error_count
                            + report.warning_count + report.info_count)
        assert total_calculated == len(report.violations)

    def test_bpa_violation_structure(self, bpa_report):
        for violation in bpa_report.violations:
            assert violation.rule_id
            assert violation.rule_name
            assert violation.category
            assert 1 <= violation.severity <= 5
            assert violation.object_name
            assert violation.object_type
            assert violation.message


class TestBPACriticalViolations:
    def test_no_critical_bpa_violations(self, bpa_report):
        critical = [v for v in bpa_report.violations if v.severity >= 4]
        assert critical == []
        # the gate agrees
        code, out, _ = run_cli("live", MODEL, "--workspace", "ws-coffee", "--dataset", "ds-coffee",
                               "--replay", LIVE / "bpa", "--checks", "live-bpa", "--json")
        result = [c for c in json.loads(out)["checks"] if c["id"] == "live-bpa"][0]
        assert result["outcome"] == "pass"
        assert code == 0

    def test_bpa_analysis_did_not_fail(self, bpa_report):
        assert [v for v in bpa_report.violations if v.rule_id == "BPA_ANALYSIS_FAILED"] == []


class TestBPAPerformanceRules:
    def test_calculated_columns_detected(self, bpa_report):
        # BUGFIX: filtering INFO.COLUMNS() on a text type against the integer
        # Type column finds 0 calculated columns. The stand-in has one.
        found = [v for v in bpa_report.violations if v.rule_id == "PERF_CALCULATED_COLUMNS"]
        assert [v.object_name for v in found] == ["Sales[Band]"]

    def test_dax_division_usage(self, bpa_report):
        found = [v for v in bpa_report.violations if v.rule_id == "DAX_DIVISION_USAGE"]
        assert len(found) >= 0  # report only
        assert sorted(v.object_name for v in found) == ["!Revenue", "Helper Ratio"]
        assert all(v.severity == 3 for v in found)


class TestBPANamingRules:
    def test_user_facing_measures_have_descriptions(self, bpa_report):
        found = [v for v in bpa_report.violations if v.rule_id == "NAME_MEASURE_DESCRIPTIONS"]
        assert [v.object_name for v in found] == ["!Revenue"]


class TestBPAReporting:
    def test_bpa_report_json_export(self, bpa_report):
        data = json.loads(bpa_report.export_report_json())
        assert "summary" in data
        assert "violations" in data
        summary = data["summary"]
        assert "total_violations" in summary
        assert "critical_count" in summary
        assert "analysis_duration_ms" in summary
        required = ["rule_id", "rule_name", "category", "severity", "object_name",
                    "object_type", "message", "fix_suggestion", "timestamp"]
        for violation in data["violations"]:
            for field in required:
                assert field in violation

    def test_violations_by_severity_filter(self, bpa_report):
        critical = bpa_report.get_violations_by_severity(4)
        assert all(v.severity >= 4 for v in critical)
        errors_plus = bpa_report.get_violations_by_severity(3)
        assert all(v.severity >= 3 for v in errors_plus)
        assert len(errors_plus) >= len(critical)
        all_violations = bpa_report.get_violations_by_severity(1)
        assert len(all_violations) == len(bpa_report.violations)

    def test_bpa_performance_tracking(self, bpa_report):
        assert bpa_report.analysis_duration_ms < 30000
        assert bpa_report.total_objects_analyzed > 0
        assert bpa_report.total_objects_analyzed == 15  # 3 measures + 12 columns


class TestBPAIntegration:
    @pytest.mark.parametrize("scenario, status", [
        pytest.param("bpa", "healthy", id="bpa"),
        # EVALUATE { 1 } recorded as an error -> unhealthy
        pytest.param("bpa-health-error", "unhealthy", id="bpa-health-error"),
    ])
    def test_bpa_uses_existing_client(self, scenario, status):
        client = ReplayClient(LIVE / scenario)
        engine = LiveBPA(client)
        assert engine.client is client
        assert engine.client.health_check()["status"] == status

    def test_bpa_runs_with_data_quality_tests(self, bpa_report):
        # report only; with the bug fix: 2 division + 1 calculated column + 1 description
        assert len(bpa_report.violations) == 4
        assert bpa_report.critical_count == 0

    def test_generate_bpa_audit_report(self, bpa_report):
        categories = {}
        for v in bpa_report.violations:
            categories[v.category] = categories.get(v.category, 0) + 1
        assert categories == {"DAX Expressions": 2, "Performance": 1, "Naming Conventions": 1}
