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
report — auto-repair never gets to vouch for itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules.base import Context, RuleSet, Severity, Violation


@dataclass
class PreflightReport:
    violations: list[Violation] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)
    fixed_rule_ids: list[str] = field(default_factory=list)

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
        if self.errors:
            return 1
        if strict and self.warnings:
            return 1
        return 0

    def to_dict(self) -> dict:
        return {
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "infos": len(self.infos),
                "fixes_applied": len(self.fixes_applied),
            },
            "fixes": self.fixes_applied,
            "violations": [v.to_dict() for v in self.violations],
        }


def check(ctx: Context, ruleset: RuleSet) -> PreflightReport:
    """Pure-read pass: run every rule, collect violations, mutate nothing."""
    report = PreflightReport()
    for rule in ruleset.rules:
        report.violations.extend(rule.check(ctx))
    return report


def fix(ctx: Context, ruleset: RuleSet) -> PreflightReport:
    """Imposition pass: check, repair what is repairable, then re-check.

    The returned report carries the *post-fix* violations plus a log of
    every applied fix. Violations of fixable rules that survive the re-check
    mean the fixer could not (safely) resolve them — they require a human.
    """
    first = check(ctx, ruleset)
    report = PreflightReport()

    dirty_rule_ids = {v.rule_id for v in first.violations}
    for rule in ruleset.rules:
        if not rule.fixable or rule.id not in dirty_rule_ids:
            continue
        applied = rule.fix(ctx)
        if applied:
            report.fixes_applied.extend(f"{rule.id}: {a}" for a in applied)
            report.fixed_rule_ids.append(rule.id)
        # Fixers rewrite files; later fixers and the re-check must see the
        # new state, not the parse cache.
        ctx.reload()

    second = check(ctx, ruleset)
    report.violations = second.violations
    return report
