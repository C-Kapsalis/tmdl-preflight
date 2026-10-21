"""Relationship rules: endpoint integrity, cardinality, duplicates,
bidirectional filters, orphan tables. IDs R0xx."""

from __future__ import annotations

from .base import Context, Rule, Severity, Violation

VALID_CARDINALITIES = {"one", "many"}


class RelationshipEndpointsRule(Rule):
    id = "R001"
    name = "relationship-endpoints"
    severity = Severity.ERROR
    option_defaults = {"min_endpoint_success_rate": 0.95}
    description = (
        "Both endpoints of every relationship must exist: the from/to tables "
        "must be declared, and the referenced columns must exist on them. "
        "Names resolve case-insensitively, as Power BI does, but an endpoint "
        "spelled with different casing from its declaration is reported as "
        "an error too. A relationship whose fromColumn or toColumn is missing "
        "or unreadable is reported, never dropped. When the share of "
        "relationships with valid endpoints falls under "
        "min_endpoint_success_rate (default 0.95) the report notes it; the "
        "broken endpoints are errors whatever the share."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        threshold = float(self.options.get("min_endpoint_success_rate", 0.95))
        for model in ctx.models:
            broken_ids: set[int] = set()
            for rel in model.malformed_relationships:
                broken_ids.add(id(rel))
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
                    obj = f"relationship {rel.rel_id[:8]}"
                    t = model.find_table(table)
                    if t is None:
                        broken_ids.add(id(rel))
                        out.append(self.violation(
                            f"{side}-table '{table}' does not exist in the model (table "
                            f"not found), so this relationship cannot deploy. The table "
                            f"was probably renamed or removed; update the relationship "
                            f"or restore the table.",
                            file=rel.file, line=rel.line, obj=obj,
                        ))
                        continue
                    col = t.find_column(column)
                    if col is None:
                        broken_ids.add(id(rel))
                        out.append(self.violation(
                            f"{side}-column '{table}'[{column}] does not exist (column "
                            f"not found), so this relationship cannot deploy. The column "
                            f"was probably renamed or removed; update the relationship "
                            f"or restore the column.",
                            file=rel.file, line=rel.line, obj=obj,
                        ))
                        continue
                    if t.name != table or col.name != column:
                        out.append(self.violation(
                            f"casing mismatch: the relationship names '{table}'[{column}], "
                            f"the column is declared '{t.name}'[{col.name}]. Use the "
                            f"declared spelling.",
                            file=rel.file, line=rel.line, obj=obj,
                        ))
            total = len(model.relationships) + len(model.malformed_relationships)
            if total:
                rate = (total - len(broken_ids)) / total
                if rate < threshold:
                    # every broken endpoint is already an error, so the rate is
                    # reported as a note and never adds a finding of its own
                    ctx.notes.append(
                        f"R001: {ctx.model_key(model)}: endpoint success rate {rate:.1%} is "
                        f"below the configured {threshold:.0%} ({len(broken_ids)} of {total} "
                        f"relationship(s) have a broken endpoint)"
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
    severity = Severity.ERROR
    fixable = True
    safe = False
    option_defaults = {"fix_autodetected_relationships": False}
    description = (
        "A relationship whose id contains 'autodetected' (any case) was "
        "invented by Power BI Desktop's relationship autodetection, which "
        "turns itself back on after Desktop updates. An active one changes "
        "results with no DAX change and can open a second filter path; an "
        "inactive one is indistinguishable from a deliberate one. Delete a "
        "wrong one in Model view; adopt a right one by removing the marker "
        "from its id. The fixer deletes the relationship blocks and runs only "
        "when R007 is selected explicitly or fix_autodetected_relationships "
        "is true; never in a blanket fix."
    )

    def unsafe_fix_enabled(self) -> bool:
        return bool(self.options.get("fix_autodetected_relationships"))

    @staticmethod
    def _matches(rel) -> bool:
        return "autodetected" in rel.rel_id.lower()

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for rel in model.relationships + model.malformed_relationships:
                if self._matches(rel):
                    state = "active" if rel.is_active else "inactive"
                    out.append(
                        self.violation(
                            f"{state} relationship {rel.from_table}[{rel.from_column}] "
                            f"-> {rel.to_table}[{rel.to_column}] was created by "
                            f"Power BI Desktop's autodetection, not by a modeler. "
                            f"Delete it in Model view if it is wrong; adopt it by "
                            f"removing the autodetection marker from its id.",
                            file=rel.file,
                            line=rel.line,
                            obj=f"relationship {rel.rel_id}",
                        )
                    )
        return out

    def fix(self, ctx: Context) -> list[str]:
        from ..edits import EditRefused, read_text_file, verified_write

        applied: list[str] = []
        for model in ctx.models:
            path = model.definition_path / "relationships.tmdl"
            doomed = [r for r in model.relationships + model.malformed_relationships
                      if self._matches(r)]
            if not doomed or not path.is_file():
                continue
            original = read_text_file(path)
            lines = original.lines()
            starts = sorted(r.line - 1 for r in doomed)
            drop: set[int] = set()
            for start in starts:
                end = start + 1
                while end < len(lines) and not lines[end].startswith("relationship "):
                    end += 1
                drop.update(range(start, end))
            kept = [ln for k, ln in enumerate(lines) if k not in drop]
            text = original.join(kept).rstrip("\r\n") + original.newline if any(
                ln.strip() for ln in kept) else ""

            def verify(old: str, new: str) -> None:
                if any("autodetected" in ln.lower() and ln.startswith("relationship ")
                       for ln in new.split(original.newline)):
                    raise EditRefused("an autodetected relationship survived the removal")

            try:
                if verified_write(original, text, verify):
                    applied.extend(f"relationships.tmdl: removed relationship {r.rel_id}" for r in doomed)
            except EditRefused:
                continue
        return applied


class FactConformedDimensionJoinRule(Rule):
    id = "R008"
    name = "fact-conformed-dimension-join"
    severity = Severity.ERROR
    option_defaults = {
        "dimension_table": None,
        "key_column": None,
        "exempt": {},
        "baseline": None,
        "fail_without_baseline_entry": True,
    }
    description = (
        "Every fact table must actively join a conformed dimension (configure "
        "dimension_table and key_column, for example an accounts table and "
        "its key): an ACTIVE relationship from the fact to "
        "dimension_table[key_column], whatever the fact's column is called. "
        "Without it a filter on that dimension silently returns unfiltered "
        "data. Offenders are classified 'missing relationship' (the fact has "
        "the key column) or 'missing key column'. 'exempt' maps tables to a "
        "mandatory reason; 'baseline' ratchets existing offenders per model, "
        "and a model with no entry in it is a finding until the entry is "
        "recorded deliberately ('fail_without_baseline_entry' turns that off). "
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
            flagged: list[str] = []
            for name in fact_tables(model):
                if name in exempt:
                    continue
                joined = any(
                    r.is_active and r.from_table == name and r.to_table == dim and r.to_column == key
                    for r in model.relationships
                )
                if joined:
                    continue
                flagged.append(name)
            if floors is not None:
                found, value = entry_for(floors, mkey)
                if not found and self.options.get("fail_without_baseline_entry"):
                    out.append(self.violation(
                        f"no account-key floor recorded for '{mkey}'. Record it "
                        f"deliberately. Currently flagged ({len(flagged)}): "
                        f"{', '.join(flagged) or 'none'}",
                        file=model.definition_path / "relationships.tmdl", obj=mkey,
                    ))
                accepted = set(value or [])
            for name in flagged:
                if name in accepted:
                    continue
                t = model.tables[name]
                cls = ("missing relationship" if t.find_column(key) else "missing key column")
                out.append(self.violation(
                    f"fact table {name} has no active relationship to {dim}[{key}] "
                    f"({cls}), so filtering by {dim} returns unfiltered data. Create "
                    f"the active relationship" + (" (adding the key column first)." if
                                                  cls == "missing key column" else "."),
                    file=t.file, line=t.line, obj=name,
                ))
            fixed = sorted(accepted - set(flagged))
            if fixed:
                ctx.notes.append(
                    f"FIXED since the floor was recorded ({len(fixed)}): "
                    f"{', '.join(fixed)}")
                ctx.notes.append(
                    f"  -> tighten the floor: remove the fixed table(s) from the "
                    f"floor file of '{mkey}'")
            if flagged and not (set(flagged) - accepted):
                ctx.notes.append(
                    f"KNOWN BACKLOG (ratcheted, not failing) - {len(flagged)} "
                    f"table(s) awaiting an active {dim} relationship: "
                    f"{', '.join(flagged)}")
        return out
