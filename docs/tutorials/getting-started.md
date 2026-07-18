# Getting started with tmdl-preflight

In this tutorial you will install tmdl-preflight, check a clean semantic
model, check a deliberately broken copy of the same model, repair the
blockers with the auto-fixer, and learn to read the one advisory finding
that remains. It takes about ten minutes and assumes nothing beyond a
working Python 3.10+ installation.

## 1. Install

From a clone of this repository (the `[test]` extra pulls in pytest, which
you will want for the later steps anyway):

```console
$ pip install -e ".[test]"
$ tmdl-preflight --version
tmdl-preflight 0.1.0
```

## 2. Meet the example models

The repository ships two copies of a small fictional PBIP project — the
Pedal & Sprocket Bike Co. model — under [`examples/`](../../examples/):

```
examples/
├── bike-shop-clean/            <- every rule passes; opens in Power BI
│   ├── BikeShop.SemanticModel/
│   │   └── definition/
│   │       ├── model.tmdl
│   │       ├── relationships.tmdl
│   │       └── tables/
│   │           ├── __Calendar.tmdl
│   │           ├── Metric Selector.tmdl
│   │           ├── Products.tmdl
│   │           ├── Sales Measures.tmdl
│   │           ├── Sales.tmdl
│   │           └── Stores.tmdl
│   └── BikeShop.Report/
└── bike-shop-broken/           <- same model, 4 blockers + 1 style nudge
```

This is exactly the folder shape Power BI Desktop produces when you save a
project as **PBIP** (*File → Save as → Power BI project files (.pbip)*), so
everything below works the same on your own models.

## 3. Check the clean model

Point `check` at the project root (it also accepts a `*.SemanticModel`
folder, a `definition` folder or a `*.Report` folder):

```console
$ tmdl-preflight check examples/bike-shop-clean

tmdl-preflight: 0 error(s), 0 warning(s), 0 info(s)
```

Exit code 0: the model is clean and opens in Power BI Desktop. `check` is
strictly read-only — it never touches your files.

## 4. Check the broken model

`bike-shop-broken` is the same project after a bad week: a table lost its
`ref table` line, a table file was copy-pasted, a lineage tag was hand-typed
as a placeholder, and a field-parameter row was deleted without its comma.
The result **will not open in Power BI Desktop**. Four of those defects are
blockers Power BI rejects on open; the fifth is a style nudge.
[`examples/README.md`](../../examples/README.md) lists exactly what is
seeded where; here is what `check` makes of it:

```console
$ tmdl-preflight check examples/bike-shop-broken
BikeShop.SemanticModel\definition\tables\Metric Selector.tmdl:45  F001 error: stray comma run (1 orphan comma(s)) in calculated partition source [Metric Selector (partition source)] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:17  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]
BikeShop.SemanticModel\definition\tables\Stores.tmdl  M006 error: table 'Stores' is defined in tables/ but has no 'ref table' line in model.tmdl, so it is not part of the model and Power BI will not open the project. Add: ref table Stores [Stores] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Stores.tmdl:3  M003 error: lineageTag 'e689596a-59ea-4b2c-a14d-48596a7b8c9d' duplicates the one on table Products (Products.tmdl:3) [table Stores] (auto-fixable)
BikeShop.SemanticModel\definition\tables\__Calendar.tmdl:4  M004 warning: lineageTag 'calendar-tag-TODO' is not a canonical UUID [table __Calendar] (auto-fixable)

tmdl-preflight: 3 error(s), 1 warning(s), 1 info(s)
```

Exit code 1. Every line names the file (and line where one exists), the rule
id, the severity, what is wrong, and — where the tool can repair it — the
`(auto-fixable)` marker:

- **M006** (`Stores` has no `ref table` line) — the table is not attached to
  the model, so Power BI refuses to open the project.
- **M003** (`Stores` copied `Products`' `lineageTag`) — the deploy target
  rejects duplicate lineage tags.
- **M004** (`__Calendar`'s `lineageTag` is a `TODO` placeholder, not a UUID).
- **F001** (a deleted field-parameter row left an orphan comma) — the
  calculated partition source no longer parses.
- **S001** (the visible measure `Units Sold` has no `formatString`) — an
  advisory nudge, **not** a blocker; the model opens fine without it.

Four findings carry the `(auto-fixable)` marker; S001 does not. That split
is the whole design: a defect earns an auto-fix only when the failure itself
fully determines the repair.

## 5. Fix a copy

`fix` edits files in place, so work on a copy and keep the broken original
for rereading this tutorial:

```console
$ cp -r examples/bike-shop-broken /tmp/bike-shop
$ tmdl-preflight fix /tmp/bike-shop
fixed  M006: model.tmdl: + ref table Stores
fixed  M003: Stores.tmdl:3 (table Stores): 'e689596a-59ea-4b2c-a14d-48596a7b8c9d' -> '1556d6dd-6012-4be4-8d04-6383081d6e02'
fixed  M004: __Calendar.tmdl:4 (table __Calendar): 'calendar-tag-TODO' -> '1e41940d-23a7-4d0f-b260-4c40ecdd16fa'
fixed  F001: Metric Selector.tmdl: removed 1 orphan comma(s) from 'Metric Selector' partition source

BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:17  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]

tmdl-preflight: 0 error(s), 0 warning(s), 1 info(s), 4 fix(es) applied
```

(The regenerated UUIDs are random, so yours will differ.) Three things
happened, in order:

1. every rule ran (`check`),
2. the fixers of the failed auto-fixable rules ran — the missing `ref table
   Stores` line was appended to `model.tmdl`, the duplicate lineage tag was
   regenerated (the original in `Products.tmdl` was left alone), the
   placeholder tag became a real UUID, and the orphan comma was deleted,
3. every rule ran **again**, from disk, and the report you see is that
   re-check.

Exit code 0 — because the *re-check* came back clean of blockers, not
because fixers ran. The four blockers are gone and **the project now opens
in Power BI Desktop**. Only the S001 info line remains, and info never
blocks. That check → fix → re-check loop is the imposition pattern; see
[the explanation guide](../explanation/imposition-pattern.md) for why the
re-check is not optional. Running `fix` a second time applies zero fixes and
reports the same single info line — the fixers are idempotent.

Diff the copy against `examples/bike-shop-broken` before you move on: every
auto-fix is a one-line (or one-value) change, so the review is trivial.

## 6. Read what remains

Re-run `check` on the repaired copy:

```console
$ tmdl-preflight check /tmp/bike-shop
BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:17  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]

tmdl-preflight: 0 error(s), 0 warning(s), 1 info(s)
```

Exit code 0. One finding stays, and it stays on purpose: S001 is an
`info`-level nudge, not a defect that stops the model from opening. The
message tells you the problem and your options, but the *choice* is yours —
give `Units Sold` a `formatString` if you format measures on the model, or
run with `--ignore S001` if your formatting strategy lives elsewhere (a
calculation group, a theme). A tool that forced one answer would be
imposing a house style, not repairing a break. Add a `formatString` yourself
and re-run `check` to see the same all-clear the clean model shows:

```console
$ tmdl-preflight check examples/bike-shop-clean

tmdl-preflight: 0 error(s), 0 warning(s), 0 info(s)
```

## 7. Explore the rest

```console
$ tmdl-preflight rules                                            # the full catalog
$ tmdl-preflight check examples/bike-shop-broken --select M006    # one rule only
$ tmdl-preflight check examples/bike-shop-broken --json           # machine-readable
$ tmdl-preflight check examples/bike-shop-broken --strict         # warnings fail too
```

## Where to go next

- Wire it into your pipeline: [Run tmdl-preflight in CI](../how-to/run-in-ci.md)
- Use it from your test suite: [Run rules inside pytest](../how-to/run-in-pytest.md)
- Understand what each rule protects you from: the
  [explanation guides](../explanation/README.md)
- Everything the CLI accepts: [CLI reference](../reference/cli.md)
