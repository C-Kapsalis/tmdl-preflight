# Rule catalog

Severity semantics: **error** — will break an import/deploy or silently
corrupt results; **warning** — suspicious, deserves a look before shipping;
**info** — advisory, never blocks (not even with `--strict`).

Select rules by id or name, case-insensitively: `--select M003` and
`--select lineage-duplicates` are equivalent.

Each rule links to an explanation guide covering the underlying pitfall.

---

## M001 — model-structure

| | |
|---|---|
| Severity | error |
| Auto-fix | no |
| Scope | each `definition/` folder |

The definition folder must contain `model.tmdl` and a `tables/` folder with
at least one `.tmdl` file. Guards against truncated exports and bad merges
that drop whole folders.
[Explanation](../explanation/tmdl-well-formedness.md)

## M002 — tmdl-well-formed

| | |
|---|---|
| Severity | error |
| Auto-fix | no |
| Scope | every `.tmdl` file, recursively |

Each file must decode as UTF-8, contain no null bytes, have an even number
of ```` ``` ```` expression fences, and (for table files) declare a table.
[Explanation](../explanation/tmdl-well-formedness.md)

## M003 — lineage-duplicates

| | |
|---|---|
| Severity | error |
| Auto-fix | **yes** — keeps the first occurrence, regenerates the rest |
| Scope | every `lineageTag:` across the definition folder |

No two objects may share a `lineageTag`. Duplicates are rejected at import
("an object with that lineage tag already exists").
[Explanation](../explanation/duplicate-lineage-tags.md)

## M004 — lineage-format

| | |
|---|---|
| Severity | warning |
| Auto-fix | **yes** — regenerates the tag as a fresh UUID |
| Scope | every `lineageTag:` across the definition folder |

Tags must be canonical hyphenated UUIDs (8-4-4-4-12 hex). Placeholder or
hand-typed tags defeat the identity mechanism lineage tags exist for.
[Explanation](../explanation/duplicate-lineage-tags.md)

## M005 — column-data-types

| | |
|---|---|
| Severity | warning |
| Auto-fix | no |
| Scope | every declared column `dataType:` |

Value must be one of `string`, `int64`, `double`, `decimal`, `dateTime`,
`boolean`, `binary`, `variant`, `currency`, `rowNumber`.
[Explanation](../explanation/column-data-types.md)

## D001 — dax-delimiters

| | |
|---|---|
| Severity | error |
| Auto-fix | no |
| Scope | every DAX expression: measures, calculated columns, calculated-partition sources, calculation items, dynamic format strings |

Parentheses, braces, brackets, strings and quoted identifiers must balance.
Comment contents and string contents are excluded from the count.
[Explanation](../explanation/dax-delimiter-balance.md)

## D002 — nameof-resolution

| | |
|---|---|
| Severity | error (`warning` for ambiguous references) |
| Auto-fix | no |
| Scope | every `NAMEOF()` call in every DAX expression |

`NAMEOF('Table'[Member])` must point at an existing column or measure on
that table; `NAMEOF([Measure])` at an existing measure. Qualified
references to measures are accepted — Power BI Desktop writes that form
itself when building field parameters. An ambiguous bare-measure reference
(the same measure name declared in several tables) is downgraded to a
warning, because rule D003 already reports the underlying duplicate as an
error.
[Explanation](../explanation/nameof-reference-integrity.md)

## D003 — duplicate-measure-names

| | |
|---|---|
| Severity | error |
| Auto-fix | no |
| Scope | all measures, model-wide |

The tabular engine requires measure names to be unique across the whole
model, not merely within a table.
[Explanation](../explanation/duplicate-measure-names.md)

## R001 — relationship-endpoints

| | |
|---|---|
| Severity | error |
| Auto-fix | no |
| Scope | every relationship in `relationships.tmdl` |

The from/to tables must exist and the referenced columns must exist on
them. [Explanation](../explanation/relationship-integrity.md)

## R002 — relationship-cardinality

| | |
|---|---|
| Severity | error |
| Auto-fix | no |
| Scope | every relationship |

`fromCardinality`/`toCardinality`, where declared, must be `one` or `many`.
[Explanation](../explanation/relationship-integrity.md)

## R003 — relationship-duplicates

| | |
|---|---|
| Severity | warning |
| Auto-fix | no |
| Scope | every relationship |

Two relationships over the same column pair (keyed on endpoints, not
GUIDs). [Explanation](../explanation/relationship-integrity.md)

## R004 — relationship-bidirectional

| | |
|---|---|
| Severity | info |
| Auto-fix | no |
| Scope | every relationship |

Surfaces each `crossFilteringBehavior: bothDirections` so the modeler
confirms it is intentional.
[Explanation](../explanation/bidirectional-and-orphan-tables.md)

## R005 — orphan-tables

| | |
|---|---|
| Severity | info |
| Auto-fix | no |
| Scope | every table |

Data tables that participate in no relationship. Tables that are unrelated
by design are exempt: measure-only tables, tables whose columns are all
hidden (the measure-home pattern), hidden tables, field parameters and
calculated helper tables. Deliberate disconnected slicer tables with
visible columns still surface — as `info`, so they never fail a run.
[Explanation](../explanation/bidirectional-and-orphan-tables.md)

## F001 — fieldparam-comma-runs

| | |
|---|---|
| Severity | error |
| Auto-fix | **yes** — keeps each run's first comma, deletes the orphans |
| Scope | every `calculated` partition source (field parameters, calculated tables) |

Two or more commas separated only by whitespace — the classic leftover of
deleting a row without its separator — make the whole source unparseable.
Commas inside `--`/`//` comments are exempt.
[Explanation](../explanation/field-parameter-comma-runs.md)

## B001 — bookmark-int-types

| | |
|---|---|
| Severity | error |
| Auto-fix | **yes** — coerces the value to its integer form |
| Scope | every `*.bookmark.json` under each `*.Report` folder |

`howCreated`, `ComparisonKind` and `Version` must be JSON integers, not
strings. Known string spellings of `howCreated` (`"User"`, `"System"`, …)
are mapped; unknown strings are left for a human.
[Explanation](../explanation/bookmark-integer-types.md)

## B002 — bookmark-visual-refs

| | |
|---|---|
| Severity | error |
| Auto-fix | no — the right resolution depends on intent |
| Scope | every `*.bookmark.json` under each `*.Report` folder |

Every visual a bookmark references must exist as a visual folder under
`pages/*/visuals/`.
[Explanation](../explanation/bookmark-visual-references.md)

## S001 — format-strings

| | |
|---|---|
| Severity | info |
| Auto-fix | no |
| Scope | every visible measure |

Visible measures should declare a `formatString`. Models that carry
`formatStringDefinition` blocks (dynamic formatting via calculation groups)
are exempted automatically; disable explicitly with `--ignore S001` if your
formatting strategy lives elsewhere.
[Explanation](../explanation/format-strings.md)

---

## Configuration

tmdl-preflight has no config file in this release; scoping is done per
invocation with `--select`/`--ignore` (or the pytest fixture's `select=` /
`ignore=` arguments). Custom rules are added in code — see
[How to add a custom rule](../how-to/add-a-custom-rule.md).
