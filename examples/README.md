# Example models

Two copies of the same fictional PBIP project — the Pedal & Sprocket Bike
Co. semantic model and its report — so you can run tmdl-preflight against
real TMDL files without exporting anything from Power BI Desktop:

- **`bike-shop-clean/`** — the model as it should be. Every rule passes.
- **`bike-shop-broken/`** — the same model with nine deliberate defects
  seeded across eight rules: four that the fixer repairs mechanically and
  four that need a human decision.

Try the two commands:

```console
$ tmdl-preflight check examples/bike-shop-clean
$ tmdl-preflight check examples/bike-shop-broken
```

The first exits 0 and reports nothing. The second exits 1 and reports every
seeded defect with its file, line, rule id, and whether it is auto-fixable.

To try the fixer, work on a copy — `fix` edits files in place, and you want
to keep the broken original around to rerun the tutorial:

```console
$ cp -r examples/bike-shop-broken /tmp/bike-shop
$ tmdl-preflight fix /tmp/bike-shop
```

## What is seeded where

| File | Rule | Defect |
|---|---|---|
| `tables/Stores.tmdl` | M003 | table `lineageTag` copy-pasted from `Products.tmdl` |
| `tables/Calendar.tmdl` | M004 | placeholder `lineageTag` that is not a UUID |
| `tables/Metric Selector.tmdl` | F001 | field-parameter row deleted, its comma left behind |
| `bookmarks/spotlight-revenue.bookmark.json` | B001 | `howCreated` and a filter `Version` stored as strings |
| `tables/Stores.tmdl` | D003 | measure `Revenue per Store` duplicated from `Sales Measures` |
| `relationships.tmdl` | R001 | inactive ship-date relationship still points at the renamed table `Dates` |
| `tables/Sales Measures.tmdl` | S001 | visible measure `Units Sold` has no `formatString` |
| `bookmarks/spotlight-orders.bookmark.json` | B002 | bookmark captures a visual that was later deleted |

The first four are auto-fixable; the last four are not, because the right
repair depends on intent. The walkthrough that uses these folders is
[Getting started](../docs/tutorials/getting-started.md); what each rule
protects you from is in the [explanation guides](../docs/explanation/README.md).
