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
            endpoint_errors = 0
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
                        endpoint_errors += 1
                        out.append(self.violation(
                            f"{side.capitalize()} table not found: {table} "
                            f"(in relationship {rel.rel_id[:8]}...)",
                            file=rel.file, line=rel.line, obj=obj,
                        ))
                        continue
                    col = t.find_column(column)
                    if col is None:
                        broken_ids.add(id(rel))
                        endpoint_errors += 1
                        out.append(self.violation(
                            f"{side.capitalize()} column not found: {table}[{column}] "
                            f"(in relationship {rel.rel_id[:8]}...)",
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
            inactive = [r for r in model.relationships if not r.is_active]
            summary = [
                f"Validated {total} relationships",
                f"   Errors: {endpoint_errors}",
                f"   Warnings (inactive): {len(inactive)}",
            ]
            if total:
                rate = (total - len(broken_ids)) / total
                summary.append(f"   Success rate: {rate * 100:.1f}%")
                if rate < threshold:
                    summary.append(
                        f"Relationship validation below {threshold * 100:.1f}% "
                        f"({rate * 100:.1f}%)."
                    )
                    summary.append(f"Broken relationship endpoints: {endpoint_errors}")
            summary.extend(
                f"Inactive: {r.from_table} -> {r.to_table}" for r in inactive
            )
            ctx.notes.append(f"R001: {ctx.model_key(model)}\n" + "\n".join(summary))
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
            stats: dict[str, int] = {}
            for rel in model.relationships:
                for side, value in (
                    ("fromCardinality", rel.from_cardinality),
                    ("toCardinality", rel.to_cardinality),
                ):
                    if value not in VALID_CARDINALITIES:
                        out.append(
                            self.violation(
                                f"Invalid {side[:-len('Cardinality')]} "
                                f"cardinality: {value.lower()} in {rel.rel_id[:8]}...",
                                file=rel.file,
                                line=rel.line,
                                obj=f"relationship {rel.rel_id[:8]}",
                            )
                        )
                kind = f"{rel.from_cardinality}_to_{rel.to_cardinality}"
                stats[kind] = stats.get(kind, 0) + 1
            if stats:
                lines = ["Cardinality Distribution:"]
                for kind, count in sorted(stats.items(), key=lambda kv: (-kv[1], kv[0])):
                    lines.append(f"   {kind:20s} {count:3d}")
                many_to_many = stats.get("many_to_many", 0)
                if many_to_many > 3:
                    lines.append(
                        f"Warning: {many_to_many} many-to-many relationships "
                        f"(may impact performance)"
                    )
                ctx.notes.append(f"R002: {ctx.model_key(model)}\n" + "\n".join(lines))
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
            both = [r for r in model.relationships
                    if r.cross_filtering.lower() == "bothdirections"]
            for rel in both:
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
            lines = [
                "Cross-filtering Analysis:",
                f"   Unidirectional: {len(model.relationships) - len(both)}",
                f"   Bidirectional: {len(both)}",
            ]
            for rel in both[:10]:
                lines.append(f"   - {rel.from_table} <-> {rel.to_table}")
                lines.append(
                    f"     {rel.from_table}[{rel.from_column}] <-> "
                    f"{rel.to_table}[{rel.to_column}]"
                )
            if len(both) > 5:
                lines.append(
                    f"Warning: {len(both)} bidirectional relationships detected"
                )
                lines.append(
                    "   Consider if all of these are necessary for model performance"
                )
            elif len(both) <= 3:
                lines.append("Bidirectional count is acceptable (<=3)")
            ctx.notes.append(f"R004: {ctx.model_key(model)}\n" + "\n".join(lines))
        return out


class OrphanTablesRule(Rule):
    id = "R005"
    name = "orphan-tables"
    severity = Severity.INFO
    description = (
        "Data tables that participate in no relationship are usually load "
        "leftovers. Tables that are unrelated by design are exempt: "
        "measure-only tables, tables whose columns are all hidden (the "
        "measure-home pattern), hidden tables, calculated helper tables, "
        "field parameters and the tables whose name says they are expected "
        "to stand alone (a plot-specific or selector table, a z- table, a "
        "measures table)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            related: set[str] = set()
            for rel in model.relationships:
                related.add(rel.from_table)
                related.add(rel.to_table)
            orphans = [t for t in model.table_list if t.name not in related]
            expected = [t for t in orphans if self._is_expected_orphan(t.name)]
            other = [t for t in orphans if t not in expected]
            plot_specific = [t for t in orphans if "plot specific" in t.name.lower()]
            selector = [t for t in orphans if "selector" in t.name.lower()]
            measure = [t for t in orphans if "measure" in t.name.lower()]
            for table in other:
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
            note = [
                f"Total tables: {len(model.table_list)}",
                f"With relationships: {len(related)}",
                f"Orphans: {len(orphans)}",
                "",
                "Orphan Categories:",
                f"   - Plot Specific tables: {len(plot_specific)}",
                f"   - Selector tables: {len(selector)}",
                f"   - Measure tables: {len(measure)}",
                f"   - Other: {len(other)}",
                "",
                f"Expected orphans (Plot Specific/Selector/Measure): {len(expected)}",
                f"Unexpected orphans: {len(other)}",
            ]
            if other:
                note.append("")
                note.append("Other Orphan Tables:")
                note.extend(f"  - {t.name}" for t in other)
            if len(other) > 50:
                note.append("")
                note.append(f"Warning: {len(other)} unexpected orphan tables")
            ctx.notes.append(f"R005: {ctx.model_key(model)}\n" + "\n".join(note))
        return out

    @staticmethod
    def _is_expected_orphan(name: str) -> bool:
        """Is this table expected to stand alone, by its name?"""
        low = name.lower()
        return (
            "plot specific" in low
            or "selector" in low
            or name.startswith("z-")
            or "measure" in low
        )


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
            groups: dict[frozenset, list] = {}
            for rel in model.relationships:
                if not rel.is_active:
                    continue
                key = frozenset((rel.from_table.lower(), rel.to_table.lower()))
                groups.setdefault(key, []).append(rel)
            for rels in groups.values():
                if len(rels) < 2:
                    continue
                first = rels[0]
                ids = ", ".join(r.rel_id for r in rels)
                columns = sorted({f"{r.from_column}->{r.to_column}" for r in rels})
                out.append(
                    self.violation(
                        f"{first.from_table} -> {first.to_table}: {len(rels)} active "
                        f"[{ids}] on columns [{', '.join(columns)}]",
                        file=first.file,
                        line=first.line,
                        obj=f"relationship {first.rel_id[:8]}",
                    )
                )
        return out


class AutodetectedRelationshipsRule(Rule):
    id = "R007"
    name = "autodetected-relationships"
    severity = Severity.ERROR
    fixable = True
    safe = False
    baselinable = False
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
        "is true; never in a blanket fix. Zero tolerance: it can never be "
        "baselined."
    )

    def unsafe_fix_enabled(self) -> bool:
        return bool(self.options.get("fix_autodetected_relationships"))

    def pending_repairs(self, ctx: Context) -> bool:
        """The fixer always runs when it is selected: it also says what it
        found when there is nothing to remove."""
        return True

    @staticmethod
    def _matches(rel) -> bool:
        return "autodetected" in rel.rel_id.lower()

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for rel in model.relationships + model.malformed_relationships:
                if not self._matches(rel):
                    continue
                state = ("ACTIVE  <-- changing measure results NOW"
                         if rel.is_active else "inactive")
                out.append(
                    self.violation(
                        f"{state}  {rel.from_table}[{rel.from_column}] -> "
                        f"{rel.to_table}[{rel.to_column}]" "\n"
                        f"name: {rel.rel_id}",
                        file=rel.file,
                        line=rel.line,
                        obj=f"relationship {rel.rel_id}",
                    )
                )
        if out:
            ctx.notes.append(
                "Power BI re-enables 'Autodetect new relationships after data "
                "is loaded' after every Desktop update, so the setting cannot "
                "be relied on.\n"
                "WRONG relationship -> delete it in Power BI Model view, "
                "re-save.\n"
                "RIGHT relationship -> adopt it: strip the 'AutoDetected_' "
                "prefix from its name in relationships.tmdl, leaving the bare "
                "GUID. Safe -- nothing references relationships by name; DAX "
                "uses USERELATIONSHIP on columns."
            )
        return out

    def dry_run_notes(self, ctx: Context) -> list[str]:
        out: list[str] = []
        for model in ctx.models:
            path = model.definition_path / "relationships.tmdl"
            if not path.is_file():
                out.append("No relationships file")
                continue
            doomed = [r for r in model.relationships + model.malformed_relationships
                      if self._matches(r)]
            if not doomed:
                out.append("No autodetected relationships found")
                continue
            out.append(f"Found {len(doomed)} autodetected relationships:")
            out.extend(f"   - {r.rel_id}" for r in doomed)
            out.append(
                f"Would delete {len(doomed)} autodetected relationships (strict policy)"
            )
        return out

    def fix(self, ctx: Context) -> list[str]:
        from ..edits import EditRefused, read_text_file, verified_write

        applied: list[str] = []
        for model in ctx.models:
            path = model.definition_path / "relationships.tmdl"
            if not path.is_file():
                ctx.fix_notes.append("No relationships file")
                continue
            doomed = [r for r in model.relationships + model.malformed_relationships
                      if self._matches(r)]
            if not doomed:
                ctx.fix_notes.append("No autodetected relationships found")
                continue
            ctx.fix_notes.append(
                f"Found {len(doomed)} autodetected relationships:"
            )
            ctx.fix_notes.extend(f"   - {r.rel_id}" for r in doomed)
            original = read_text_file(path)
            # every line keeps its own terminator, so the bytes that are not
            # part of a removed block come out exactly as they went in
            lines = original.text.splitlines(keepends=True)
            starts = sorted(r.line - 1 for r in doomed)
            drop: set[int] = set()
            for start in starts:
                end = start + 1
                while end < len(lines) and not lines[end].startswith("relationship "):
                    end += 1
                drop.update(range(start, end))
            kept = [ln for k, ln in enumerate(lines) if k not in drop]
            text = "".join(kept)

            def verify(old: str, new: str) -> None:
                if any("autodetected" in ln.lower() and ln.startswith("relationship ")
                       for ln in new.splitlines()):
                    raise EditRefused("an autodetected relationship survived the removal")

            try:
                if verified_write(original, text, verify):
                    ctx.fix_notes.append(
                        f"Deleted {len(doomed)} autodetected relationships"
                    )
                    applied.extend(
                        f"relationships.tmdl: removed relationship {r.rel_id}"
                        for r in doomed
                    )
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
        "fail_without_baseline_entry": None,
        "template_facts": None,
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
        "A fact whose key column is missing is called out as a template "
        "fact (a core-model defect) or as model-specific, depending on "
        "'template_facts'. Facts follow the shared table-role law. Inert "
        "until configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        from ..ratchet import RatchetFileError, entry_for, load_floors
        from ..roles import fact_tables

        dim = self.options.get("dimension_table")
        key = self.options.get("key_column")
        if not dim or not key:
            return []
        exempt = self.options.get("exempt") or {}
        template_facts = set(self.options.get("template_facts") or [])
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
            facts = fact_tables(model)
            in_scope = [n for n in facts if n not in exempt]
            offenders = self._offenders(model, dim, key, exempt, template_facts)
            no_join = [n for n in offenders if self._has_key_column(model, n, key)]
            missing_key = [n for n in offenders if n not in no_join]
            if floors is not None:
                found, value = entry_for(floors, mkey)
                if not found and self._fail_without_entry():
                    out.append(self.violation(
                        f"no account-key floor recorded for '{mkey}'. Record it "
                        f"deliberately: {self._capture_command()}. Currently flagged "
                        f"({len(offenders)}): {', '.join(sorted(offenders)) or 'none'}",
                        file=model.definition_path / "relationships.tmdl", obj=mkey,
                    ))
                    continue
                accepted = set(value or [])
            new = sorted(set(offenders) - accepted)
            fixed = sorted(accepted - set(offenders))
            if new:
                out.append(self.violation(
                    "\n".join(self._finding(mkey, new, missing_key, no_join,
                                            template_facts, len(accepted))),
                    file=model.definition_path / "relationships.tmdl", obj=mkey,
                ))
            if fixed:
                ctx.notes.append(
                    f"FIXED since the floor was recorded ({len(fixed)}): "
                    f"{', '.join(fixed)}\n"
                    f"  -> tighten the floor: {self._capture_command()}"
                )
            if offenders and not new:
                ctx.notes.append(
                    f"KNOWN BACKLOG (ratcheted, not failing) - {len(offenders)} "
                    f"table(s) awaiting an active {dim} relationship: "
                    f"{', '.join(sorted(offenders))}"
                )
            summary = [
                f"Fact-classified tables: {len(facts)}",
            ]
            if exempt:
                summary.append(
                    f"Excluded, declared exempt ({len(exempt)}): "
                    f"{', '.join(sorted(exempt))}"
                )
            summary.append(f"In scope: {len(in_scope)}")
            summary.append(
                f"Account-filterable (active -> {dim} join): "
                f"{len(in_scope) - len(offenders)}"
            )
            summary.append(
                f"Flagged: {len(offenders)} (no join w/ {key}: {len(no_join)}; "
                f"no join, no FK col: {len(missing_key)})"
            )
            ctx.notes.append(f"R008: {mkey}\n" + "\n".join(summary))
        return out

    def _fail_without_entry(self) -> bool:
        """Must a model have a recorded floor entry?

        With a floor file configured, a model without an entry fails: the
        backlog has to be recorded deliberately, never picked up silently.
        """
        value = self.options.get("fail_without_baseline_entry")
        if value is None:
            return True
        return bool(value)

    def capture_floor(self, ctx: Context) -> Optional[dict[str, list[str]]]:
        from ..roles import fact_tables

        dim = self.options.get("dimension_table")
        key = self.options.get("key_column")
        if not dim or not key:
            return None
        exempt = self.options.get("exempt") or {}
        template_facts = set(self.options.get("template_facts") or [])
        out: dict[str, list[str]] = {}
        for model in ctx.models:
            mkey = ctx.model_key(model)
            offenders = self._offenders(model, dim, key, exempt, template_facts)
            out[mkey] = sorted(offenders)
        return out

    def floor_indent(self) -> int:
        return 1

    def floor_captured_message(self, floors: dict[str, list[str]]) -> str:
        return " ".join(
            f"captured account-key floor for {key}: {len(names)} known offender(s)"
            for key, names in sorted(floors.items())
        )

    def _joined(self, model, dim: str, key: str) -> set[str]:
        """The facts that actively join the dimension on its key."""
        return {
            r.from_table
            for r in model.relationships
            if r.is_active and r.to_table == dim and r.to_column == key
        }

    @staticmethod
    def _has_key_column(model, name: str, key: str) -> bool:
        """Does the table carry the key column, spelled exactly like that?

        The check is case-sensitive: a column named ``Account_X_ID`` is not
        the key column ``account_x_id``.
        """
        table = model.tables.get(name)
        return table is not None and key in table.columns

    def _offenders(self, model, dim: str, key: str, exempt, template_facts) -> list[str]:
        """The facts with no active join to the dimension, in table order."""
        joined = self._joined(model, dim, key)
        return [
            name for name in model.tables
            if name not in exempt and name not in joined and self._is_fact(model, name)
        ]

    @staticmethod
    def _is_fact(model, name: str) -> bool:
        from ..roles import is_fact

        table = model.tables.get(name)
        return table is not None and is_fact(table)

    @staticmethod
    def _capture_command() -> str:
        return "tmdl-preflight check --select fact-conformed-dimension-join " \
               "--capture-floor"

    def _finding(self, mkey: str, new: list[str], missing_key: list[str],
                 no_join: list[str], template_facts: set[str], known: int) -> list[str]:
        key = self.options["key_column"]
        dim = self.options["dimension_table"]
        lines = [
            f"NEW account-key offender(s) in '{mkey}' — {len(new)} table(s) "
            f"not in the recorded floor ({known} known). This is a fresh "
            f"regression, not the existing backlog:"
        ]
        new_missing = [n for n in new if n in missing_key]
        new_no_join = [n for n in new if n in no_join]
        if new_missing:
            lines.append(
                f"Fact tables missing '{key}' — they cannot be account-filtered:"
            )
            template = sorted(n for n in new_missing if n in template_facts)
            specific = sorted(n for n in new_missing if n not in template_facts)
            if template:
                lines.append("  CRITICAL — template fact tables (core-model defect):")
                lines.extend(f"    - {n}" for n in template)
            if specific:
                lines.append(
                    "  model-specific fact tables — the database must supply a "
                    f"placeholder {key}:"
                )
                lines.extend(f"    - {n}" for n in specific)
        if new_no_join:
            lines.append(
                f"Fact tables that carry '{key}' but have NO active relationship "
                f"to {dim}[{key}] — the account filter would resolve but return "
                f"UNFILTERED data; create the active relationship (your "
                f"relationship tooling):"
            )
            lines.extend(f"    - {n}" for n in new_no_join)
        return lines
