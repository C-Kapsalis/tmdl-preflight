"""Relationship topology: presence, cycles, calendar coverage, keys and
cohort calendars. IDs R009-R016."""

from __future__ import annotations

from collections import deque
from typing import Optional

from ..model import SemanticModel
from ..roles import fact_tables
from .base import Context, Rule, Severity, Violation


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
    opt_in = True
    option_defaults = {"calendar_table": "__Calendar",
                       "standard_columns": ["Date", "Year", "Quarter", "Month", "Week", "Day"]}
    description = (
        "Report authors expect a calendar with the usual levels (Date, Year, "
        "Quarter, Month, Week, Day by default). One info finding lists the "
        "missing ones. Opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            t = model.get_table(self.options["calendar_table"])
            if t is None:
                continue
            have = {c.name.lower() for c in t.column_list}
            missing = [c for c in self.options["standard_columns"] if c.lower() not in have]
            if missing:
                out.append(self.violation(
                    f"calendar {t.name} has no {', '.join(missing)} column(s).",
                    file=t.file, obj=t.name,
                ))
        return out


def _is_key(name: str) -> bool:
    low = name.lower()
    return (low.endswith("_id") or low == "date" or low.endswith("_date") or low.endswith(" date")
            or low.endswith("_level") or low.endswith(".id") or name.startswith("z-"))


class DimensionKeyColumnsRule(Rule):
    id = "R014"
    name = "dimension-key-columns"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"dimension_prefix": "_", "require_dimension_keys": True}
    description = (
        "A dimension table (name starts with '_') without a recognisable key "
        "column (…_id, date, …_date, …_level, .id, or a z- column) usually "
        "cannot be the one side of a relationship. Advisory, opt-in; "
        "require_dimension_keys = false skips it."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("require_dimension_keys") is False

    def check(self, ctx: Context) -> list[Violation]:
        prefix = self.options["dimension_prefix"]
        return [
            self.violation(
                f"dimension table {t.name} has no key-like column (columns: "
                f"{', '.join(c.name for c in t.column_list) or 'none'}).",
                file=t.file, obj=t.name,
            )
            for model in ctx.models for t in model.table_list
            if t.name.startswith(prefix) and not any(_is_key(c.name) for c in t.column_list)
        ]


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
        "the total. Subjects are the dimensions the calendar filters; their "
        "facts are the many sides of those dimensions."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        suffix = self.options["cohort_date_suffix"]
        hops = int(self.options["max_hops"])
        checked = 0
        for model in ctx.models:
            calendars = [t.name for t in model.table_list
                         if any(c.name.endswith(suffix) and not c.is_calculated for c in t.column_list)]
            if not calendars:
                continue
            graph = filter_graph(model)
            ones = set(graph)
            cal_set = set(calendars)
            subjects = {m for cal in calendars for m in graph.get(cal, ()) if m in ones}
            facts = {m for s in subjects for m in graph.get(s, ())} - subjects - cal_set
            if not facts:
                continue
            checked += 1
            for cal in calendars:
                missing = sorted(facts - reachable(graph, cal, hops))
                if missing:
                    t = model.get_table(cal)
                    out.append(self.violation(
                        f"cohort calendar {cal} does not reach {', '.join(missing)} within "
                        f"{hops} active hop(s), so its cohort measures blank or repeat the "
                        f"total there. Anchor it on the subject dimension like its siblings.",
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
    option_defaults = {"template": None, "retained": [], "max_hops": 2}
    description = (
        "An anchor calendar (a table named '__…Calendar') that reaches no "
        "table through active relationships filters nothing: every cohort "
        "measure written against it renders the grand total or blanks. "
        "Calendars the template model also carries (set 'template' to its "
        "folder) and tables listed in 'retained' are not anchors. Use the "
        "baseline to accept known dead calendars."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        excluded = set(self.options.get("retained") or [])
        template = self.options.get("template")
        template_models = [m for m in ctx.models if template and ctx.model_matches(template, m)]
        for tm in template_models:
            excluded |= {p.stem for p in (tm.definition_path / "tables").glob("*.tmdl")
                         if p.stem.startswith("__") and p.stem.endswith("Calendar")}
        for model in ctx.models:
            if model in template_models:
                continue
            graph = filter_graph(model)
            for f in sorted((model.definition_path / "tables").glob("*.tmdl")):
                stem = f.stem
                if not (stem.startswith("__") and stem.endswith("Calendar")) or stem in excluded:
                    continue
                if not reachable(graph, stem, int(self.options["max_hops"])):
                    out.append(self.violation(
                        f"anchor calendar {stem} reaches no table through an active "
                        f"relationship, so it filters nothing. Wire it to the anchor date "
                        f"on its subject dimension, or delete it.",
                        file=f, obj=stem,
                    ))
        return out
