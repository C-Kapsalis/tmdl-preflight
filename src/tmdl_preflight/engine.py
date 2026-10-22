"""The check -> fix -> re-check engine.

tmdl-preflight preserves the "imposition pattern" its checks grew out of:
a fix is not a separate manual chore, it is part of the test. In ``fix``
mode the engine

1. runs every selected rule's ``check()``,
2. for each fixable rule that reported violations, runs its ``fix()``,
3. reloads the model from disk (fixers rewrite files, never in-memory
   objects), and
4. runs every ``check()`` again.

The run only counts as clean if the *re-check* is clean. A fixer that did
not actually resolve its violation class leaves the violation on the
report: auto-repair never gets to vouch for itself.

``apply_policy`` then applies a project configuration (severity overrides,
excluded paths, exemptions) to a report; baselines are applied by
``baseline.apply_baseline``. Both only ever remove or re-grade violations
the rules actually found; neither can add one.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .rules.base import Context, RuleSet, Severity, Violation


def scan_summary(ctx: Context) -> dict[str, int]:
    """How much of the project a run actually looked at."""
    models = ctx.models
    tables = [t for m in models for t in m.table_list]
    bookmarks = pages = visuals = 0
    for report_dir in ctx.report_dirs:
        bookmarks += sum(1 for _ in report_dir.rglob("*.bookmark.json"))
        pages += sum(1 for _ in report_dir.rglob("page.json"))
        visuals += sum(1 for _ in report_dir.rglob("visual.json"))
    bookmarks += len(ctx.bookmark_targets)
    return {
        "files": ctx.files_scanned(),
        "models": len(models),
        "tables": len(tables),
        "columns": sum(len(t.column_list) for t in tables),
        "measures": sum(len(t.measure_list) for t in tables),
        "relationships": sum(
            len(m.relationships) + len(m.malformed_relationships) for m in models
        ),
        "dax_blocks": sum(sum(1 for _ in m.dax_blocks()) for m in models),
        "calculation_groups": sum(1 for t in tables if t.is_calculation_group),
        "expressions": sum(len(m.expressions) for m in models),
        "tmdl_files": sum(len(m.tmdl_files) for m in models),
        "reports": len(ctx.report_dirs),
        "pages": pages,
        "visuals": visuals,
        "bookmarks": bookmarks,
    }


@dataclass
class PreflightReport:
    violations: list[Violation] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)
    fixed_rule_ids: list[str] = field(default_factory=list)
    scanned: dict[str, int] = field(default_factory=dict)
    # filled by apply_policy / the baseline step; empty for a plain run
    excluded: list[Violation] = field(default_factory=list)
    exempted: list[Violation] = field(default_factory=list)
    expired_exemptions: list[Any] = field(default_factory=list)
    unused_exemptions: list[Any] = field(default_factory=list)
    baseline: Optional[Any] = None  # baseline.BaselineResult
    # files skipped before parsing because an exclude glob matched them all
    excluded_files: int = 0
    # fixable rules whose (unsafe) fixer a blanket fix did not run
    skipped_fixers: list[str] = field(default_factory=list)
    # rules disabled by a policy toggle; they ran no check at all
    skipped: list[str] = field(default_factory=list)
    # why each skipped rule did not run
    skip_reasons: dict[str, str] = field(default_factory=dict)
    # fix --dry-run: what a real fix would repair, per rule
    would_fix: list[str] = field(default_factory=list)
    # free-text notes from the rules (for example ratchet tighten hints)
    notes: list[str] = field(default_factory=list)
    # multi-line closing advice from the fixers, printed after the summary
    blocks: list[str] = field(default_factory=list)
    # repairs a fixer refused because it could not prove them (exit 2)
    refused_fixes: list[str] = field(default_factory=list)
    # the violations the first pass found, before any fixer ran; the console
    # reports of the rules that repair files describe those, not the clean
    # re-check
    found: list[Violation] = field(default_factory=list)
    # the console report of a rule that came from a script with a report of
    # its own, rendered before the repair so it can describe what was there
    console: list[str] = field(default_factory=list)
    # lines the fixers printed while they worked
    fix_notes: list[str] = field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[Violation]:
        return [v for v in self.violations if v.severity == severity]

    @property
    def errors(self) -> list[Violation]:
        return self.by_severity(Severity.ERROR)

    @property
    def warnings(self) -> list[Violation]:
        return self.by_severity(Severity.WARNING)

    @property
    def infos(self) -> list[Violation]:
        return self.by_severity(Severity.INFO)

    def exit_code(self, strict: bool = False) -> int:
        if self.refused_fixes:
            return 2
        if self.errors:
            return 1
        if strict and self.warnings:
            return 1
        return 0

    def to_dict(self) -> dict:
        payload: dict[str, Any] = {
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "infos": len(self.infos),
                "fixes_applied": len(self.fixes_applied),
                "excluded": len(self.excluded) + self.excluded_files,
                "excluded_files": self.excluded_files,
                "files_scanned": self.scanned.get("files", 0),
                "exempted": len(self.exempted),
                "baselined": len(self.baseline.suppressed) if self.baseline else 0,
            },
            "fixes": self.fixes_applied,
            "skipped": self.skipped,
            "skip_reasons": self.skip_reasons,
            "skipped_fixers": self.skipped_fixers,
            "would_fix": self.would_fix,
            "refused_fixes": self.refused_fixes,
            "notes": self.notes,
            "fix_notes": self.fix_notes,
            "blocks": self.blocks,
            "violations": [v.to_dict() for v in self.violations],
            "scanned": self.scanned,
        }
        if self.exempted or self.expired_exemptions or self.unused_exemptions:
            payload["exemptions"] = {
                "applied": len(self.exempted),
                "expired": [e.to_dict() for e in self.expired_exemptions],
                "unused": [e.to_dict() for e in self.unused_exemptions],
            }
        if self.baseline is not None:
            payload["baseline"] = self.baseline.to_dict()
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def check(ctx: Context, ruleset: RuleSet) -> PreflightReport:
    """Pure-read pass: run every rule, collect violations, mutate nothing."""
    report = PreflightReport()
    ctx.notes = []
    ctx.skips = []
    for rule in ruleset.rules:
        if rule.disabled_by_policy():
            report.skipped.append(rule.name)
            report.skip_reasons[rule.name] = rule.skip_reason()
            continue
        report.violations.extend(rule.check(ctx))
    report.skipped.extend(ctx.skips)
    report.scanned = scan_summary(ctx)
    report.notes = list(dict.fromkeys(ctx.notes))
    report.blocks = list(ctx.blocks)
    return report


def fix(ctx: Context, ruleset: RuleSet, explicit: Optional[set[str]] = None) -> PreflightReport:
    """Imposition pass: check, repair what is repairable, then re-check.

    The returned report carries the *post-fix* violations plus a log of
    every applied fix. Violations of fixable rules that survive the re-check
    mean the fixer could not (safely) resolve them; they require a human.
    """
    first = check(ctx, ruleset)
    report = PreflightReport()
    report.found = list(first.violations)
    ctx.refused_fixes = []
    ctx.fix_notes = []

    dirty_rule_ids = {v.rule_id for v in first.violations}
    chosen = {e.lower() for e in (explicit or set())}
    notes_before = len(ctx.notes)
    for rule in ruleset.rules:
        if not rule.fixable or (rule.id not in dirty_rule_ids and not rule.pending_repairs(ctx)):
            continue
        if not rule.safe and not ({rule.id.lower(), rule.name.lower()} & chosen) \
                and not rule.unsafe_fix_enabled():
            # name the skipped fixer only when this run reported findings it
            # repairs; a fixer that runs whenever it is selected (R007) has
            # nothing to skip on a model without them
            if dirty_rule_ids & rule.repaired_rule_ids():
                report.skipped_fixers.append(rule.id)
            continue
        applied = rule.fix(ctx)
        if applied:
            report.fixes_applied.extend(f"{rule.id}: {a}" for a in applied)
            report.fixed_rule_ids.append(rule.id)
        # Fixers rewrite files; later fixers and the re-check must see the
        # new state, not the parse cache.
        ctx.reload()

    # what a fixer had to say survives the re-check, which starts with an
    # empty note list
    fixer_notes = list(ctx.notes[notes_before:])
    report.fix_notes = list(ctx.fix_notes)
    second = check(ctx, ruleset)
    report.refused_fixes = list(ctx.refused_fixes)
    report.violations = second.violations
    report.scanned = second.scanned
    report.notes = list(dict.fromkeys(ctx.fix_notes + fixer_notes + second.notes))
    report.skipped = second.skipped
    report.skip_reasons = second.skip_reasons
    report.blocks = list(ctx.blocks)
    return report


def apply_policy(report: PreflightReport, config, today: Optional[_dt.date] = None,
                 ctx: Optional[Context] = None) -> PreflightReport:
    """Apply a ``config.Config`` to a report, in place.

    Order: severity overrides, then path excludes, then exemptions. An
    exemption past its ``until`` date no longer applies, so its violation
    is reported again and the exemption is listed as expired.
    """
    from .config import glob_match  # local import: config imports rules

    today = today or _dt.date.today()
    for v in report.violations:
        override = config.severity_overrides.get(v.rule_id)
        if override is not None:
            v.severity = override
    if ctx is not None:
        report.excluded_files = ctx.excluded_files
    if config.exclude:
        kept = []
        for v in report.violations:
            scan_rel = ctx.scan_relative(v.file) if (ctx is not None and v.file) else None
            paths = [p for p in (v.path, scan_rel) if p]
            if any(glob_match(p, path) for p in config.exclude for path in paths):
                report.excluded.append(v)
            else:
                kept.append(v)
        report.violations = kept
    active = []
    for ex in config.exemptions:
        if ex.expired(today):
            report.expired_exemptions.append(ex)
        else:
            active.append(ex)
    used: set[int] = set()
    kept = []
    for v in report.violations:
        match = next((ex for ex in active if ex.matches(v)), None)
        if match is None:
            kept.append(v)
        else:
            used.add(id(match))
            report.exempted.append(v)
    report.violations = kept
    report.unused_exemptions = [ex for ex in active if id(ex) not in used]
    return report
