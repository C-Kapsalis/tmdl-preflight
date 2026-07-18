# Stray commas in field-parameter sources

*Rule [F001](../reference/rules.md#f001--fieldparam-comma-runs).*

## The pitfall

Field parameters — and calculated tables generally — are defined by a DAX
table constructor: a `{ ... }` list of tuples separated by commas.

```dax
{
    ( "Revenue",   NAMEOF ( [Revenue] ),   0 ),
    ( "Orders #",  NAMEOF ( [Orders #] ),  1 ),
    ( "Units Sold", NAMEOF ( [Units Sold] ), 2 )
}
```

The maintenance operation this invites is *removing a row* — a metric is
retired, a measure moves elsewhere. And the natural way to remove a row in
a text editor or a script is to delete the tuple's line… which leaves its
**separator** behind:

```dax
{
    ( "Revenue",   NAMEOF ( [Revenue] ),   0 ),
    ,
    ( "Units Sold", NAMEOF ( [Units Sold] ), 2 )
}
```

That orphan comma makes the entire source expression unparseable. And
because a field parameter is infrastructure rather than content, the blast
radius is wide: the parameter's table is invalid, every visual and slicer
driven by it fails, and any calculated table *derived from* the parameter
(a common pattern — for example a categories table built by unioning the
parameter's rows) fails with it. One character, several report pages.

Two things make this defect a recurring class rather than a one-off:

- **Automation produces it.** Scripts that drop rows by matching the tuple
  line are exactly one comma away from correct, forever.
- **Commented-out rows camouflage it.** Teams park rows with `--` rather
  than deleting them; a scanner that naively counts commas then flags the
  parked rows and gets ignored — while missing the real orphan.

## How the rule detects it

For every `calculated` partition source in the model, the rule masks
comment contents (length-preserving, so line numbers survive) and then
scans for **comma runs**: two or more commas separated only by whitespace
(`,,` and the multi-line orphan case both match). Commas inside `--`/`//`
comments never count — a commented-out row is an intentional parking, not
a defect. The scan covers all calculated tables, not only field parameters,
because the failure mode is identical for any table-constructor source.

## Why the fix is safe

The repair collapses each run to its **first comma** — the live separator
between the two surviving rows — and deletes only the orphans. Its safety
comes from a precise observation about the failure mode:

- The orphan commas are, by construction, *the* leftover of the row that
  was already deleted. Removing them completes a deletion the author
  already made; it does not make any new decision.
- Nothing else in the expression is touched: whitespace, comments and all
  surviving tuples are byte-for-byte preserved, and the edit is applied
  only inside the partition-source block's line range in the file.
- It is idempotent — once no run of 2+ commas exists, the fixer has
  nothing to match.

The one thing the fixer deliberately does **not** do is decide whether the
row *should* have been deleted — if the deletion itself was the mistake,
that shows up as a dangling `NAMEOF` reference, which is
[D002](nameof-reference-integrity.md)'s job to report and a human's job to
resolve.
