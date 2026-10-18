"""Rule registry."""

from __future__ import annotations

from .base import Context, Rule, RuleSet, Severity, Violation
from .dax_rules import (
    DaxDelimiterBalanceRule,
    DaxReferenceResolutionRule,
    DuplicateMeasureNamesRule,
    DuplicateVariableRule,
    NameofResolutionRule,
)
from .field_parameters import (
    FieldParameterCommaRunsRule,
    MissingRowSeparatorRule,
    RaggedRowWidthRule,
    TrailingRowCommaRule,
)
from .hygiene import (
    ModelAnnotationDuplicatesRule,
    SpaceIndentationRule,
    UndefinedQueryGroupRule,
)
from .relationships import (
    AmbiguousActivePairRule,
    AutodetectedRelationshipsRule,
    BidirectionalFilterRule,
    DuplicateRelationshipsRule,
    OrphanTablesRule,
    RelationshipCardinalityRule,
    RelationshipEndpointsRule,
)
from .report import (
    BookmarkIntegerTypesRule,
    BookmarkOptionsSchemaRule,
    BookmarkVisualRefsRule,
    ReportDefinitionIntegrityRule,
)
from .structural import (
    CalcGroupImplicitMeasuresRule,
    ColumnDataTypeRule,
    DanglingDescriptionRule,
    DuplicateObjectNamesRule,
    EntityQuerySourceRule,
    LineageTagFormatRule,
    LineageTagUniquenessRule,
    MetadataInExpressionRule,
    ModelStructureRule,
    ModelTableReferencesRule,
    PropertyAfterChildBlockRule,
    RefTableTargetRule,
    ReservedTableNameRule,
    TablePartitionPresenceRule,
    TmdlFileSanityRule,
    TmdlWellFormedRule,
)
from .style import FormatStringPresenceRule, MeasureDescriptionRule

ALL_RULES: list[type[Rule]] = [
    ModelStructureRule,
    TmdlWellFormedRule,
    ModelTableReferencesRule,
    TablePartitionPresenceRule,
    EntityQuerySourceRule,
    ReservedTableNameRule,
    LineageTagUniquenessRule,
    LineageTagFormatRule,
    ColumnDataTypeRule,
    MetadataInExpressionRule,
    PropertyAfterChildBlockRule,
    DuplicateObjectNamesRule,
    DanglingDescriptionRule,
    CalcGroupImplicitMeasuresRule,
    RefTableTargetRule,
    TmdlFileSanityRule,
    SpaceIndentationRule,
    ModelAnnotationDuplicatesRule,
    UndefinedQueryGroupRule,
    DaxDelimiterBalanceRule,
    NameofResolutionRule,
    DuplicateMeasureNamesRule,
    DaxReferenceResolutionRule,
    DuplicateVariableRule,
    RelationshipEndpointsRule,
    RelationshipCardinalityRule,
    DuplicateRelationshipsRule,
    BidirectionalFilterRule,
    OrphanTablesRule,
    AmbiguousActivePairRule,
    AutodetectedRelationshipsRule,
    FieldParameterCommaRunsRule,
    MissingRowSeparatorRule,
    TrailingRowCommaRule,
    RaggedRowWidthRule,
    BookmarkIntegerTypesRule,
    BookmarkVisualRefsRule,
    BookmarkOptionsSchemaRule,
    ReportDefinitionIntegrityRule,
    FormatStringPresenceRule,
    MeasureDescriptionRule,
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
