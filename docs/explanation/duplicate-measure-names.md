# Duplicate measure names

*Rule [D003](../reference/rules.md#d003--duplicate-measure-names).*

## The pitfall

Columns are scoped to their table: `Sales[quantity]` and
`Returns[quantity]` coexist happily. Measures are not. In the tabular
model, **measure names are unique across the entire model** — a measure
merely *lives* in a home table for organizational purposes, but its name
is global, which is why DAX references it as `[Revenue]` with no table
qualifier.

Text-file workflows walk straight into this. Copying a table file to
scaffold a similar one copies its measures. A merge keeps both sides'
version of a measure that one branch moved to a different home table —
each file is individually valid, and no textual conflict is reported,
because the two declarations live in *different files*. Power BI Desktop
would have refused the second declaration interactively; a git merge has
no such opinion.

The result is a model the engine rejects at import. And even before
deployment, duplicates poison anything that resolves measures by name:
`NAMEOF([Revenue])` becomes ambiguous, and tooling that looks measures up
model-wide picks one of the two arbitrarily.

## How the rule detects it

All measures from all tables are indexed by name; any name declared more
than once is reported at every occurrence after the first, with the first
occurrence's table, file and line in the message so both halves of the
collision are one click away. `NAMEOF` ambiguity warnings from
[D002](nameof-reference-integrity.md) are the same disease observed from
the reference side; D003 errors on the disease itself.

## Why there is no auto-fix

The two declarations usually differ — one is stale, one is current, or
they were never meant to be the same measure at all. Deleting one requires
knowing which; renaming one requires knowing what every report and
expression referencing `[Revenue]` intended. Both are judgement calls, so
the rule fails plainly and shows both locations.
