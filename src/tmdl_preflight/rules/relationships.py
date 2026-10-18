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
        "must be declared, and the referenced columns must exist on them "
        "(names compare case-insensitively). A relationship whose fromColumn "
        "or toColumn is missing or unreadable is reported too, never dropped."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for rel in model.malformed_relationships:
                missing = [
                    side
                    for side, table, column in (
                        ("fromColumn", rel.from_table, rel.from_column),
                        ("toColumn", rel.to_table, rel.to_column),
                    )
                    if not (table and column)
                ]
                out.append(
                    self.violation(
                        f"relationship has no usable {' or '.join(missing)} "
                        f"(expected 'Table.Column' or 'Table'.'Column'), so it "
                        f"cannot deploy. Restore the missing endpoint line or "
                        f"delete the relationship.",
                        file=rel.file,
                        line=rel.line,
                        obj=f"relationship {rel.rel_id[:8]}",
                    )
                )
            for rel in model.relationships:
                for side, table, column in (
                    ("from", rel.from_table, rel.from_column),
                    ("to", rel.to_table, rel.to_column),
                ):
                    t = model.find_table(table)
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
                    elif t.find_column(column) is None:
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
        "'many'; anything else is not a cardinality the engine accepts."
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


class AmbiguousActivePairRule(Rule):
    id = "R006"
    name = "ambiguous-active-pair"
    severity = Severity.ERROR
    baselinable = False
    description = (
        "At most one relationship between the same two tables may be active. "
        "A second active relationship makes the filter path ambiguous and the "
        "engine refuses to load the model. Mark all but one as "
        "'isActive: false' and use USERELATIONSHIP() where the other path is "
        "needed."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            seen: dict[frozenset, object] = {}
            for rel in model.relationships:
                if not rel.is_active:
                    continue
                key = frozenset((rel.from_table.lower(), rel.to_table.lower()))
                if key in seen:
                    first = seen[key]
                    out.append(
                        self.violation(
                            f"second active relationship between "
                            f"'{rel.from_table}' and '{rel.to_table}' (the "
                            f"first is {first.rel_id[:8]} on line {first.line}). "
                            f"Two active paths between the same tables are "
                            f"ambiguous and the model cannot load; set "
                            f"'isActive: false' on one of them.",
                            file=rel.file,
                            line=rel.line,
                            obj=f"relationship {rel.rel_id[:8]}",
                        )
                    )
                else:
                    seen[key] = rel
        return out


class AutodetectedRelationshipsRule(Rule):
    id = "R007"
    name = "autodetected-relationships"
    severity = Severity.WARNING
    description = (
        "Relationships whose id starts with 'AutoDetected_' were created by "
        "Power BI Desktop's relationship autodetection, not by a modeler. "
        "They often join on columns that merely share a name. Review each "
        "one; keep it (Desktop then keeps the id, so ignore this rule or "
        "baseline it) or delete it and turn autodetection off."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for rel in model.relationships + model.malformed_relationships:
                if rel.rel_id.startswith("AutoDetected_"):
                    out.append(
                        self.violation(
                            f"relationship {rel.from_table}[{rel.from_column}] "
                            f"-> {rel.to_table}[{rel.to_column}] was "
                            f"autodetected by Power BI Desktop. Confirm it "
                            f"joins the right columns, or delete it.",
                            file=rel.file,
                            line=rel.line,
                            obj=f"relationship {rel.rel_id}",
                        )
                    )
        return out


class FactConformedDimensionJoinRule(Rule):
    id = "R008"
    name = "fact-conformed-dimension-join"
    severity = Severity.ERROR
    option_defaults = {
        "dimension_table": None,
        "key_column": None,
        "exempt": {},
        "baseline": None,
        "fail_without_baseline_entry": False,
    }
    description = (
        "Every fact table must actively join a conformed dimension (configure "
        "dimension_table and key_column, for example an accounts table and "
        "its key): an ACTIVE relationship from the fact to "
        "dimension_table[key_column], whatever the fact's column is called. "
        "Without it a filter on that dimension silently returns unfiltered "
        "data. Offenders are classified 'missing relationship' (the fact has "
        "the key column) or 'missing key column'. 'exempt' maps tables to a "
        "mandatory reason; 'baseline' ratchets existing offenders per model. "
        "Facts follow the shared table-role law. Inert until configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        from ..ratchet import RatchetFileError, entry_for, load_floors
        from ..roles import fact_tables

        dim = self.options.get("dimension_table")
        key = self.options.get("key_column")
        if not dim or not key:
            return []
        exempt = self.options.get("exempt") or {}
        out: list[Violation] = []
        floors = None
        if self.options.get("baseline"):
            try:
                floors = load_floors(self.options["baseline"], missing_ok=True)
            except RatchetFileError as exc:
                return [self.violation(str(exc))]
        for model in ctx.models:
            mkey = ctx.model_key(model)
            accepted: set[str] = set()
            if floors is not None:
                found, value = entry_for(floors, mkey)
                if not found and self.options.get("fail_without_baseline_entry"):
                    out.append(self.violation(
                        f"model {mkey} has no entry in the baseline; record its accepted "
                        f"offenders deliberately (an empty list means none).",
                        file=model.definition_path / "relationships.tmdl", obj=mkey,
                    ))
                accepted = set(value or [])
            flagged = []
            for name in fact_tables(model):
                if name in exempt:
                    continue
                joined = any(
                    r.is_active and r.from_table == name and r.to_table == dim and r.to_column == key
                    for r in model.relationships
                )
                if joined:
                    continue
                t = model.tables[name]
                flagged.append(name)
                if name in accepted:
                    continue
                cls = "missing relationship" if t.find_column(key) else "missing key column"
                out.append(self.violation(
                    f"fact table {name} has no active relationship to {dim}[{key}] "
                    f"({cls}), so filtering by {dim} returns unfiltered data. Create "
                    f"the active relationship" + (" (adding the key column first)." if
                                                  cls == "missing key column" else "."),
                    file=t.file, line=t.line, obj=name,
                ))
            for name in sorted(accepted - set(flagged)):
                ctx.notes.append(
                    f"fact-conformed-dimension-join: {mkey}: {name} is in the baseline but "
                    f"now joins {dim}; tighten the baseline by removing it."
                )
        return out
