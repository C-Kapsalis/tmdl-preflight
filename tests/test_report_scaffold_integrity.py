"""Report scaffold integrity (B008): the files a report folder must carry.

A report folder that was cloned or scaffolded by a script often misses a
file or carries a broken JSON file; Power BI Desktop then refuses to open
the project. The rule checks the file set, that every file parses, and the
three properties the loader reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, violations, write_config

PLATFORM_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                   "platformProperties/2.0.0/schema.json")
PBIR_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
               "definitionProperties/2.0.0/schema.json")
VERSION_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                  "definition/versionMetadata/1.0.0/schema.json")
REPORT_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                 "definition/report/3.0.0/schema.json")
PAGES_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definition/pagesMetadata/1.1.0/schema.json")


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _report(tmp_path: Path, name: str = "Roastery.Report") -> Path:
    """A complete report folder (the eight cases start from here)."""
    report = tmp_path / name
    _write(report / ".platform",
           {"$schema": PLATFORM_SCHEMA, "config": {"logicalId": "6d1c9a30-5b47-4f8e-9c2b-0a7d3e6b1f58"}})
    _write(report / "definition.pbir",
           {"$schema": PBIR_SCHEMA, "version": "4.0",
            "datasetReference": {"byPath": {"path": "../Roastery.SemanticModel"}}})
    _write(report / "definition" / "version.json",
           {"$schema": VERSION_SCHEMA, "version": "2.0.0"})
    _write(report / "definition" / "report.json",
           {"$schema": REPORT_SCHEMA, "themeCollection": {}})
    _write(report / "definition" / "pages" / "pages.json",
           {"$schema": PAGES_SCHEMA, "pageOrder": ["p1"]})
    return report


def _messages(payload: dict) -> list[str]:
    return [v["message"] for v in violations(payload, "B008")]


class TestReportScaffoldIntegrity:
    def test_a_complete_report_passes(self, tmp_path):
        code, payload = run_check(_report(tmp_path), "B008")
        assert code == 0, payload
        assert violations(payload, "B008") == []

    def test_a_missing_platform_is_one_violation(self, tmp_path):
        report = _report(tmp_path)
        (report / ".platform").unlink()
        code, payload = run_check(report, "B008")
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert ".platform" in found[0]

    def test_a_truncated_version_json_is_one_violation(self, tmp_path):
        report = _report(tmp_path)
        (report / "definition" / "version.json").write_text('{"version": "2.0.0"',
                                                            encoding="utf-8")
        code, payload = run_check(report, "B008")
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert "definition/version.json" in found[0]
        assert "not valid JSON" in found[0]

    def test_a_platform_without_a_logical_id_is_one_violation(self, tmp_path):
        report = _report(tmp_path)
        _write(report / ".platform", {"$schema": PLATFORM_SCHEMA, "config": {}})
        code, payload = run_check(report, "B008")
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert "config.logicalId" in found[0]

    def test_a_version_json_without_a_schema_is_one_violation(self, tmp_path):
        report = _report(tmp_path)
        _write(report / "definition" / "version.json", {"version": "2.0.0"})
        code, payload = run_check(report, "B008")
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert "$schema" in found[0]

    def test_a_definition_pbir_without_a_version_is_one_violation(self, tmp_path):
        report = _report(tmp_path)
        _write(report / "definition.pbir",
               {"$schema": PBIR_SCHEMA, "datasetReference": {"byPath": {"path": "../x"}}})
        code, payload = run_check(report, "B008")
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert "version" in found[0]

    def test_the_blank_report_form_passes(self, tmp_path):
        report = tmp_path / "Blank.Report"
        _write(report / ".platform",
               {"$schema": PLATFORM_SCHEMA, "config": {"logicalId": "6d1c9a30-5b47-4f8e-9c2b-0a7d3e6b1f58"}})
        _write(report / "definition.pbir",
               {"$schema": PBIR_SCHEMA, "version": "4.0",
                "datasetReference": {"byPath": {"path": "../Blank.SemanticModel"}}})
        code, payload = run_check(report, "B008")
        assert code == 0, payload
        assert violations(payload, "B008") == []

    def test_a_report_with_pages_but_no_pages_json_is_one_violation(self, tmp_path):
        report = _report(tmp_path)
        (report / "definition" / "pages" / "pages.json").unlink()
        code, payload = run_check(report, "B008")
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert "definition/pages/pages.json" in found[0]

    def test_the_required_files_option_adds_a_file(self, tmp_path):
        report = _report(tmp_path)
        config = write_config(tmp_path, {
            "rules": {"B008": {"required_files": [
                ".platform", "definition.pbir", "definition/version.json",
                "definition/report.json", "StaticResources/theme.json"]}},
        })
        code, payload = run_check(report, "B008", config=config)
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert "StaticResources/theme.json" in found[0]
