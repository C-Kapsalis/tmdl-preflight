"""Relationship topology: presence, cycles, calendar coverage, keys and
cohort calendars. IDs R009-R016."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Optional

from ..model import SemanticModel
from ..roles import fact_tables
from ..ratchet import entry_for
from .base import Context, Rule, Severity, Violation


def relationship_sides(model: SemanticModel) -> list[tuple[str, str]]:
    """The (one side, many side) of every active relationship.

    The one side is the to-table unless the to-cardinality is 'many'. The
    reverse edge a bidirectional relationship adds is not a side of its own:
    only the declared direction counts here.
    """
    out: list[tuple[str, str]] = []
    for r in model.relationships:
        if not r.is_active:
            continue
        one, many = ((r.to_table, r.from_table) if r.to_cardinality != "many"
                     else (r.from_table, r.to_table))
        out.append((one, many))
    return out


def filter_graph(model: SemanticModel) -> dict[str, set[str]]:
    """Directed filter edges of the ACTIVE relationships: one side -> many
    side (the to-table is the one side unless toCardinality is many), plus
    the reverse edge for bothDirections."""
    graph: dict[str, set[str]] = {}
    for r in model.relationships:
        if not r.is_active:
            continue
        one, many = (r.to_table, r.from_table) if r.to_cardinality != "many" else (r.from_table, r.to_table)
        graph.setdefault(one, set()).add(many)
        if r.cross_filtering.lower() == "bothdirections":
            graph.setdefault(many, set()).add(one)
    return graph


def reachable(graph: dict[str, set[str]], start: str, max_hops: int) -> set[str]:
    seen = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if seen[node] >= max_hops:
            continue
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen[nxt] = seen[node] + 1
                queue.append(nxt)
    seen.pop(start)
    return set(seen)


class RelationshipsPresenceRule(Rule):
    id = "R009"
    name = "relationships-presence"
    severity = Severity.ERROR
    option_defaults = {"enabled": True}
    description = (
        "relationships.tmdl must exist and declare at least one complete "
        "relationship. A model that lost the file in a merge keeps loading, "
        "but every cross-table filter silently stops working. On by default; "
        "a single-table model legitimately has none, so switch it off with "
        "'enabled = false' in that model's configuration."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("enabled") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            path = model.definition_path / "relationships.tmdl"
            if not path.is_file():
                out.append(self.violation(
                    "relationships.tmdl file not found",
                    file=model.definition_path, obj=ctx.model_key(model),
                ))
            elif not model.relationships:
                out.append(self.violation(
                    "relationships.tmdl exists but parses to zero relationships",
                    file=path, obj=ctx.model_key(model),
                ))
        return out


class RelationshipCyclesRule(Rule):
    id = "R010"
    name = "relationship-cycles"
    severity = Severity.INFO
    description = (
        "A cycle over active relationships (A -> B -> C -> A, from table to to "
        "table) can make filter propagation ambiguous. Usually resolved with "
        "an inactive relationship and USERELATIONSHIP; advisory. A two-table "
        "reverse pair is R006's; a table joined to itself is reported here."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            active = [r for r in model.relationships if r.is_active]
            graph: dict[str, list[str]] = {}
            for r in active:
                graph.setdefault(r.from_table, []).append(r.to_table)
            visited: set[str] = set()
            cycles: list[list[str]] = []
            for start in graph:
                if start in visited:
                    continue
                cycle = self._first_cycle(graph, start, visited)
                if cycle:
                    cycles.append(cycle)
            for cycle in cycles:
                out.append(self.violation(
                    f"Cycle detected: {' -> '.join(cycle)}",
                    file=model.definition_path / "relationships.tmdl", obj=cycle[0],
                ))
            note = [
                "Circular Dependency Analysis:",
                f"   Active relationships checked: {len(active)}",
                f"   Tables in graph: {len(graph)}",
                f"   Cycles detected: {len(cycles)}",
            ]
            ctx.notes.append(f"R010: {ctx.model_key(model)}\n" + "\n".join(note))
        return out

    @staticmethod
    def _first_cycle(graph, start, visited) -> Optional[list[str]]:
        """The first cycle reachable from ``start``, as the path that closes it.

        A two-table loop is a reverse pair, which R006 reports, so it is not
        returned here; a table joined to itself is.
        """
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []
        on_path: set[str] = set()
        while stack:
            node, idx = stack.pop()
            if idx == 0:
                visited.add(node)
                path.append(node)
                on_path.add(node)
            children = graph.get(node, [])
            if idx < len(children):
                stack.append((node, idx + 1))
                child = children[idx]
                if child in on_path:
                    cycle = path[path.index(child):] + [child]
                    if len(set(cycle)) == 2:
                        continue  # a reverse pair is R006's finding
                    return cycle
                if child not in visited:
                    stack.append((child, 0))
            else:
                path.pop()
                on_path.discard(node)
        return None


class FactCalendarCoverageRule(Rule):
    id = "R011"
    name = "fact-calendar-coverage"
    severity = Severity.ERROR
    option_defaults = {"calendar_table": "__Calendar", "min_fact_coverage_percent": 90.0,
                       "require_fact_link": True}
    description = (
        "A fact table with no relationship to the calendar cannot be sliced by "
        "date: time slicers return its unfiltered total. A fact counts as "
        "covered when it is the from side of any relationship (active or "
        "inactive, for USERELATIONSHIP) into the calendar table. One error "
        "lists the uncovered facts when coverage falls under "
        "min_fact_coverage_percent (default 90). require_fact_link = false "
        "skips the rule; a model without the calendar table has no coverage "
        "at all, so every fact is uncovered."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("require_fact_link") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        cal = self.options["calendar_table"]
        floor = float(self.options["min_fact_coverage_percent"])
        for model in ctx.models:
            facts = fact_tables(model)
            if not facts:
                continue
            linked = {r.from_table for r in model.relationships if r.to_table == cal}
            uncovered = sorted(f for f in facts if f not in linked)
            coverage = 100.0 * (len(facts) - len(uncovered)) / len(facts)
            lines = [
                f"Calendar coverage {coverage:.1f}% below threshold {floor}",
                f"Fact tables with NO {cal} relationship (active or inactive): "
                f"{', '.join(uncovered)}",
            ]
            if coverage < floor:
                out.append(self.violation(
                    "\n".join(lines),
                    file=model.definition_path / "relationships.tmdl", obj=ctx.model_key(model),
                ))
            note = [
                f"Calendar Relationship Coverage: {coverage:.1f}% "
                f"({len(facts) - len(uncovered)}/{len(facts)})",
                f"Policy threshold: {floor}%",
            ]
            if uncovered:
                note.append(
                    f"Fact tables with NO relationship to {cal} (active or inactive) "
                    f"({len(uncovered)}):"
                )
                note.extend(f"  - {t}" for t in uncovered)
                note.append(
                    f"Recommendation: add a relationship from the table to "
                    f"{cal}[Date]. Inactive is fine - activate it via "
                    f"USERELATIONSHIP in the relevant measures."
                )
            else:
                note.append(f"All fact tables relate to {cal}.")
            ctx.notes.append(f"R011: {ctx.model_key(model)}\n" + "\n".join(note))
        return out


class CalendarRelationshipCardinalityRule(Rule):
    id = "R012"
    name = "calendar-relationship-cardinality"
    severity = Severity.ERROR
    option_defaults = {"calendar_table": "__Calendar"}
    description = (
        "A relationship into the calendar table should be many (fact dates) to "
        "one (calendar date). One-to-one or many-to-many usually means "
        "duplicate calendar dates or a relationship drawn backwards; totals "
        "then double count."
    )

    def check(self, ctx: Context) -> list[Violation]:
        cal = self.options["calendar_table"]
        out: list[Violation] = []
        for model in ctx.models:
            calendar_rels = [r for r in model.relationships if r.to_table == cal]
            invalid = [r for r in calendar_rels
                       if r.from_cardinality_raw != "many" or r.to_cardinality_raw != "one"]
            if invalid:
                lines = [
                    f"{r.from_table}[{r.from_column}] -> {cal}[{r.to_column}]: "
                    f"{r.from_cardinality_raw}-to-{r.to_cardinality_raw}"
                    for r in invalid
                ]
                lines.append(
                    f"Found {len(invalid)} calendar relationships with invalid cardinality"
                )
                lines.append("All calendar relationships should be many-to-one")
                out.append(self.violation(
                    "\n".join(lines),
                    file=invalid[0].file, line=invalid[0].line,
                    obj=ctx.model_key(model),
                ))
            note = [
                "Calendar Relationship Cardinality:",
                f"Total calendar relationships: {len(calendar_rels)}",
                f"Valid (many-to-one): {len(calendar_rels) - len(invalid)}",
                f"Invalid cardinality: {len(invalid)}",
            ]
            ctx.notes.append(f"R012: {ctx.model_key(model)}\n" + "\n".join(note))
        return out


class CalendarStandardColumnsRule(Rule):
    id = "R013"
    name = "calendar-standard-columns"
    severity = Severity.INFO
    option_defaults = {"calendar_table": "__Calendar",
                       "standard_columns": ["Date", "Year", "Quarter", "Month", "Week", "Day"]}
    description = (
        "Report authors expect a calendar with the usual levels (Date, Year, "
        "Quarter, Month, Week, Day by default). One info finding lists the "
        "missing ones. Advisory: it never fails the run."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            t = model.get_table(self.options["calendar_table"])
            if t is None:
                continue
            have = {c.name.lower(): c.name for c in t.column_list}
            present = [have[c.lower()] for c in self.options["standard_columns"]
                       if c.lower() in have]
            missing = [c for c in self.options["standard_columns"] if c.lower() not in have]
            if missing:
                out.append(self.violation(
                    f"calendar {t.name} has no {', '.join(missing)} column(s).",
                    file=t.file, obj=t.name,
                ))
            note = [
                "Calendar Table Completeness:",
                f"Total columns: {len(t.column_list)}",
                f"Standard columns present: {len(present)}/{len(self.options['standard_columns'])}",
            ]
            if present:
                note.append("")
                note.append("Present standard columns:")
                note.extend(f"  - {c}" for c in present)
            if missing:
                note.append("")
                note.append("Advisory - Missing standard columns:")
                note.extend(f"  - {c}" for c in missing)
                note.append("")
                note.append("These columns are recommended for complete date hierarchies.")
            else:
                note.append("")
                note.append("All standard calendar columns present")
            others = sorted(c.name for c in t.column_list if c.name not in present)
            if others:
                note.append("")
                note.append(f"Additional columns ({len(others)}):")
                note.extend(f"  - {c}" for c in others[:10])
            ctx.notes.append(f"R013: {ctx.model_key(model)}\n" + "\n".join(note))
        return out


def _is_key(name: str) -> bool:
    low = name.lower()
    return (low.endswith("_id") or low == "date" or low.endswith("_date") or low.endswith(" date")
            or low.endswith("_level") or low.endswith(".id") or name.startswith("z-"))


class DimensionKeyColumnsRule(Rule):
    id = "R014"
    name = "dimension-key-columns"
    severity = Severity.INFO
    option_defaults = {"dimension_prefix": "_", "require_dimension_keys": True}
    description = (
        "A dimension table (name starts with '_') without a recognisable key "
        "column (…_id, date, …_date, …_level, .id, or a z- column) usually "
        "cannot be the one side of a relationship. Advisory; "
        "require_dimension_keys = false skips it."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("require_dimension_keys") is False

    def check(self, ctx: Context) -> list[Violation]:
        prefix = self.options["dimension_prefix"]
        out: list[Violation] = []
        for model in ctx.models:
            dimensions = [t for t in model.table_list if t.name.startswith(prefix)]
            with_keys = [t for t in dimensions
                         if any(_is_key(c.name) for c in t.column_list)]
            without = [t for t in dimensions if t not in with_keys]
            for t in without:
                out.append(self.violation(
                    f"dimension table {t.name} has no key-like column (columns: "
                    f"{', '.join(c.name for c in t.column_list) or 'none'}).",
                    file=t.file, obj=t.name,
                ))
            coverage = 100.0 * len(with_keys) / len(dimensions) if dimensions else 100.0
            note = [
                f"Total dimension tables ({prefix}prefix): {len(dimensions)}",
                f"With key columns: {len(with_keys)} ({coverage:.1f}%)",
                f"Without apparent keys: {len(without)}",
            ]
            if without:
                note.append("")
                note.append(
                    f"Dimension tables without keys matching the rigid pattern "
                    f"list ({len(without)}):"
                )
                note.append("(Patterns: _x_id, _id, date, _level, z-, .id)")
                for t in sorted(without, key=lambda x: x.name):
                    note.append("")
                    note.append(f"  Table: {t.name}")
                    if t.column_list:
                        note.extend(f"    column: {c.name}" for c in t.column_list)
                    else:
                        note.append("    (no columns parsed)")
            else:
                note.append("")
                note.append("All dimension tables have key columns matching the canonical patterns.")
            ctx.notes.append(f"R014: {ctx.model_key(model)}\n" + "\n".join(note))
        return out


class CohortCalendarReachRule(Rule):
    id = "R015"
    name = "cohort-calendar-reach"
    severity = Severity.ERROR
    option_defaults = {"cohort_date_suffix": "Cohort Date", "max_hops": 2,
                       "require_cohort_calendars": False}
    description = (
        "A cohort calendar (a table with a plain column whose name ends with "
        "'Cohort Date', whatever the table is called) must reach every fact "
        "that carries its cohort subject within max_hops active relationship "
        "hops; otherwise every cohort measure on that fact blanks or repeats "
        "the total. The subject dimensions are the many sides of the active "
        "relationships whose one side is a cohort calendar and that are "
        "themselves the one side of another active relationship; the subject "
        "facts are the many sides of those dimensions."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        suffix = self.options["cohort_date_suffix"]
        hops = int(self.options["max_hops"])
        checked = 0
        for model in ctx.models:
            calendars = [t.name for t in model.table_list
                         if any(c.name.endswith(suffix) and not c.is_calculated
                                for c in t.column_list)]
            if not calendars:
                continue
            graph = filter_graph(model)
            sides = relationship_sides(model)
            cal_set = set(calendars)
            one_sides = {one for one, _many in sides}
            subjects = {
                many
                for one, many in sides
                if one in cal_set and many in one_sides
            }
            facts = {
                many for one, many in sides
                if one in subjects
            } - subjects - cal_set
            if not facts:
                continue
            checked += 1
            for cal in calendars:
                missing = sorted(facts - reachable(graph, cal, hops))
                if missing:
                    t = model.get_table(cal)
                    out.append(self.violation(
                        f"{ctx.model_key(model)}: '{cal}' cannot filter "
                        f"[{', '.join(repr(m) for m in missing)}] over the active "
                        f"relationship graph (subject-bearing facts: "
                        f"[{', '.join(repr(f) for f in sorted(facts))}])",
                        file=t.file if t else None, obj=cal,
                    ))
        if self.options.get("require_cohort_calendars") and checked == 0:
            out.append(self.violation(
                "no model with a cohort calendar and subject facts was found; the "
                "discovery is broken, so this check would pass vacuously."
            ))
        return out


class DeadAnchorCalendarRule(Rule):
    id = "R016"
    name = "dead-anchor-calendar"
    severity = Severity.ERROR
    option_defaults = {"template": None, "retained": [], "max_hops": 2, "floor": None}
    description = (
        "An anchor calendar (a table named '__…Calendar') that reaches no "
        "table through active relationships filters nothing: every cohort "
        "measure written against it renders the grand total or blanks. "
        "Calendars the template model also carries (set 'template' to its "
        "folder, wherever it lives) and tables listed in 'retained' are not "
        "anchors. 'retained' is a list that applies to every model or a "
        "mapping from a model key to the tables it keeps unwired on purpose. "
        "The floor file (option 'floor') records the dead calendars each "
        "model already has: those do not fail, the ones that are new do."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        floors = self._floors()
        for model in ctx.models:
            key = ctx.model_key(model)
            excluded = self._retained_for(key)
            excluded |= self._template_calendars(ctx)
            if self.options.get("template") and ctx.model_matches(self.options["template"], model):
                continue
            graph = filter_graph(model)
            dead: list[str] = []
            for f in sorted((model.definition_path / "tables").glob("*.tmdl")):
                stem = f.stem
                if not (stem.startswith("__") and stem.endswith("Calendar")) or stem in excluded:
                    continue
                if not reachable(graph, stem, int(self.options["max_hops"])):
                    dead.append(stem)
            accepted = set()
            if floors is not None:
                found, value = entry_for(floors, key)
                accepted = set(value or [])
            new = sorted(set(dead) - accepted)
            if new:
                out.append(self.violation(
                    f"New anchor calendar with NO active relationship — it filters "
                    f"nothing, so every cohort measure written against it is inert: "
                    f"{key}: [{', '.join(new)}]. Wire it to the anchor date on the "
                    f"subject dimension, or delete the table. Do not add it to the "
                    f"floor to get green.",
                    file=model.definition_path / "tables" / f"{new[0]}.tmdl",
                    obj=key,
                ))
            fixed = sorted(accepted - set(dead))
            if fixed:
                ctx.notes.append(
                    f"[dead-anchor-calendar floor] {{{key}: {fixed}}} now reach "
                    f"something — tighten with {self._capture_command(ctx)}"
                )
        return out

    def _floors(self) -> Optional[dict]:
        from ..ratchet import RatchetFileError, load_floors

        path = self.options.get("floor")
        if not path:
            return None
        try:
            return load_floors(path, missing_ok=True)
        except RatchetFileError:
            return None

    def capture_floor(self, ctx: Context) -> Optional[dict[str, list[str]]]:
        out: dict[str, list[str]] = {}
        for model in ctx.models:
            key = ctx.model_key(model)
            excluded = self._retained_for(key)
            excluded |= self._template_calendars(ctx)
            graph = filter_graph(model)
            dead = [
                f.stem
                for f in sorted((model.definition_path / "tables").glob("*.tmdl"))
                if f.stem.startswith("__") and f.stem.endswith("Calendar")
                and f.stem not in excluded
                and not reachable(graph, f.stem, int(self.options["max_hops"]))
            ]
            out[key] = sorted(dead)
        return out

    def floor_captured_message(self, floors: dict[str, list[str]]) -> str:
        total = sum(len(names) for names in floors.values())
        return (f"[dead-anchor-calendar floor] captured {total} across "
                f"{len(floors)} models")

    @staticmethod
    def _capture_command(ctx: Context) -> str:
        return "tmdl-preflight check --select dead-anchor-calendar --capture-floor"

    def _retained_for(self, model_key: str) -> set[str]:
        """The calendars this model keeps unwired on purpose."""
        retained = self.options.get("retained") or []
        if isinstance(retained, dict):
            found, value = entry_for(retained, model_key)
            names = value if found else []
        else:
            names = retained
        return {n for n in (names or []) if isinstance(n, str) and n.startswith("__")}

    def _template_calendars(self, ctx: Context) -> set[str]:
        """The anchor calendars the template model carries.

        The template may live anywhere on disk: an absolute path, or a path
        relative to the configuration file. A folder that does not exist
        excludes nothing.
        """
        template = self.options.get("template")
        if not template:
            return set()
        path = Path(str(template))
        if not path.is_absolute():
            path = Path(self.options.get("_config_dir") or ".") / path
        tables = path / "tables"
        if not tables.is_dir():
            tables = path
            if not tables.is_dir():
                return set()
        return {p.stem for p in tables.glob("*.tmdl")
                if p.stem.startswith("__") and p.stem.endswith("Calendar")}
