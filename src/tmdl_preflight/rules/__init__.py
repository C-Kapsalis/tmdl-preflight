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
from .dax_patterns import (
    CalcDaxBlocksPresentRule,
    CalcItemBlindAverageRule,
    CrossFactMultirowKeyJoinRule,
)
from .field_parameters import (
    FieldParameterCategoryColumnRule,
    MissingRowSeparatorRule,
    TrailingRowCommaRule,
)
from .fp_rows import (
    FieldParameterCommaRunsRule,
    FieldParameterDuplicateRowsRule,
    FieldParameterFamilyConsistencyRule,
    RaggedRowWidthRule,
)
from .fp_axes import (
    CalculatedColumnExpressionRule,
    FieldParameterArityRule,
    FieldParameterCategoryRequiredRule,
    FieldParameterCoverageRule,
    FieldParameterLevelConsistencyRule,
    FieldParameterNoMeasuresRule,
    FieldParameterPartitionShapeRule,
    FieldParameterRetagRule,
    SelectorBranchResolutionRule,
)
from .mapping import (
    CategoryGateCoverageRule,
    FMeasurePatternRule,
    MappingCategoryRequiredKeysRule,
    MappingTableInfoReportsRule,
    MappingTableRequiredColumnsRule,
)
from .refresh_policy import RefreshPolicyCoverageRule, RefreshPolicyRepairRule
from .rls import (
    InValuesBypassRule,
    MappingTableHiddenRule,
    MappingTableNoRelationshipRule,
    RlsInventoryRule,
    RoleGrammarRule,
    UsernameFunctionRule,
)
from .cultures import CultureOrphanBindingsRule
from .measure_hygiene import (
    FactTableFilterCoverageRule,
    HelperMeasuresHiddenRule,
    IntermediaryHelperFolderRule,
    RequiredCalcGroupsRule,
    TableDescriptionCoverageRule,
    UnusedHelperMeasuresRule,
    UserFacingDisplayFolderRule,
    UserFacingMeasureDescriptionRule,
    UserFacingMeasureVisibleRule,
)
from .comments import CommentTicketRefsRule
from .contract_patterns import (
    GuardedRatioWrapperRule,
    MeasureArmScopedFilterRule,
    MeasureReferenceContractRule,
    TypedFlagPredicatesRule,
)
from .contracts import (
    FieldParamRegistrationContractRule,
    ModelContractObjectsRule,
    ModelContractRelationshipsRule,
    RequiredModelObjectsRule,
)
from .formats import FormatMinDecimalsRule
from .grain import (
    DaxOrChainDepthRule,
    GrainGuardCoverageRule,
    GrainPolicyExceptionRule,
    ReachGuardHelperConsistencyRule,
)
from .hygiene import (
    DiagramLayoutBlankRule,
    ModelAnnotationDuplicatesRule,
    SpaceIndentationRule,
    UndefinedQueryGroupRule,
)
from .organization import (
    DimensionPrefixFloorRule,
    DeadFactTablesRule,
    EmptyMeasureTablesRule,
    FormatInferenceNamingRule,
    HelperMeasurePlacementRule,
    MeasuresInDimensionTablesRule,
    MeasuresInFactTablesRule,
    UserFacingInHelperTablesRule,
    UserOnlyTablePurityRule,
)
from .relationships import (
    AmbiguousActivePairRule,
    AutodetectedRelationshipsRule,
    BidirectionalFilterRule,
    DuplicateRelationshipsRule,
    FactConformedDimensionJoinRule,
    OrphanTablesRule,
    RelationshipCardinalityRule,
    RelationshipEndpointsRule,
)
from .report import (
    BookmarkIntegerTypesRule,
    BookmarkOptionsSchemaRule,
    BookmarkVisualRefsRule,
    HierarchyLevelBindingShapeRule,
    PagesMetadataSchemaRule,
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
from .topology import (
    CalendarRelationshipCardinalityRule,
    CalendarStandardColumnsRule,
    CohortCalendarReachRule,
    DeadAnchorCalendarRule,
    DimensionKeyColumnsRule,
    FactCalendarCoverageRule,
    RelationshipCyclesRule,
    RelationshipsPresenceRule,
)
from .validation_notes import ModelValidationNotesRule

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
    CalculatedColumnExpressionRule,
    RefreshPolicyRepairRule,
    RefreshPolicyCoverageRule,
    CultureOrphanBindingsRule,
    DiagramLayoutBlankRule,
    DaxDelimiterBalanceRule,
    NameofResolutionRule,
    DuplicateMeasureNamesRule,
    DaxReferenceResolutionRule,
    DuplicateVariableRule,
    CalcDaxBlocksPresentRule,
    CalcItemBlindAverageRule,
    CrossFactMultirowKeyJoinRule,
    DaxOrChainDepthRule,
    RelationshipEndpointsRule,
    RelationshipCardinalityRule,
    DuplicateRelationshipsRule,
    BidirectionalFilterRule,
    OrphanTablesRule,
    AmbiguousActivePairRule,
    AutodetectedRelationshipsRule,
    FactConformedDimensionJoinRule,
    RelationshipsPresenceRule,
    RelationshipCyclesRule,
    FactCalendarCoverageRule,
    CalendarRelationshipCardinalityRule,
    CalendarStandardColumnsRule,
    DimensionKeyColumnsRule,
    CohortCalendarReachRule,
    DeadAnchorCalendarRule,
    FieldParameterCommaRunsRule,
    MissingRowSeparatorRule,
    TrailingRowCommaRule,
    RaggedRowWidthRule,
    FieldParameterCategoryColumnRule,
    FieldParameterDuplicateRowsRule,
    FieldParameterFamilyConsistencyRule,
    FieldParameterArityRule,
    FieldParameterLevelConsistencyRule,
    FieldParameterRetagRule,
    FieldParameterCategoryRequiredRule,
    FieldParameterCoverageRule,
    FieldParameterNoMeasuresRule,
    SelectorBranchResolutionRule,
    FieldParameterPartitionShapeRule,
    MappingTableRequiredColumnsRule,
    MappingTableInfoReportsRule,
    MappingCategoryRequiredKeysRule,
    CategoryGateCoverageRule,
    FMeasurePatternRule,
    RoleGrammarRule,
    UsernameFunctionRule,
    InValuesBypassRule,
    MappingTableHiddenRule,
    MappingTableNoRelationshipRule,
    RlsInventoryRule,
    BookmarkIntegerTypesRule,
    BookmarkVisualRefsRule,
    BookmarkOptionsSchemaRule,
    ReportDefinitionIntegrityRule,
    PagesMetadataSchemaRule,
    HierarchyLevelBindingShapeRule,
    FormatStringPresenceRule,
    MeasureDescriptionRule,
    FormatInferenceNamingRule,
    CommentTicketRefsRule,
    UserOnlyTablePurityRule,
    HelperMeasurePlacementRule,
    UserFacingInHelperTablesRule,
    MeasuresInFactTablesRule,
    MeasuresInDimensionTablesRule,
    EmptyMeasureTablesRule,
    DeadFactTablesRule,
    DimensionPrefixFloorRule,
    IntermediaryHelperFolderRule,
    HelperMeasuresHiddenRule,
    UnusedHelperMeasuresRule,
    UserFacingMeasureVisibleRule,
    UserFacingDisplayFolderRule,
    UserFacingMeasureDescriptionRule,
    TableDescriptionCoverageRule,
    FactTableFilterCoverageRule,
    RequiredModelObjectsRule,
    ModelContractObjectsRule,
    ModelContractRelationshipsRule,
    FieldParamRegistrationContractRule,
    MeasureReferenceContractRule,
    GuardedRatioWrapperRule,
    TypedFlagPredicatesRule,
    MeasureArmScopedFilterRule,
    ReachGuardHelperConsistencyRule,
    GrainGuardCoverageRule,
    GrainPolicyExceptionRule,
    RequiredCalcGroupsRule,
    FormatMinDecimalsRule,
    ModelValidationNotesRule,
]


def full_ruleset() -> RuleSet:
    """Every registered rule, opt-in ones included (the catalog)."""
    return RuleSet([cls() for cls in ALL_RULES])


def default_ruleset() -> RuleSet:
    """The rules a plain run executes: every rule except the opt-in ones."""
    return RuleSet([cls() for cls in ALL_RULES if not cls.opt_in])


__all__ = [
    "ALL_RULES",
    "Context",
    "Rule",
    "RuleSet",
    "Severity",
    "Violation",
    "default_ruleset",
    "full_ruleset",
]
