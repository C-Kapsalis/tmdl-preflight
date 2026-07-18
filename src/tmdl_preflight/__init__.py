"""tmdl-preflight — preflight checks and auto-fixes for Power BI semantic
models saved in TMDL format (PBIP folders)."""

from __future__ import annotations

__version__ = "0.1.0"

from .engine import PreflightReport, check, fix
from .parser import parse_model
from .rules import ALL_RULES, default_ruleset
from .rules.base import Context, Rule, RuleSet, Severity, Violation

__all__ = [
    "ALL_RULES",
    "Context",
    "PreflightReport",
    "Rule",
    "RuleSet",
    "Severity",
    "Violation",
    "check",
    "default_ruleset",
    "fix",
    "parse_model",
    "__version__",
]
