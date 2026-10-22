"""Report-format schema (B007): the files a PBIR report carries and the
schemas they must declare.

The report folder is what Desktop opens and what Fabric imports. A missing
``definition.pbir``, a ``version.json`` without its ``$schema``, a
``report.json`` without ``themeCollection`` or a content file without
``$schema`` all fail at import time, long after the file was written.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_check, run_fix, violations

PBIR_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
               "definitionProperties/2.0.0/schema.json")
VERSION_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                  "definition/versionMetadata/1.0.0/schema.json")
REPORT_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                 "definition/report/3.0.0/schema.json")
REPORT_SCHEMA_31 = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                    "definition/report/3.1.0/schema.json")


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _messages(payload: dict, rule: str = "B007") -> list[str]:
    return [v["message"] for v in violations(payload, rule)]


class TestDefinitionPbir:
    """PB89: definition.pbir is required and must declare a usable version."""

    def test_clean_report_passes(self, project):
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert violations(payload, "B007") == []

    def test_missing_pbir_is_an_error(self, project, report_dir):
        (report_dir / "definition.pbir").unlink()
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: Missing definition.pbir" in _messages(payload)

    def test_invalid_json_stops_the_pbir_checks(self, project, report_dir):
        (report_dir / "definition.pbir").write_text("{ not json", encoding="utf-8")
        code, payload = run_check(project, "B007")
        assert code == 1
        found = _messages(payload)
        assert len(found) == 1
        assert found[0].startswith("BikeShop.Report: Invalid JSON in definition.pbir: ")

    def test_missing_schema_is_a_warning(self, project, report_dir):
        _write(report_dir / "definition.pbir",
               {"version": "4.0", "datasetReference": {"byPath": {"path": "../BikeShop.SemanticModel"}}})
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert ("BikeShop.Report: definition.pbir missing $schema property "
                "(recommended for IntelliSense)") in _messages(payload)

    def test_unexpected_schema_is_a_warning(self, project, report_dir):
        _write(report_dir / "definition.pbir",
               {"$schema": "https://example.com/other.json", "version": "4.0",
                "datasetReference": {"byPath": {"path": "../BikeShop.SemanticModel"}}})
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert ("BikeShop.Report: definition.pbir has unexpected $schema: "
                "https://example.com/other.json") in _messages(payload)

    def test_missing_version_is_an_error(self, project, report_dir):
        _write(report_dir / "definition.pbir",
               {"$schema": PBIR_SCHEMA, "datasetReference": {"byPath": {"path": "../x"}}})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: definition.pbir missing version property" in _messages(payload)

    def test_invalid_version_format_is_an_error(self, project, report_dir):
        _write(report_dir / "definition.pbir",
               {"$schema": PBIR_SCHEMA, "version": "4",
                "datasetReference": {"byPath": {"path": "../x"}}})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: definition.pbir has invalid version format: 4" in _messages(payload)

    def test_non_string_version_is_an_invalid_format(self, project, report_dir):
        """BUGFIX: the original crashed on a version that is not a string."""
        _write(report_dir / "definition.pbir",
               {"$schema": PBIR_SCHEMA, "version": 4,
                "datasetReference": {"byPath": {"path": "../x"}}})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: definition.pbir has invalid version format: 4" in _messages(payload)

    def test_missing_dataset_reference_is_an_error(self, project, report_dir):
        _write(report_dir / "definition.pbir", {"$schema": PBIR_SCHEMA, "version": "4.0"})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: definition.pbir missing datasetReference" in _messages(payload)

    def test_dataset_reference_without_by_path_or_by_connection_is_an_error(self, project, report_dir):
        _write(report_dir / "definition.pbir",
               {"$schema": PBIR_SCHEMA, "version": "4.0", "datasetReference": {}})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: datasetReference missing byPath or byConnection" in _messages(payload)

    def test_version_four_point_zero_passes(self, project, report_dir):
        _write(report_dir / "definition.pbir",
               {"$schema": PBIR_SCHEMA, "version": "4.0",
                "datasetReference": {"byPath": {"path": "../x"}}})
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert violations(payload, "B007") == []


class TestReportJsonAndVersionJson:
    """PB90: report.json lives at exactly one place; the new format needs version.json."""

    def test_both_report_json_locations_is_an_error(self, project, report_dir):
        _write(report_dir / "report.json", {"$schema": REPORT_SCHEMA, "themeCollection": {}})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: Has BOTH root and definition/report.json" in _messages(payload)

    def test_no_report_json_at_all_is_an_error(self, project, report_dir):
        (report_dir / "definition" / "report.json").unlink()
        code, payload = run_check(project, "B007")
        assert code == 1
        assert ("BikeShop.Report: Missing report.json (neither at root nor in definition/)"
                in _messages(payload))

    def test_missing_version_json_is_an_error(self, project, report_dir):
        (report_dir / "definition" / "version.json").unlink()
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: New format but missing version.json" in _messages(payload)

    def test_invalid_version_json_is_an_error(self, project, report_dir):
        (report_dir / "definition" / "version.json").write_text("{", encoding="utf-8")
        code, payload = run_check(project, "B007")
        assert code == 1
        found = [m for m in _messages(payload) if "Invalid JSON in version.json" in m]
        assert len(found) == 1

    def test_version_json_without_schema_is_an_error(self, project, report_dir):
        _write(report_dir / "definition" / "version.json", {"version": "2.0.0"})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: version.json MISSING $schema property" in _messages(payload)

    def test_version_json_with_the_wrong_schema_is_an_error(self, project, report_dir):
        _write(report_dir / "definition" / "version.json",
               {"$schema": "https://example.com/other.json", "version": "2.0.0"})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert ("BikeShop.Report: version.json has incorrect $schema: https://example.com/other.json"
                in _messages(payload))

    def test_version_json_without_version_is_an_error(self, project, report_dir):
        _write(report_dir / "definition" / "version.json", {"$schema": VERSION_SCHEMA})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: version.json MISSING version property" in _messages(payload)

    def test_invalid_version_json_version_format_is_an_error(self, project, report_dir):
        _write(report_dir / "definition" / "version.json",
               {"$schema": VERSION_SCHEMA, "version": "2.0"})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: version.json has INVALID version format: '2.0'" in _messages(payload)

    def test_unexpected_version_json_properties_warn(self, project, report_dir):
        _write(report_dir / "definition" / "version.json",
               {"$schema": VERSION_SCHEMA, "version": "2.0.0", "extra": 1})
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert "BikeShop.Report: version.json has unexpected properties: {'extra'}" in _messages(payload)

    def test_version_four_warns_about_compatibility(self, project, report_dir):
        _write(report_dir / "definition" / "version.json",
               {"$schema": VERSION_SCHEMA, "version": "4.0.0"})
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert ("BikeShop.Report: version.json is 4.0.0, recommend 2.0.0 for compatibility"
                in _messages(payload))

    def test_two_errors_and_one_warning(self, project, report_dir):
        _write(report_dir / "definition" / "version.json",
               {"$schema": "https://example.com/other.json", "version": "2.0", "extra": 1})
        code, payload = run_check(project, "B007")
        assert code == 1
        found = violations(payload, "B007")
        assert len(found) == 3
        assert sum(1 for v in found if v["severity"] == "error") == 2
        assert sum(1 for v in found if v["severity"] == "warning") == 1


class TestDefinitionReportJson:
    """PB91: the new format's report.json needs a schema and a theme."""

    def test_invalid_report_json_is_an_error(self, project, report_dir):
        (report_dir / "definition" / "report.json").write_text("{", encoding="utf-8")
        code, payload = run_check(project, "B007")
        assert code == 1
        found = [m for m in _messages(payload) if "Invalid JSON in report.json" in m]
        assert len(found) == 1

    def test_missing_schema_is_an_error(self, project, report_dir):
        _write(report_dir / "definition" / "report.json", {"themeCollection": {}})
        code, payload = run_check(project, "B007")
        assert code == 1
        assert "BikeShop.Report: report.json MISSING $schema property" in _messages(payload)

    def test_unexpected_schema_is_a_warning(self, project, report_dir):
        _write(report_dir / "definition" / "report.json",
               {"$schema": "https://example.com/other.json", "themeCollection": {}})
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert ("BikeShop.Report: report.json has unexpected $schema: https://example.com/other.json"
                in _messages(payload))

    def test_both_accepted_schemas_pass(self, project, report_dir):
        for schema in (REPORT_SCHEMA, REPORT_SCHEMA_31):
            _write(report_dir / "definition" / "report.json",
                   {"$schema": schema, "themeCollection": {}})
            code, payload = run_check(project, "B007")
            assert code == 0, payload

    def test_missing_theme_collection_is_an_error(self, project, report_dir):
        _write(report_dir / "definition" / "report.json", {"$schema": REPORT_SCHEMA})
        code, payload = run_check(project, "B007")
        assert code == 1
        found = [m for m in _messages(payload) if "report.json" in m]
        assert len(found) == 1
        assert found[0] == ("BikeShop.Report: report.json MISSING required property "
                            "'themeCollection'")


class TestContentFileSchemas:
    """PB92: every PBIR content file declares its $schema."""

    def _strip(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("$schema", None)
        _write(path, data)

    def test_missing_schemas_are_four_errors(self, project, report_dir):
        self._strip(report_dir / "definition" / "pages" / "overview" / "page.json")
        self._strip(report_dir / "definition" / "pages" / "overview" / "visuals" /
                    "a1b2c3d4e5f6" / "visual.json")
        self._strip(report_dir / "definition" / "bookmarks" / "spotlight-revenue.bookmark.json")
        self._strip(report_dir / ".platform")
        code, payload = run_check(project, "B007")
        assert code == 1
        found = [m for m in _messages(payload) if "MISSING $schema property" in m]
        assert len(found) == 4
        assert "BikeShop.Report: definition/pages/overview/page.json MISSING $schema property" in found
        assert ("BikeShop.Report: definition/pages/overview/visuals/a1b2c3d4e5f6/visual.json "
                "MISSING $schema property") in found
        assert ("BikeShop.Report: definition/bookmarks/spotlight-revenue.bookmark.json "
                "MISSING $schema property") in found
        assert "BikeShop.Report: .platform MISSING $schema property" in found

    def test_invalid_content_file_is_an_error(self, project, report_dir):
        (report_dir / "definition" / "pages" / "overview" / "page.json").write_text(
            "{ not json", encoding="utf-8")
        code, payload = run_check(project, "B007")
        assert code == 1
        found = [m for m in _messages(payload) if "Invalid JSON in page.json" in m]
        assert len(found) == 1

    def test_a_json_array_is_skipped(self, project, report_dir):
        _write(report_dir / "definition" / "pages" / "overview" / "page.json", [])
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert violations(payload, "B007") == []


class TestLocalSettings:
    """PB93: .pbi/localSettings.json is machine specific and must not be committed."""

    def test_local_settings_in_version_control_warns(self, project, report_dir):
        settings = report_dir / ".pbi" / "localSettings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        _write(settings, {"version": "1.0"})
        code, payload = run_check(project, "B007")
        assert code == 0, payload
        assert ("BikeShop.Report: .pbi/localSettings.json found in version control "
                "(should be in .gitignore - it's user/machine specific)") in _messages(payload)


class TestReportFormatFixer:
    """PB94: the fixer repairs version.json and the report.json settings."""

    def test_version_json_is_repaired_whole(self, project, report_dir):
        version_file = report_dir / "definition" / "version.json"
        _write(version_file, {"$schema": "https://example.com/other.json", "version": "2.0"})
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        assert version_file.read_text(encoding="utf-8") == (
            "{\n"
            f"  \"$schema\": \"{VERSION_SCHEMA}\",\n"
            "  \"version\": \"2.0.0\"\n"
            "}\n"
        )
        assert any("Fixed $schema URL" in f for f in payload["fixes"])
        assert any("Fixed version 2.0 -> 2.0.0" in f or "Fixed version 2.0 → 2.0.0" in f
                   for f in payload["fixes"])

    def test_missing_schema_is_added_at_the_end(self, project, report_dir):
        version_file = report_dir / "definition" / "version.json"
        _write(version_file, {"version": "2.0"})
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        assert version_file.read_text(encoding="utf-8") == (
            "{\n"
            "  \"version\": \"2.0.0\",\n"
            f"  \"$schema\": \"{VERSION_SCHEMA}\"\n"
            "}\n"
        )
        assert any("Added $schema" in f for f in payload["fixes"])

    def test_a_version_with_a_patch_part_is_repaired(self, project, report_dir):
        version_file = report_dir / "definition" / "version.json"
        _write(version_file, {"$schema": VERSION_SCHEMA, "version": "2.0.1"})
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        assert json.loads(version_file.read_text(encoding="utf-8"))["version"] == "2.0.0"

    def test_report_json_settings_are_repaired(self, project, report_dir):
        report_file = report_dir / "definition" / "report.json"
        _write(report_file, {"$schema": REPORT_SCHEMA, "themeCollection": {},
                             "settings": {"allowInlineExploration": True}})
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        data = json.loads(report_file.read_text(encoding="utf-8"))
        assert data["settings"] == {"exportDataMode": "AllowSummarized",
                                    "useDefaultAggregateDisplayName": True}
        assert any("Fixed report.json settings" in f for f in payload["fixes"])

    def test_report_json_without_settings_is_left_alone(self, project, report_dir):
        report_file = report_dir / "definition" / "report.json"
        before = report_file.read_text(encoding="utf-8")
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        assert report_file.read_text(encoding="utf-8") == before

    def test_non_ascii_is_written_literally(self, project, report_dir):
        version_file = report_dir / "definition" / "version.json"
        version_file.write_text(
            "{\n  \"$schema\": \"" + VERSION_SCHEMA + "\",\n  \"version\": \"2.0.0\",\n"
            "  \"note\": \"caf\u00e9\"\n}\n", encoding="utf-8")
        code, payload = run_fix(project, "B007")
        assert code == 0, payload

    def test_the_fixer_is_idempotent(self, project, report_dir):
        version_file = report_dir / "definition" / "version.json"
        _write(version_file, {"version": "2.0"})
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        first = version_file.read_text(encoding="utf-8")
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        assert version_file.read_text(encoding="utf-8") == first
        assert payload["fixes"] == []

    def test_the_fixed_count_is_reported(self, project, report_dir):
        _write(report_dir / "definition" / "version.json", {"version": "2.0"})
        code, payload = run_fix(project, "B007")
        assert code == 0, payload
        assert any("Fixed 1 files" in n for n in payload["notes"])
