# Getting started with tmdl-preflight

In this tutorial you will install tmdl-preflight, check a clean semantic
model, check a deliberately broken copy of the same model, repair the
mechanical defects with the auto-fixer, and learn to read the findings that
remain. It takes about ten minutes and assumes nothing beyond a working
Python 3.10+ installation.

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
├── bike-shop-clean/            <- every rule passes
│   ├── BikeShop.SemanticModel/
│   │   └── definition/
│   │       ├── model.tmdl
│   │       ├── relationships.tmdl
│   │       └── tables/
│   └── BikeShop.Report/
│       └── definition/
│           ├── pages/
│           └── bookmarks/
└── bike-shop-broken/           <- nine defects seeded on purpose
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

Exit code 0: the model is clean. `check` is strictly read-only — it never
touches your files.

## 4. Check the broken model

`bike-shop-broken` is the same model after a bad week: a table file was
copy-pasted, a field-parameter row was deleted carelessly, a bookmark was
hand-edited, a table was renamed without updating a relationship.
[`examples/README.md`](../../examples/README.md) lists every seeded defect;
here is what `check` makes of them:

```console
$ tmdl-preflight check examples/bike-shop-broken
BikeShop.Report\definition\bookmarks\spotlight-orders.bookmark.json  B002 error: bookmark captures visual 'b7c8d9e0f1a2', but no visual folder with that name exists under pages/. The visual was probably renamed or deleted after the bookmark was created, so the bookmark will silently stop working; restore the visual, re-create the bookmark, or delete it. [spotlight-orders.bookmark]
BikeShop.Report\definition\bookmarks\spotlight-revenue.bookmark.json  B001 error: howCreated at howCreated is the string 'User' (must be a JSON integer) [spotlight-revenue.bookmark] (auto-fixable)
BikeShop.Report\definition\bookmarks\spotlight-revenue.bookmark.json  B001 error: Version at explorationState.visualContainers.a1b2c3d4e5f6.filters.byExpr[0].filter.Version is the string '2' (must be a JSON integer) [spotlight-revenue.bookmark] (auto-fixable)
BikeShop.SemanticModel\definition\relationships.tmdl:13  R001 error: to-table 'Dates' does not exist in the model, so this relationship cannot deploy. The table was probably renamed or removed; update the relationship or restore the table. [relationship 4c9e5f6d]
BikeShop.SemanticModel\definition\tables\Calendar.tmdl:3  M004 warning: lineageTag 'calendar-table-tag-TODO' is not a canonical UUID [table Calendar] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Metric Selector.tmdl:45  F001 error: stray comma run (1 orphan comma(s)) in calculated partition source [Metric Selector (partition source)] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:17  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]
BikeShop.SemanticModel\definition\tables\Stores.tmdl:3  M003 error: lineageTag 'e689596a-59ea-4b2c-a14d-48596a7b8c9d' duplicates the one on table Products (Products.tmdl:3) [table Stores] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Stores.tmdl:5  D003 error: measure 'Revenue per Store' is also declared in table 'Sales Measures' (Sales Measures.tmdl:20). The tabular engine requires measure names to be unique across the whole model, so this model cannot deploy. Rename or remove one of the two. [Stores[Revenue per Store]]

tmdl-preflight: 7 error(s), 1 warning(s), 1 info(s)
```

Exit code 1. Every line names the file (and line where one exists), the rule id, the
severity, what is wrong, and — where the tool can repair it — the
`(auto-fixable)` marker. Five findings carry that marker; four do not.
That split is the whole design: a defect earns an auto-fix only when the
failure itself fully determines the repair.

## 5. Fix a copy

`fix` edits files in place, so work on a copy and keep the broken original
for rereading this tutorial:

```console
$ cp -r examples/bike-shop-broken /tmp/bike-shop
$ tmdl-preflight fix /tmp/bike-shop
fixed  M003: Stores.tmdl:3 (table Stores): 'e689596a-59ea-4b2c-a14d-48596a7b8c9d' -> '957c911a-8be2-487d-9db7-a5b0aa05426e'
fixed  M004: Calendar.tmdl:3 (table Calendar): 'calendar-table-tag-TODO' -> '022aad27-480e-432d-b1ca-c292bd5887b8'
fixed  F001: Metric Selector.tmdl: removed 1 orphan comma(s) from 'Metric Selector' partition source
fixed  B001: spotlight-revenue.bookmark.json: howCreated: 'User' -> 0
fixed  B001: spotlight-revenue.bookmark.json: explorationState.visualContainers.a1b2c3d4e5f6.filters.byExpr[0].filter.Version: '2' -> 2

BikeShop.Report\definition\bookmarks\spotlight-orders.bookmark.json  B002 error: bookmark captures visual 'b7c8d9e0f1a2', but no visual folder with that name exists under pages/. The visual was probably renamed or deleted after the bookmark was created, so the bookmark will silently stop working; restore the visual, re-create the bookmark, or delete it. [spotlight-orders.bookmark]
BikeShop.SemanticModel\definition\relationships.tmdl:13  R001 error: to-table 'Dates' does not exist in the model, so this relationship cannot deploy. The table was probably renamed or removed; update the relationship or restore the table. [relationship 4c9e5f6d]
BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:17  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]
BikeShop.SemanticModel\definition\tables\Stores.tmdl:5  D003 error: measure 'Revenue per Store' is also declared in table 'Sales Measures' (Sales Measures.tmdl:20). The tabular engine requires measure names to be unique across the whole model, so this model cannot deploy. Rename or remove one of the two. [Stores[Revenue per Store]]

tmdl-preflight: 3 error(s), 0 warning(s), 1 info(s), 5 fix(es) applied
```

Three things happened, in order:

1. every rule ran (`check`),
2. the fixers of the failed auto-fixable rules ran — the duplicate lineage
   tag was regenerated (the original in `Products.tmdl` was left alone),
   the placeholder tag became a real UUID, the orphan comma was deleted,
   and the two string-typed bookmark fields became integers,
3. every rule ran **again**, from disk, and the report you see is that
   re-check — which is why the four findings that need a human still
   appear and the run still exits 1.

That check → fix → re-check loop is the imposition pattern; see
[the explanation guide](../explanation/imposition-pattern.md) for why the
re-check is not optional. Running `fix` a second time applies zero fixes
and reports the same four findings — the fixers are idempotent.

Diff the copy against `examples/bike-shop-broken` before you move on: every
auto-fix is a one-line (or one-value) change, so the review is trivial.

## 6. Read what remains

Re-run `check` on the repaired copy:

```console
$ tmdl-preflight check /tmp/bike-shop
BikeShop.Report\definition\bookmarks\spotlight-orders.bookmark.json  B002 error: bookmark captures visual 'b7c8d9e0f1a2', but no visual folder with that name exists under pages/. [...]
BikeShop.SemanticModel\definition\relationships.tmdl:13  R001 error: to-table 'Dates' does not exist in the model, so this relationship cannot deploy. [...]
BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:17  S001 info: visible measure has no formatString [...]
BikeShop.SemanticModel\definition\tables\Stores.tmdl:5  D003 error: measure 'Revenue per Store' is also declared in table 'Sales Measures' [...]

tmdl-preflight: 3 error(s), 0 warning(s), 1 info(s)
```

These four stay manual on purpose. Each message tells you the problem, the
likely cause, and your options — but the *choice* is yours: does the
ship-date relationship retarget to `Calendar` or get deleted? Which of the
two `Revenue per Store` measures is the real one? Was the deleted visual
supposed to survive? A tool that guessed those answers would be repairing
symptoms while corrupting intent. Make the calls, edit the files, and
re-run `check` until you see what the clean model shows:

```console
$ tmdl-preflight check examples/bike-shop-clean

tmdl-preflight: 0 error(s), 0 warning(s), 0 info(s)
```

## 7. Explore the rest

```console
$ tmdl-preflight rules                                            # the full catalog
$ tmdl-preflight check examples/bike-shop-broken --select D003    # one rule only
$ tmdl-preflight check examples/bike-shop-broken --json           # machine-readable
$ tmdl-preflight check examples/bike-shop-broken --strict         # warnings fail too
```

## Where to go next

- Wire it into your pipeline: [Run tmdl-preflight in CI](../how-to/run-in-ci.md)
- Use it from your test suite: [Run rules inside pytest](../how-to/run-in-pytest.md)
- Understand what each rule protects you from: the
  [explanation guides](../explanation/README.md)
- Everything the CLI accepts: [CLI reference](../reference/cli.md)
