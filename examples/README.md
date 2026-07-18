# Example models

Two copies of the same fictional PBIP project — the Pedal & Sprocket Bike
Co. semantic model and its report:

- **`bike-shop-clean/`** — the model as it should be. Opens in Power BI
  Desktop and every rule passes.
- **`bike-shop-broken/`** — the same project seeded with defects that stop
  Power BI Desktop from opening it. Run the fixer and it opens.

## The 30-second story

`bike-shop-broken` will **not open in Power BI Desktop**: a table is missing
its `ref table` line (so it is not part of the model), a field-parameter
partition has an orphan comma, and two tables share a lineage tag. Point
tmdl-preflight at it, let it auto-repair the blockers, and Power BI opens the
project:

```console
$ tmdl-preflight check examples/bike-shop-broken   # exit 1 — see what's wrong
$ tmdl-preflight fix   examples/bike-shop-broken   # auto-repair the blockers
$ tmdl-preflight check examples/bike-shop-broken   # 0 errors — now it opens
```

`fix` edits files in place, so work on a copy if you want to rerun the
walkthrough with the broken original intact:

```console
$ cp -r examples/bike-shop-broken /tmp/bike-shop
$ tmdl-preflight fix /tmp/bike-shop
```

`bike-shop-clean` passes with nothing to report:

```console
$ tmdl-preflight check examples/bike-shop-clean    # exit 0
```

## What is seeded where

| File | Rule | Defect | Fixer |
|---|---|---|---|
| `definition/model.tmdl` | M006 | `Stores` has no `ref table` line, so it is not attached to the model and Power BI refuses to open the project | ✅ re-adds the line |
| `tables/Stores.tmdl` | M003 | table `lineageTag` copy-pasted from `Products.tmdl` (duplicate — the deploy target rejects it) | ✅ regenerates it |
| `tables/__Calendar.tmdl` | M004 | placeholder `lineageTag` that is not a canonical UUID | ✅ regenerates it |
| `tables/Metric Selector.tmdl` | F001 | field-parameter row deleted, its comma left behind (breaks the calculated partition) | ✅ removes the orphan comma |
| `tables/Sales Measures.tmdl` | S001 | visible measure `Units Sold` has no `formatString` | ⚠️ info only — add one yourself |

The first four are **blockers** Power BI rejects on open; `fix` repairs all
of them mechanically and the project then loads. `S001` is an info-level
style nudge that does not stop the model from opening. The walkthrough that
uses these folders is [Getting started](../docs/tutorials/getting-started.md);
what each rule protects you from is in the
[explanation guides](../docs/explanation/README.md).
