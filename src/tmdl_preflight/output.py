"""Report renderers: text, json, github, sarif, markdown.

Every renderer takes the finished ``PreflightReport`` and returns the full
output as a string; none of them decides the exit code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from . import __version__
from .engine import PreflightReport
from .rules.base import RuleSet, Severity, Violation

FORMATS = ("text", "json", "github", "sarif", "markdown")

_SEVERITY_TAG = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}

_SCAN_LABELS = (
    ("models", "model"),
    ("tables", "table"),
    ("columns", "column"),
    ("measures", "measure"),
    ("relationships", "relationship"),
    ("dax_blocks", "DAX expression"),
    ("reports", "report"),
    ("bookmarks", "bookmark"),
)


def _sorted(violations: list[Violation]) -> list[Violation]:
    return sorted(violations, key=lambda v: (str(v.file or ""), v.line or 0, v.rule_id))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def scanned_line(scanned: dict[str, int]) -> str:
    optional = {"reports", "bookmarks"}
    parts = [
        _plural(scanned.get(key, 0), label)
        for key, label in _SCAN_LABELS
        if key not in optional or scanned.get(key)
    ]
    return "scanned: " + ", ".join(parts)


def _display_path(file: Optional[Path], root: Path) -> str:
    if file is None:
        return ""
    try:
        return str(Path(file).relative_to(root))
    except ValueError:
        return str(file)


def _cwd_relative(file: Optional[Path]) -> str:
    """POSIX path relative to the working directory when possible."""
    if file is None:
        return ""
    p = Path(file)
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (ValueError, OSError):
        return p.as_posix()


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------


def render_text(report: PreflightReport, root: Path) -> str:
    out: list[str] = []
    for applied in report.fixes_applied:
        out.append(f"fixed  {applied}")
    if report.fixes_applied:
        out.append("")
    for v in _sorted(report.violations):
        loc = _display_path(v.file, root)
        if loc and v.line:
            loc += f":{v.line}"
        prefix = f"{loc}  " if loc else ""
        obj = f" [{v.obj}]" if v.obj else ""
        fixable = " (auto-fixable)" if v.fixable else ""
        out.append(f"{prefix}{v.rule_id} {_SEVERITY_TAG[v.severity]}: {v.message}{obj}{fixable}")
    out.append("")
    if report.scanned:
        out.append(scanned_line(report.scanned))
    notes = _notes(report)
    out.extend(notes)
    e, w, i = len(report.errors), len(report.warnings), len(report.infos)
    out.append(
        f"tmdl-preflight: {e} error(s), {w} warning(s), {i} info(s)"
        + (f", {len(report.fixes_applied)} fix(es) applied" if report.fixes_applied else "")
    )
    return "\n".join(out)


def _notes(report: PreflightReport) -> list[str]:
    notes: list[str] = []
    if report.excluded:
        notes.append(f"excluded: {len(report.excluded)} violation(s) in excluded paths")
    if report.exempted:
        notes.append(f"exemptions: {len(report.exempted)} violation(s) exempted")
    for ex in report.expired_exemptions:
        notes.append(
            f"exemptions: expired on {ex.until.isoformat()}, its violations are "
            f"reported again: {ex.describe()}"
        )
    for ex in report.unused_exemptions:
        notes.append(f"exemptions: matched nothing, consider removing it: {ex.describe()}")
    b = report.baseline
    if b is not None:
        notes.append(f"baseline: {len(b.suppressed)} known violation(s) suppressed")
        for (rule, path, obj), was, now in b.fixed:
            where = f"{path} [{obj}]" if obj else path
            notes.append(
                f"baseline: fixed {rule} {where} ({was} -> {now}); run "
                f"'tmdl-preflight baseline --update' to shrink the baseline"
            )
        for (rule, path, obj), why in b.stale:
            notes.append(f"baseline: stale entry {rule} {path} [{obj}]: {why}")
    return notes


# ---------------------------------------------------------------------------
# github (workflow commands)
# ---------------------------------------------------------------------------


def _gh_escape_data(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _gh_escape_prop(s: str) -> str:
    return _gh_escape_data(s).replace(":", "%3A").replace(",", "%2C")


_GH_LEVEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "notice"}


def render_github(report: PreflightReport, root: Path, ruleset: RuleSet) -> str:
    names = {r.id: r.name for r in ruleset.rules}
    out: list[str] = []
    for v in _sorted(report.violations):
        props = []
        if v.file is not None:
            props.append(f"file={_gh_escape_prop(_cwd_relative(v.file))}")
            if v.line:
                props.append(f"line={v.line}")
        props.append(f"title={_gh_escape_prop(v.rule_id + ' ' + names.get(v.rule_id, ''))}")
        message = v.message + (f" [{v.obj}]" if v.obj else "")
        out.append(f"::{_GH_LEVEL[v.severity]} {','.join(props)}::{_gh_escape_data(message)}")
    e, w, i = len(report.errors), len(report.warnings), len(report.infos)
    out.append(f"tmdl-preflight: {e} error(s), {w} warning(s), {i} info(s)")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# sarif 2.1.0
# ---------------------------------------------------------------------------

_SARIF_LEVEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "note"}
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://tmdl-preflight-documentation.readthedocs.io/en/latest/"


def render_sarif(report: PreflightReport, root: Path, ruleset: RuleSet) -> str:
    rules = []
    index: dict[str, int] = {}
    for r in ruleset.rules:
        index[r.id] = len(rules)
        rules.append(
            {
                "id": r.id,
                "name": r.name,
                "shortDescription": {"text": r.name},
                "fullDescription": {"text": r.description},
                "defaultConfiguration": {"level": _SARIF_LEVEL[r.severity]},
                "helpUri": INFORMATION_URI,
            }
        )
    results = []
    for v in _sorted(report.violations):
        result: dict = {
            "ruleId": v.rule_id,
            "level": _SARIF_LEVEL[v.severity],
            "message": {"text": v.message + (f" [{v.obj}]" if v.obj else "")},
        }
        if v.rule_id in index:
            result["ruleIndex"] = index[v.rule_id]
        if v.file is not None:
            location: dict = {"artifactLocation": {"uri": _cwd_relative(v.file)}}
            if v.line:
                location["region"] = {"startLine": v.line}
            result["locations"] = [{"physicalLocation": location}]
        if v.path:
            result["partialFingerprints"] = {
                "tmdlPreflightIdentity/v1": "|".join(v.identity())
            }
        results.append(result)
    payload = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "tmdl-preflight",
                        "version": __version__,
                        "informationUri": INFORMATION_URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------


def _md(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: PreflightReport, root: Path) -> str:
    e, w, i = len(report.errors), len(report.warnings), len(report.infos)
    out = [
        "## tmdl-preflight",
        "",
        f"**{e} error(s), {w} warning(s), {i} info(s)**"
        + (f", {len(report.fixes_applied)} fix(es) applied" if report.fixes_applied else ""),
        "",
    ]
    if report.scanned:
        out.extend([scanned_line(report.scanned).capitalize(), ""])
    if report.violations:
        out.append("| Severity | Rule | Location | Object | Message |")
        out.append("|---|---|---|---|---|")
        for v in _sorted(report.violations):
            loc = _display_path(v.file, root).replace(os.sep, "/")
            if loc and v.line:
                loc += f":{v.line}"
            out.append(
                f"| {_SEVERITY_TAG[v.severity]} | {v.rule_id} | `{_md(loc)}` | "
                f"{_md(v.obj or '')} | {_md(v.message)} |"
            )
        out.append("")
    for note in _notes(report):
        out.append(f"- {_md(note)}")
    return "\n".join(out).rstrip() + "\n"


def render(fmt: str, report: PreflightReport, root: Path, ruleset: RuleSet) -> str:
    if fmt == "json":
        return report.to_json()
    if fmt == "github":
        return render_github(report, root, ruleset)
    if fmt == "sarif":
        return render_sarif(report, root, ruleset)
    if fmt == "markdown":
        return render_markdown(report, root)
    return render_text(report, root)
