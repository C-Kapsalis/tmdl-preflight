# Bidirectional filters and orphan tables

*Rules [R004](../reference/rules.md#r004--relationship-bidirectional) and
[R005](../reference/rules.md#r005--orphan-tables).*

These two rules are advisories (`info` severity — they never fail a run).
They exist because the *absence* of a defect is not the same as the
*presence* of a healthy topology, and two topology smells are worth
surfacing on every run.

## Bidirectional cross-filtering (R004)

A relationship normally filters one way: the dimension filters the fact.
`crossFilteringBehavior: bothDirections` makes filtering flow both ways —
sometimes genuinely necessary (classic many-to-many bridges), but carrying
two well-documented hazards:

- **Ambiguity.** With enough bidirectional edges, multiple filter paths can
  connect the same two tables, and the engine's choice of path can produce
  results that are correct by its rules and baffling to the analyst.
- **Performance.** Every bidirectional edge widens the subgraph the engine
  must consider for each query.

The hazard compounds silently: each individual `bothDirections` looked
reasonable when added; the *set* of them is what creates an ambiguous
mesh. So the rule surfaces every occurrence, every run — not because any
one is wrong, but because each one should be re-confirmed as intentional
whenever the model changes around it. No fixer exists (or should): the
"fix" for an intentional bridge is nothing, and for an accidental one it
is a modelling decision.

## Orphan tables (R005)

A table with data columns that participates in no relationship usually
means one of: a load leftover from an abandoned experiment, a table whose
relationships were deleted with intent to re-add (and forgotten), or a
genuinely standalone reference table. The first two are debt — they bloat
the model, confuse users in the field list, and any measure over them
silently ignores every slicer.

The rule is careful about what counts, because healthy models contain many
tables that are *orphans by design*:

- **measure-home tables** — no columns at all, or only hidden placeholder
  columns (Power BI requires at least one column per table, so measure
  tables typically carry one hidden column nobody uses),
- **hidden tables** (mapping and staging helpers a modeler deliberately
  keeps out of the field list),
- **field parameters** (detected via their parameter metadata),
- **calculated helper tables** (all columns calculated, or a calculated
  partition — parameter tables, what-if tables, calendars pending wiring).

Only tables with real, visible data columns and zero relationship
participation are reported, as `info`, for a human to classify. Deliberate
disconnected slicer tables (a static list of options read with
`SELECTEDVALUE`) fall in this group and will keep surfacing; that is by
design — `info` never fails a run — but you can silence the rule with
`--ignore R005` if your model uses the pattern heavily. There is nothing
to auto-fix: deleting a table is destructive and wiring a relationship
requires knowing the join key — both firmly human decisions.
