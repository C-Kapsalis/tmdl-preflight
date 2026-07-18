"""Rule registry."""

from __future__ import annotations

from .base import Context, Rule, RuleSet, Severity, Violation
from .dax_rules import (
    DaxDelimiterBalanceRule,
    DuplicateMeasureNamesRule,
    NameofResolutionRule,
)
from .field_parameters import FieldParameterCommaRunsRule
from .relationships import (
    BidirectionalFilterRule,
    DuplicateRelationshipsRule,
    OrphanTablesRule,
    RelationshipCardinalityRule,
    RelationshipEndpointsRule,
)
from .report import BookmarkIntegerTypesRule, BookmarkVisualRefsRule
from .structural import (
    ColumnDataTypeRule,
    LineageTagFormatRule,
    LineageTagUniquenessRule,
    ModelStructureRule,
    TmdlWellFormedRule,
)
from .style import FormatStringPresenceRule

ALL_RULES: list[type[Rule]] = [
    ModelStructureRule,
    TmdlWellFormedRule,
    LineageTagUniquenessRule,
    LineageTagFormatRule,
    ColumnDataTypeRule,
    DaxDelimiterBalanceRule,
    NameofResolutionRule,
    DuplicateMeasureNamesRule,
    RelationshipEndpointsRule,
    RelationshipCardinalityRule,
    DuplicateRelationshipsRule,
    BidirectionalFilterRule,
    OrphanTablesRule,
    FieldParameterCommaRunsRule,
    BookmarkIntegerTypesRule,
    BookmarkVisualRefsRule,
    FormatStringPresenceRule,
]


def default_ruleset() -> RuleSet:
    return RuleSet([cls() for cls in ALL_RULES])


__all__ = [
    "ALL_RULES",
    "Context",
    "Rule",
    "RuleSet",
    "Severity",
    "Violation",
    "default_ruleset",
]
