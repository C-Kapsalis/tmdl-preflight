# tmdl-preflight

**Preflight checks — and auto-fixes — for Power BI semantic models saved in
TMDL format (PBIP folders).**

For most of Power BI's life, the semantic model was a binary `.pbix` blob:
un-diffable, un-reviewable, un-testable. PBIP and TMDL changed that — the
model is now a folder of plain-text files, which means it can finally be
tested like code. But nothing ships that testing layer: a duplicate
`lineageTag` left behind by a copy-pasted table file sails through Power BI
Desktop and every code review, then kills the deployment days later with
*"an object with that lineage tag already exists."* `tmdl-preflight` catches
that class of defect on your machine, and repairs the mechanical ones itself.

## Features

- **21 rules** over the failure modes that reject imports or silently corrupt
  results: tables missing their `ref table` line, tables with no partition,
  inline `#table` entity sources that force a composite model, duplicate lineage tags, unbalanced DAX delimiters, dangling
  `NAMEOF()` references, broken relationship endpoints, stray commas in
  field-parameter sources, string-typed bookmark fields, and more.
- **5 auto-fixers** for the defects whose repair is fully mechanical —
  applied via a check → fix → re-check loop that never lets a fixer vouch
  for itself.
- **Three entry points:** a CLI (`check`, `fix`, `rules`), a pytest fixture
  (`tmdl_preflight`), and a plain Python API (`check(Context(path), ruleset)`).
- **Zero runtime dependencies.** Standard library only; Python ≥ 3.10.
- **Surgical edits.** Fixers rewrite single lines or single JSON values, so
  every auto-fix diff is reviewable at a glance.

## Install

From a clone of this repository:

```console
pip install -e .
```

Add the test extra (`pip install -e ".[test]"`) if you want to run the
package's own suite.

## Quickstart

Point `check` at any PBIP folder — a project root, a `*.SemanticModel`
folder, a `definition` folder, or a `*.Report` folder. The repo ships a
small fictional bike-shop project you can try it on — [`examples/`](examples/)
has a clean copy and a pre-broken one. `bike-shop-broken` **will not open in
Power BI Desktop**: `Stores` lost its `ref table` line, its `lineageTag` is
copy-pasted from `Products`, `__Calendar`'s tag is a placeholder, and a
field-parameter row was deleted without its comma. `check` names each one,
with file, line, severity, and whether the fixer can handle it:

```console
$ tmdl-preflight check examples/bike-shop-broken
BikeShop.SemanticModel\definition\tables\Metric Selector.tmdl:45  F001 error: stray comma run (1 orphan comma(s)) in calculated partition source [Metric Selector (partition source)] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:17  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]
BikeShop.SemanticModel\definition\tables\Stores.tmdl  M006 error: table 'Stores' is defined in tables/ but has no 'ref table' line in model.tmdl, so it is not part of the model and Power BI will not open the project. Add: ref table Stores [Stores] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Stores.tmdl:3  M003 error: lineageTag 'e689596a-59ea-4b2c-a14d-48596a7b8c9d' duplicates the one on table Products (Products.tmdl:3) [table Stores] (auto-fixable)
BikeShop.SemanticModel\definition\tables\__Calendar.tmdl:4  M004 warning: lineageTag 'calendar-tag-TODO' is not a canonical UUID [table __Calendar] (auto-fixable)

tmdl-preflight: 3 error(s), 1 warning(s), 1 info(s)
```

Exit code 1. The four blockers carry the `(auto-fixable)` marker; the S001
style nudge does not (info never blocks). `check` is strictly read-only.
`fix` repairs what it safely can, then re-checks from disk:

```console
$ cp -r examples/bike-shop-broken /tmp/bike-shop
$ tmdl-preflight fix /tmp/bike-shop
fixed  M006: model.tmdl: + ref table Stores
fixed  M003: Stores.tmdl:3 (table Stores): 'e689596a-...' -> '1556d6dd-6012-4be4-8d04-6383081d6e02'
fixed  M004: __Calendar.tmdl:4 (table __Calendar): 'calendar-tag-TODO' -> '1e41940d-23a7-4d0f-b260-4c40ecdd16fa'
fixed  F001: Metric Selector.tmdl: removed 1 orphan comma(s) from 'Metric Selector' partition source

tmdl-preflight: 0 error(s), 0 warning(s), 1 info(s), 4 fix(es) applied
```

Exit code 0 — because the *re-check* came back clean of blockers, not
because fixers ran. The four blockers are gone and the project now opens in
Power BI Desktop; the S001 info line is yours to act on or ignore. Diff,
review, commit.

## Rules

| ID | Protects you from | Severity | Auto-fix |
|------|-------------------|----------|----------|
| M001 | missing `model.tmdl` / `tables/` folder (truncated exports, bad merges) | error | — |
| M002 | unreadable files, null bytes, unpaired ```` ``` ```` fences, missing table declarations | error | — |
| M003 | duplicate `lineageTag` values — the deployment target rejects the model | error | yes |
| M004 | placeholder / non-UUID `lineageTag` values | warning | yes |
| M005 | column `dataType` values the tabular engine does not accept | warning | — |
| D001 | unbalanced `()`, `{}`, `[]`, quotes in any DAX expression | error | — |
| D002 | `NAMEOF()` references to missing tables, columns, or measures | error | — |
| D003 | the same measure name declared in two tables (engine requires model-wide uniqueness) | error | — |
| R001 | relationships pointing at missing tables or columns | error | — |
| R002 | cardinality values other than `one`/`many` | error | — |
| R003 | two relationships over the same column pair (copy/paste or merge accident) | warning | — |
| R004 | unreviewed `bothDirections` cross-filters (ambiguous filter paths) | info | — |
| R005 | data tables with no relationships (load leftovers) | info | — |
| F001 | stray commas that make a field-parameter / calculated-table source unparseable | error | yes |
| B001 | bookmark `howCreated`/`ComparisonKind`/`Version` stored as strings — report loader rejects them | error | yes |
| B002 | bookmarks referencing renamed or deleted visuals | error | — |
| S001 | visible measures without a `formatString` | info | — |

Details, scopes and severity semantics: [docs/reference/rules.md](docs/reference/rules.md).
Print the same catalog from the tool: `tmdl-preflight rules` (or `--json`).

## Selecting rules and other flags

Both `check` and `fix` take the same options:

| Flag | Effect |
|---|---|
| `--select M003,B001` | run only these rules (ids or names, case-insensitive) |
| `--ignore S001` | run everything except these |
| `--strict` | exit nonzero on warnings as well as errors (`info` never blocks) |
| `--json` | machine-readable report (summary, fixes, violations) |

There is no config file in this release — scoping is per invocation.
Exit codes: `0` clean, `1` violations remain, `2` usage/path error.
Full details: [docs/reference/cli.md](docs/reference/cli.md).

## In pytest

Installing the package registers a pytest plugin; the `tmdl_preflight`
fixture makes model health an ordinary test:

```python
def test_model_is_deployable(tmdl_preflight):
    tmdl_preflight.assert_clean("src/Shop.SemanticModel")
```

`assert_clean` takes `select=`/`ignore=` sets, `strict=True`, and
`autofix=True` (repair, then assert on the re-check; also switchable via
`TMDL_PREFLIGHT_AUTOFIX=1` so CI stays read-only while developers repair
locally). `run()` returns the report without asserting. See
[docs/how-to/run-in-pytest.md](docs/how-to/run-in-pytest.md).

## How `fix` works

`fix` runs every selected rule, applies the fixers of the rules that failed,
then drops the parse cache and runs every rule **again** from disk — the run
only counts as clean if the re-check is clean. A fixer never gets to vouch
for itself: only repairs fully determined by the failure itself (a fresh
UUID, a deleted orphan comma, `"2"` → `2`) earn one, and everything that
requires human intent stays a plain failure. The full rationale:
[the imposition pattern](docs/explanation/imposition-pattern.md).

## Documentation

The docs follow the [Diátaxis](https://diataxis.fr) framework:

- **Tutorial** — [Getting started](docs/tutorials/getting-started.md):
  install, check the sample model, break it, repair it. ~10 minutes.
- **How-to guides** — [run in CI](docs/how-to/run-in-ci.md) ·
  [run inside pytest](docs/how-to/run-in-pytest.md) ·
  [run only the auto-fixable rules](docs/how-to/run-only-autofixable-rules.md) ·
  [add a custom rule](docs/how-to/add-a-custom-rule.md).
- **Reference** — [CLI](docs/reference/cli.md) (commands, flags, path
  resolution, exit codes, JSON schema) ·
  [rule catalog](docs/reference/rules.md) (every rule with scope and
  severity).
- **Release notes** — [what shipped in each version](RELEASE-NOTES.md).
- **Explanation** — [one guide per pitfall](docs/explanation/README.md):
  what it costs, how the rule detects it, and why the auto-fix (where one
  exists) is safe — plus the design pieces on the
  [imposition pattern](docs/explanation/imposition-pattern.md) and the
  [layered test model](docs/explanation/layered-testing.md).

## Contributing

Run the suite with `pip install -e ".[test]" && pytest`. New rules follow
the recipe in [How to add a custom rule](docs/how-to/add-a-custom-rule.md);
test them like the built-ins in `tests/test_rules_*.py` — copy the clean
fixture, break exactly one thing, assert the violation, and (for fixers)
assert that fix → re-check comes back clean and idempotent.

## License

MIT © 2026 Christoforos Kapsalis. See [LICENSE](LICENSE).
