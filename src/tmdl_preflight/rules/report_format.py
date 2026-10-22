"""Report-folder rules: the PBIR file set and the schemas it declares (B007, B008).

The report folder is what Power BI Desktop opens and what Fabric imports.
The files it must carry, and the properties each of them must declare, are
published by Microsoft; a file that is missing a property is rejected at
import time, long after it was written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from ..edits import EditRefused, read_text_file, write_json
from .base import Context, Rule, Severity, Violation

# The published Microsoft Fabric schemas a PBIR report declares.
DEFINITION_PBIR_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                           "definitionProperties/2.0.0/schema.json")
VERSION_METADATA_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                            "definition/versionMetadata/1.0.0/schema.json")
REPORT_SCHEMAS = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json",
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.1.0/schema.json",
)

# definition.pbir carries the report format version ("4.0"); version.json
# carries the definition version ("2.0.0"), whose patch part is always 0.
PBIR_VERSION = re.compile(r"^\d+\.\d+$")
DEFINITION_VERSION = re.compile(r"^[1-9][0-9]*\.(0|[1-9][0-9]*)\.0$")


def load_json(path: Path) -> tuple[Optional[Any], Optional[str]]:
    """The parsed document and the parser error (None when it parsed).

    A byte-order mark is tolerated: the file is still JSON.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return None, str(exc)


class ReportFormatSchemaRule(Rule):
    id = "B007"
    name = "report-format-schema"
    severity = Severity.ERROR
    fixable = True
    description = (
        "A PBIR report must carry the files Fabric imports and the schemas "
        "they declare: definition.pbir with a version and a dataset "
        "reference, exactly one report.json, a version.json that declares "
        "the version-metadata schema, and a $schema on every content file. "
        "A missing or wrong value is rejected at import time. The auto-fix "
        "adds and corrects the schema URLs and the version format."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            out.extend(self._check_report(report_dir))
        return out

    def _finding(self, message: str, file: Optional[Path] = None,
                 obj: Optional[str] = None,
                 severity: Optional[Severity] = None) -> Violation:
        """A finding the fixer does not repair."""
        return self.violation(message, file=file, obj=obj, severity=severity,
                              fixable=False)

    # -- the report folder ---------------------------------------------------

    def _check_report(self, report_dir: Path) -> list[Violation]:
        out: list[Violation] = []
        name = report_dir.name
        out.extend(self._check_pbir(report_dir))
        root_report = report_dir / "report.json"
        def_report = report_dir / "definition" / "report.json"
        has_root = root_report.is_file()
        has_def = def_report.is_file()
        if has_root and has_def:
            out.append(self._finding(
                f"{name}: Has BOTH root and definition/report.json", file=report_dir))
        elif not has_root and not has_def:
            out.append(self._finding(
                f"{name}: Missing report.json (neither at root nor in definition/)",
                file=report_dir))
        if has_def:
            out.extend(self._check_version_json(
                report_dir / "definition" / "version.json", name))
            out.extend(self._check_definition_report_json(def_report, name))
        out.extend(self._check_content_files(report_dir))
        local_settings = report_dir / ".pbi" / "localSettings.json"
        if local_settings.is_file():
            out.append(self._finding(
                f"{name}: .pbi/localSettings.json found in version control (should be "
                "in .gitignore - it's user/machine specific)",
                file=local_settings, severity=Severity.WARNING))
        return out

    def _check_pbir(self, report_dir: Path) -> list[Violation]:
        out: list[Violation] = []
        name = report_dir.name
        pbir = report_dir / "definition.pbir"
        if not pbir.is_file():
            out.append(self._finding(f"{name}: Missing definition.pbir", file=pbir))
            return out
        data, error = load_json(pbir)
        if error is not None:
            out.append(self._finding(
                f"{name}: Invalid JSON in definition.pbir: {error}", file=pbir))
            return out
        if not isinstance(data, dict):
            out.append(self._finding(
                f"{name}: definition.pbir is not a JSON object", file=pbir))
            return out
        if "$schema" not in data:
            out.append(self._finding(
                f"{name}: definition.pbir missing $schema property "
                "(recommended for IntelliSense)",
                file=pbir, severity=Severity.WARNING))
        elif data["$schema"] != DEFINITION_PBIR_SCHEMA:
            out.append(self._finding(
                f"{name}: definition.pbir has unexpected $schema: {data['$schema']}",
                file=pbir, severity=Severity.WARNING))
        if "version" not in data:
            out.append(self._finding(
                f"{name}: definition.pbir missing version property", file=pbir))
        else:
            version = data["version"]
            if not isinstance(version, str) or not PBIR_VERSION.match(version):
                out.append(self._finding(
                    f"{name}: definition.pbir has invalid version format: {version}",
                    file=pbir))
        if "datasetReference" not in data:
            out.append(self._finding(
                f"{name}: definition.pbir missing datasetReference", file=pbir))
        else:
            reference = data["datasetReference"]
            if not isinstance(reference, dict) or (
                    "byPath" not in reference and "byConnection" not in reference):
                out.append(self._finding(
                    f"{name}: datasetReference missing byPath or byConnection", file=pbir))
        return out

    def _check_version_json(self, version_file: Path, name: str) -> list[Violation]:
        out: list[Violation] = []
        if not version_file.is_file():
            out.append(self._finding(
                f"{name}: New format but missing version.json", file=version_file))
            return out
        data, error = load_json(version_file)
        if error is not None:
            out.append(self._finding(
                f"{name}: Invalid JSON in version.json: {error}", file=version_file))
            return out
        if not isinstance(data, dict):
            out.append(self._finding(
                f"{name}: version.json is not a JSON object", file=version_file))
            return out
        if "$schema" not in data:
            out.append(self.violation(
                f"{name}: version.json MISSING $schema property", file=version_file,
                fixable=True))
        elif data["$schema"] != VERSION_METADATA_SCHEMA:
            out.append(self.violation(
                f"{name}: version.json has incorrect $schema: {data['$schema']}",
                file=version_file, fixable=True))
        if "version" not in data:
            out.append(self._finding(
                f"{name}: version.json MISSING version property", file=version_file))
        else:
            version = data["version"]
            if not isinstance(version, str) or not DEFINITION_VERSION.match(version):
                repairable = (isinstance(version, str)
                              and self._repair_version(version) is not None)
                out.append(self.violation(
                    f"{name}: version.json has INVALID version format: '{version}'",
                    file=version_file, fixable=repairable))
        unexpected = set(data) - {"$schema", "version"}
        if unexpected:
            out.append(self._finding(
                f"{name}: version.json has unexpected properties: {unexpected}",
                file=version_file, severity=Severity.WARNING))
        if data.get("version") == "4.0.0":
            out.append(self._finding(
                f"{name}: version.json is 4.0.0, recommend 2.0.0 for compatibility",
                file=version_file, severity=Severity.WARNING))
        return out

    def _check_definition_report_json(self, report_file: Path, name: str) -> list[Violation]:
        out: list[Violation] = []
        data, error = load_json(report_file)
        if error is not None:
            out.append(self._finding(
                f"{name}: Invalid JSON in report.json: {error}", file=report_file))
            return out
        if not isinstance(data, dict):
            out.append(self._finding(
                f"{name}: report.json is not a JSON object", file=report_file))
            return out
        if "$schema" not in data:
            out.append(self._finding(
                f"{name}: report.json MISSING $schema property", file=report_file))
        elif data["$schema"] not in REPORT_SCHEMAS:
            out.append(self._finding(
                f"{name}: report.json has unexpected $schema: {data['$schema']}",
                file=report_file, severity=Severity.WARNING))
        if "themeCollection" not in data:
            out.append(self._finding(
                f"{name}: report.json MISSING required property 'themeCollection'",
                file=report_file))
        return out

    def _check_content_files(self, report_dir: Path) -> list[Violation]:
        out: list[Violation] = []
        name = report_dir.name
        definition = report_dir / "definition"
        if not definition.is_dir():
            return out
        pages = definition / "pages"
        files: list[Path] = []
        if pages.is_dir():
            files.extend(sorted(pages.rglob("*/page.json")))
            files.extend(sorted(pages.rglob("*/visuals/*/visual.json")))
        bookmarks = definition / "bookmarks"
        if bookmarks.is_dir():
            files.extend(sorted(bookmarks.rglob("*.bookmark.json")))
        platform = report_dir / ".platform"
        if platform.is_file():
            files.append(platform)
        for path in files:
            data, error = load_json(path)
            if error is not None:
                out.append(self._finding(
                    f"{name}: Invalid JSON in {path.name}: {error}", file=path))
                continue
            if not isinstance(data, dict):
                continue  # a JSON array (pages.json) carries no $schema
            if "$schema" not in data:
                out.append(self._finding(
                    f"{name}: {path.relative_to(report_dir).as_posix()} MISSING "
                    "$schema property", file=path))
        return out

    # -- the fixer ------------------------------------------------------------

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        fixed = 0
        for report_dir in ctx.report_dirs:
            fixed += self._fix_report(report_dir, applied)
        if fixed:
            ctx.notes.append(f"Fixed {fixed} files")
        return applied

    def _fix_report(self, report_dir: Path, applied: list[str]) -> int:
        fixed = 0
        version_file = report_dir / "definition" / "version.json"
        if version_file.is_file() and self._fix_version_json(version_file, applied):
            fixed += 1
        report_file = report_dir / "definition" / "report.json"
        if report_file.is_file() and self._fix_report_json(report_file, applied):
            fixed += 1
        return fixed

    def _fix_version_json(self, path: Path, applied: list[str]) -> bool:
        name = path.parent.parent.name
        original = read_text_file(path)
        data, error = load_json(path)
        if error is not None or not isinstance(data, dict):
            return False
        repaired = self._repaired_version(data)
        if repaired is None:
            return False
        messages: list[str] = []
        if "$schema" not in data:
            messages.append(f"✅ {name}: Added $schema")
        elif data["$schema"] != VERSION_METADATA_SCHEMA:
            messages.append(f"✅ {name}: Fixed $schema URL")
        version = data.get("version")
        if isinstance(version, str) and repaired.get("version") != version:
            messages.append(f"✅ {name}: Fixed version {version} → {repaired['version']}")
        try:
            written = write_json(original, repaired)
        except EditRefused:
            return False
        if written:
            applied.extend(messages)
        return written

    @staticmethod
    def _repaired_version(data: dict) -> Optional[dict]:
        """The repaired version.json document, or None when it needs no repair."""
        repaired = dict(data)
        changed = False
        if "$schema" not in repaired:
            repaired["$schema"] = VERSION_METADATA_SCHEMA
            changed = True
        elif repaired["$schema"] != VERSION_METADATA_SCHEMA:
            repaired["$schema"] = VERSION_METADATA_SCHEMA
            changed = True
        version = repaired.get("version")
        if isinstance(version, str):
            fixed = ReportFormatSchemaRule._repair_version(version)
            if fixed is not None and fixed != version:
                repaired["version"] = fixed
                changed = True
        return repaired if changed else None

    @staticmethod
    def _repair_version(version: str) -> Optional[str]:
        """The version string the schema accepts, or None when there is none."""
        if PBIR_VERSION.match(version):
            return f"{version}.0"
        if DEFINITION_VERSION.match(version):
            return version
        parts = version.split(".")
        if len(parts) < 2:
            return None
        try:
            major, minor = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        if major < 1:
            return None
        return f"{major}.{minor}.0"

    def _fix_report_json(self, path: Path, applied: list[str]) -> bool:
        name = path.parent.parent.name
        original = read_text_file(path)
        data, error = load_json(path)
        if error is not None or not isinstance(data, dict):
            return False
        repaired = self._repaired_settings(data)
        if repaired is None:
            return False
        try:
            written = write_json(original, repaired)
        except EditRefused:
            return False
        if written:
            applied.append(f"✅ {name}: Fixed report.json settings")
        return written

    @staticmethod
    def _repaired_settings(data: dict) -> Optional[dict]:
        """The repaired report.json document, or None when it needs no repair."""
        settings = data.get("settings")
        if not isinstance(settings, dict):
            return None
        repaired_settings = dict(settings)
        changed = False
        if "exportDataMode" not in repaired_settings:
            repaired_settings["exportDataMode"] = "AllowSummarized"
            changed = True
        if "useDefaultAggregateDisplayName" not in repaired_settings:
            repaired_settings["useDefaultAggregateDisplayName"] = True
            changed = True
        for key in ("allowInlineExploration", "queryLimitOption"):
            if key in repaired_settings:
                del repaired_settings[key]
                changed = True
        if not changed:
            return None
        repaired = dict(data)
        repaired["settings"] = repaired_settings
        return repaired

    def pending_repairs(self, ctx: Context) -> bool:
        """True when a report file needs a repair the check does not report."""
        for report_dir in ctx.report_dirs:
            for path, repair in (
                (report_dir / "definition" / "version.json", self._repaired_version),
                (report_dir / "definition" / "report.json", self._repaired_settings),
            ):
                if not path.is_file():
                    continue
                data, error = load_json(path)
                if error is None and isinstance(data, dict) and repair(data):
                    return True
        return False


# The files every report folder must carry, and the properties the loader
# reads out of them.
DEFAULT_REQUIRED_FILES = (
    ".platform",
    "definition.pbir",
    "definition/version.json",
    "definition/report.json",
)
# The blank-report form (only .platform and definition.pbir) opens in
# Desktop as an empty canvas; it needs no version.json and no report.json.
BLANK_FORM_FILES = (".platform", "definition.pbir")
BLANK_FORM_EXEMPT = ("definition/version.json", "definition/report.json")

SCAFFOLD_PROPERTIES = {
    "definition/version.json": [
        (("$schema",), "the report's definition version cannot be read"),
    ],
    ".platform": [
        (("config", "logicalId"),
         "the report item has no identity for the Fabric Git sync"),
    ],
    "definition.pbir": [
        (("version",), "the report's format version is unknown"),
    ],
}


class ReportScaffoldIntegrityRule(Rule):
    id = "B008"
    name = "report-scaffold-integrity"
    severity = Severity.ERROR
    option_defaults = {"required_files": list(DEFAULT_REQUIRED_FILES)}
    description = (
        "A report folder that was cloned or scaffolded by a script often "
        "misses a file or carries a broken JSON file; Power BI Desktop then "
        "refuses to open the project. Every *.Report folder must carry "
        ".platform, definition.pbir, definition/version.json and "
        "definition/report.json (and pages.json when the report has pages), "
        "each of them must parse, and the three properties the loader reads "
        "must be there. A folder that holds only .platform and definition.pbir "
        "is the blank-report form and needs no version.json or report.json."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            out.extend(self._check_report(report_dir))
        return out

    def _check_report(self, report_dir: Path) -> list[Violation]:
        out: list[Violation] = []
        name = report_dir.name
        required = list(self.options.get("required_files") or DEFAULT_REQUIRED_FILES)
        if self._is_blank_form(report_dir):
            required = [r for r in required if r not in BLANK_FORM_EXEMPT]
        if (report_dir / "definition" / "pages").is_dir():
            required.append("definition/pages/pages.json")
        for rel in required:
            path = report_dir / rel
            if not path.is_file():
                out.append(self.violation(
                    f"{name}: {rel} is missing; Power BI Desktop cannot open a "
                    "report folder without it.", file=path))
                continue
            data, error = load_json(path)
            if error is not None:
                if rel == "definition/pages/pages.json":
                    continue  # B004 reports the pages metadata
                out.append(self.violation(
                    f"{name}: {rel} is not valid JSON ({error}); Power BI Desktop "
                    "cannot open a report folder whose files do not parse.",
                    file=path))
                continue
            if not isinstance(data, dict):
                continue
            out.extend(self._check_properties(rel, data, name, path))
        return out

    def _check_properties(self, rel: str, data: dict, name: str, path: Path) -> list[Violation]:
        out: list[Violation] = []
        for prop, why in SCAFFOLD_PROPERTIES.get(rel, ()):
            value: Any = data
            for key in prop:
                if not isinstance(value, dict) or key not in value:
                    value = None
                    break
                value = value[key]
            if not isinstance(value, str) or not value.strip():
                out.append(self.violation(
                    f"{name}: {rel} has no {'.'.join(prop)} property; {why}.",
                    file=path))
        return out

    @staticmethod
    def _is_blank_form(report_dir: Path) -> bool:
        """Does the folder hold nothing but .platform and definition.pbir?"""
        files = {p.relative_to(report_dir).as_posix()
                 for p in report_dir.rglob("*") if p.is_file()}
        return files <= set(BLANK_FORM_FILES)
