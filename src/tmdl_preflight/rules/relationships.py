"""Relationship rules: endpoint integrity, cardinality, duplicates,
bidirectional filters, orphan tables. IDs R0xx."""

from __future__ import annotations

from .base import Context, Rule, Severity, Violation

VALID_CARDINALITIES = {"one", "many"}


class RelationshipEndpointsRule(Rule):
    id = "R001"
    name = "relationship-endpoints"
    severity = Severity.ERROR
    description = (
        "Both endpoints of every relationship must exist: the from/to tables "
        "must be declared, and the referenced columns must exist on them."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for rel in model.relationships:
                for side, table, column in (
                    ("from", rel.from_table, rel.from_column),
                    ("to", rel.to_table, rel.to_column),
                ):
                    t = model.get_table(table)
                    if t is None:
                        out.append(
                            self.violation(
                                f"{side}-table '{table}' does not exist in the "
                                f"model, so this relationship cannot deploy. The "
                                f"table was probably renamed or removed; update "
                                f"the relationship or restore the table.",
                                file=rel.file,
                                line=rel.line,
                                obj=f"relationship {rel.rel_id[:8]}",
                            )
                        )
                    elif column not in t.columns:
                        out.append(
                            self.violation(
                                f"{side}-column '{table}'[{column}] does not "
                                f"exist, so this relationship cannot deploy. The "
                                f"column was probably renamed or removed; update "
                                f"the relationship or restore the column.",
                                file=rel.file,
                                line=rel.line,
                                obj=f"relationship {rel.rel_id[:8]}",
                            )
                        )
        return out


class RelationshipCardinalityRule(Rule):
    id = "R002"
    name = "relationship-cardinality"
    severity = Severity.ERROR
    description = (
        "Declared fromCardinality/toCardinality values must be 'one' or "
        "'many' — anything else is not a cardinality the engine accepts."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for rel in model.relationships:
                for side, value in (
                    ("fromCardinality", rel.from_cardinality),
                    ("toCardinality", rel.to_cardinality),
                ):
                    if value not in VALID_CARDINALITIES:
                        out.append(
                            self.violation(
                                f"{side} is '{value}', which is not a "
                                f"cardinality the tabular engine accepts. "
                                f"Change it to 'one' or 'many'.",
                                file=rel.file,
                                line=rel.line,
                                obj=f"relationship {rel.rel_id[:8]}",
                            )
                        )
        return out


class DuplicateRelationshipsRule(Rule):
    id = "R003"
    name = "relationship-duplicates"
    severity = Severity.WARNING
    description = (
        "Two relationships over the same column pair almost always mean a "
        "copy/paste or merge accident. Relationships are keyed on their "
        "endpoints (not their GUIDs) so re-saved models compare cleanly."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            seen: dict[tuple, object] = {}
            for rel in model.relationships:
                key = rel.endpoints
                if key in seen:
                    first = seen[key]
                    out.append(
                        self.violation(
                            f"duplicate of relationship {first.rel_id[:8]}: both "
                            f"connect {rel.from_table}[{rel.from_column}] -> "
                            f"{rel.to_table}[{rel.to_column}]. Duplicates "
                            f"usually come from a copy/paste or merge accident; "
                            f"delete one of the two.",
                            file=rel.file,
                            line=rel.line,
                            obj=f"relationship {rel.rel_id[:8]}",
                        )
                    )
                else:
                    seen[key] = rel
        return out


class BidirectionalFilterRule(Rule):
    id = "R004"
    name = "relationship-bidirectional"
    severity = Severity.INFO
    description = (
        "Bidirectional cross-filtering is sometimes necessary but often a "
        "performance and correctness hazard (ambiguous filter paths). Each "
        "occurrence is surfaced so the modeler confirms it is intentional."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for rel in model.relationships:
                if rel.cross_filtering.lower() == "bothdirections":
                    out.append(
                        self.violation(
                            f"cross-filters in both directions between "
                            f"{rel.from_table}[{rel.from_column}] and "
                            f"{rel.to_table}[{rel.to_column}]. Bidirectional "
                            f"filters can create ambiguous filter paths and "
                            f"slow queries; confirm this one is intentional.",
                            file=rel.file,
                            line=rel.line,
                            obj=f"relationship {rel.rel_id[:8]}",
                        )
                    )
        return out


class OrphanTablesRule(Rule):
    id = "R005"
    name = "orphan-tables"
    severity = Severity.INFO
    description = (
        "Data tables that participate in no relationship are usually load "
        "leftovers. Tables that are unrelated by design are exempt: "
        "measure-only tables, tables whose columns are all hidden (the "
        "measure-home pattern), hidden tables, calculated helper tables and "
        "field parameters."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            related: set[str] = set()
            for rel in model.relationships:
                related.add(rel.from_table)
                related.add(rel.to_table)
            for table in model.tables.values():
                if table.name in related:
                    continue
                if not table.columns:
                    continue  # measure-only table
                if table.is_hidden:
                    continue  # hidden helper table, unrelated by design
                if all(c.is_hidden for c in table.columns.values()):
                    continue  # measure-home table (only hidden placeholder columns)
                if table.is_field_parameter:
                    continue
                if all(c.is_calculated for c in table.columns.values()):
                    continue  # calculated helper table
                if any(p.kind == "calculated" for p in table.partitions):
                    continue  # calculated table (parameter/what-if style)
                out.append(
                    self.violation(
                        f"table '{table.name}' has visible data columns but no "
                        f"relationships. If it is a deliberate disconnected "
                        f"table (for example a slicer or selector table), no "
                        f"action is needed; if it is a load leftover, remove it.",
                        file=table.file,
                        line=table.line,
                        obj=table.name,
                    )
                )
        return out
