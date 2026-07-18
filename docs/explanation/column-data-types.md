# Column data types

*Rule [M005](../reference/rules.md#m005--column-data-types).*

## The pitfall

Every column in a TMDL table declares a `dataType`. The tabular engine
accepts a small closed set — `string`, `int64`, `double`, `decimal`,
`dateTime`, `boolean`, `binary`, `variant`, `currency`, `rowNumber` — and
nothing else.

The values look guessable, and that is the trap. A modeler hand-adding a
column writes `dataType: text` (SQL habit), `dataType: int` (programming
habit), `dataType: date` or `dataType: datetime` (wrong casing — TMDL's
property values are case-sensitive where the engine's enum is). A scripted
refactor maps types from a source system and lets an unmapped value slip
through. In every case the file reads naturally; the model is rejected — or
the tooling falls back to a default type, which is worse, because a numeric
column typed as `string` deploys fine and then quietly breaks aggregation,
sorting, and every measure that sums it.

## How the rule detects it

Every parsed column's declared `dataType` is compared against the closed
set above. Anything outside it is reported with the table, column, file and
line. The severity is `warning` rather than `error` because the parser
cannot be certain how a given deployment path treats an unknown value —
but in practice you should treat a hit as a bug to fix before shipping.

## Why there is no auto-fix

The *intended* type is knowledge the file does not contain. `text` almost
certainly means `string` — but `int` could be `int64` or `double`
(depending on whether the source can overflow or carry nulls), and `date`
could be `dateTime` deliberately narrowed downstream. Guessing would
convert a loud, early failure into a quiet, late one, which is the exact
opposite of this tool's job. The rule points at the line; the human picks
the type.

## See also

- [TMDL well-formedness](tmdl-well-formedness.md) — the same "cheap check,
  expensive late discovery" logic one layer down.
