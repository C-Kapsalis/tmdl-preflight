# tmdl-preflight

**Preflight checks and auto-fixes for Power BI semantic models saved in
TMDL format (PBIP folders).**

For most of Power BI's life, the semantic model was a binary `.pbix` blob:
un-diffable, un-reviewable, un-testable. PBIP and TMDL changed that. The
model is now a folder of plain-text files, which means it can finally be
tested like code. But nothing ships that testing layer: a duplicate
`lineageTag` left behind by a copy-pasted table file sails through Power BI
Desktop and every code review, then kills the deployment days later with
*"an object with that lineage tag already exists."* `tmdl-preflight` catches
that class of defect on your machine, and repairs the mechanical ones itself.

## Features

- **37 rules** over the failure modes that reject imports or silently corrupt
  results: tables missing their `ref table` line, refs to tables that do not
  exist, tables with no partition, inline `#table` entity sources that force
  a composite model, duplicate lineage tags and object names, TMDL properties
  leaked into DAX, dangling `///` descriptions, DAX references to tables and
  columns that are gone, broken relationship endpoints and ambiguous active
  paths, stray or missing commas in field-parameter sources, bookmark and
  report-definition defects, and more.
- **10 auto-fixers** for the defects whose repair is fully mechanical,
  applied via a check → fix → re-check loop that never lets a fixer vouch
  for itself.
- **Surgical, verified edits.** Fixers rewrite single lines or single JSON
  values in place, keep the file's newline style, and prove each edit (for
  JSON, by parsing both versions) before writing, so every auto-fix diff is
  reviewable at a glance.
- **Built for adoption on real models:** a project config file, documented
  exemptions with expiry dates, and a baseline so CI fails only on *new*
  violations.
- **CI-ready output:** text, JSON, GitHub annotations, SARIF 2.1.0 and
  Markdown, plus a pre-commit hook and an example GitHub Actions workflow.
- **Four entry points:** a CLI (`check`, `fix`, `baseline`, `stats`,
  `rules`), a pytest fixture (`tmdl_preflight`), and a plain Python API
  (`check(Context(path), ruleset)`).
- **Zero runtime dependencies.** Standard library only; Python ≥ 3.10
  (TOML config files need 3.11+; the JSON form works everywhere).

## Install

From a clone of this repository:

```console
pip install -e .
```

Add the test extra (`pip install -e ".[test]"`) if you want to run the
package's own suite.

## Quickstart

Point `check` at any PBIP folder: a project root, a `*.SemanticModel`
folder, a `definition` folder, or a `*.Report` folder. The repo ships a
small fictional bike-shop project you can try it on. [`examples/`](examples/)
has a clean copy and a pre-broken one. `bike-shop-broken` **will not open in
Power BI Desktop**: `Stores` lost its `ref table` line, its `lineageTag` is
copy-pasted from `Products`, `__Calendar`'s tag is a placeholder, and a
field-parameter row was deleted without its comma. `check` names each one,
with file, line, severity, and whether the fixer can handle it:

```console
$ tmdl-preflight check examples/bike-shop-broken
BikeShop.SemanticModel\definition\tables\Metric Selector.tmdl:45  F001 error: stray comma run (1 orphan comma(s)) in calculated partition source [Metric Selector (partition source)] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:21  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]
BikeShop.SemanticModel\definition\tables\Stores.tmdl  M006 error: table 'Stores' is defined in tables/ but has no 'ref table' line in model.tmdl, so it is not part of the model and Power BI will not open the project. Add: ref table Stores [Stores] (auto-fixable)
BikeShop.SemanticModel\definition\tables\Stores.tmdl:3  M003 error: lineageTag 'e689596a-59ea-4b2c-a14d-48596a7b8c9d' duplicates the one on table Products (Products.tmdl:3) [table Stores] (auto-fixable)
BikeShop.SemanticModel\definition\tables\__Calendar.tmdl:4  M004 warning: lineageTag 'calendar-tag-TODO' is not a canonical UUID [table __Calendar] (auto-fixable)

scanned: 1 model, 6 tables, 22 columns, 6 measures, 4 relationships, 8 DAX expressions, 1 report
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

BikeShop.SemanticModel\definition\tables\Sales Measures.tmdl:21  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]

scanned: 1 model, 6 tables, 22 columns, 6 measures, 4 relationships, 8 DAX expressions, 1 report
tmdl-preflight: 0 error(s), 0 warning(s), 1 info(s), 4 fix(es) applied
```

Exit code 0, because the *re-check* came back clean of blockers, not
because fixers ran. The four blockers are gone and the project now opens in
Power BI Desktop; the S001 info line is yours to act on or ignore. Diff,
review, commit.

## Rules

| ID | Protects you from | Severity | Auto-fix |
|------|-------------------|----------|----------|
| M001 | missing `model.tmdl` / `tables/` folder (truncated exports, bad merges) | error | no |
| M002 | unreadable files, null bytes, unpaired ```` ``` ```` fences, missing table declarations, declarations the parser could not attach | error | no |
| M003 | duplicate `lineageTag` values; the deployment target rejects the model | error | yes |
| M004 | placeholder / non-UUID `lineageTag` values | warning | yes |
| M005 | column `dataType` values the tabular engine does not accept | warning | no |
| M006 | a table with no `ref table` line in `model.tmdl`, so Power BI Desktop never opens the project | error | yes |
| M007 | a table with no partition at all; Power BI Desktop crashes on open | error | no |
| M008 | an inline `#table(type table ...)` source, which forces a composite model and blocks open | error | no |
| M009 | a table literally named "Measures", a reserved name Power BI refuses to open | error | no |
| M010 | a TMDL property line (`lineageTag:`, `isHidden`, `annotation` ...) inside an expression body | error | no |
| M011 | a simple property written after an `annotation`/`changedProperty`/`extendedProperty` block | warning | yes |
| M012 | duplicate table names (case-insensitive), duplicate columns or measures in one table, a measure named like a column of its table | error | no |
| M013 | a `///` description followed by a blank line (error) or the end of the file (warning) | error | yes |
| M014 | a calculation group in a model without `discourageImplicitMeasures` | error | no |
| M015 | a `ref table` line naming a table no file defines | error | no |
| D001 | unbalanced `()`, `{}`, `[]`, quotes in any DAX expression | error | no |
| D002 | `NAMEOF()` references to missing tables, columns, or measures | error | no |
| D003 | the same measure name declared in two tables (engine requires model-wide uniqueness, case-insensitive) | error | no |
| D004 | DAX references to tables or qualified columns that do not exist (error); unresolved bare `[X]` (warning) | error | no |
| D005 | the same `VAR` declared twice in one scope | error | no |
| R001 | relationships pointing at missing tables or columns, or missing an endpoint | error | no |
| R002 | cardinality values other than `one`/`many` | error | no |
| R003 | two relationships over the same column pair (copy/paste or merge accident) | warning | no |
| R004 | unreviewed `bothDirections` cross-filters (ambiguous filter paths) | info | no |
| R005 | data tables with no relationships (load leftovers) | info | no |
| R006 | more than one active relationship between the same two tables | error | no |
| R007 | relationships created by Desktop's autodetection (`AutoDetected_*` ids) | warning | no |
| F001 | stray commas that make a field-parameter / calculated-table source unparseable | error | yes |
| F002 | a missing comma between two rows of a `{ (...), (...) }` constructor | error | yes |
| F003 | a trailing comma before the constructor's closing `}` | error | yes |
| F004 | rows of one constructor with different numbers of values | warning | no |
| B001 | bookmark `howCreated`/`ComparisonKind`/`Version` stored as strings; the report loader rejects them | error | yes |
| B002 | bookmarks referencing renamed or deleted visuals | error | no |
| B003 | bookmark `options` keys outside the report schema | error | yes |
| B004 | `definition.pbir` pointing at a missing model, `pages.json` naming missing pages, unparseable `visual.json` | error | no |
| S001 | visible measures without a `formatString` | info | no |
| S002 | visible measures without a real `///` description | info | no |

Details, scopes, examples and severity semantics: see the rule catalog in
the [documentation](#documentation) below. Print the same catalog from the
tool: `tmdl-preflight rules` (or `--json`).

## Selecting rules and other flags

`check` and `fix` take the same options:

| Flag | Effect |
|---|---|
| `--select M003,B001` | run only these rules (ids or names, case-insensitive) |
| `--ignore S001` | run everything except these |
| `--strict` | exit nonzero on warnings as well as errors (`info` never blocks) |
| `--format FMT` | `text` (default), `json`, `github`, `sarif` or `markdown` |
| `--json` | same as `--format json` (summary, fixes, violations, scanned counts) |
| `--baseline FILE` | fail only on violations not recorded in the baseline |
| `--config FILE` / `--profile NAME` / `--no-config` | choose the configuration |

Exit codes: `0` clean, `1` violations remain, `2` usage, path,
configuration or baseline error. The text report ends with a one-line
`scanned:` summary so a run that silently looked at nothing is obvious.

## Configuration

Project settings live in `[tool.tmdl-preflight]` in `pyproject.toml`, in a
`.tmdl-preflight.toml`, or in a `.tmdl-preflight.json` (the JSON form works
on Python 3.10; TOML needs 3.11+). The nearest file in the checked folder or
its parents wins; the search stops at the repository root.

```toml
[tool.tmdl-preflight]
ignore = ["S002"]
exclude = ["**/tables/Legacy*.tmdl"]   # project-relative globs

[tool.tmdl-preflight.severity_overrides]
R007 = "error"

[tool.tmdl-preflight.rules.S002]
min_length = 20

[[tool.tmdl-preflight.exemptions]]
rule = "R004"
object = "relationship 1f6f2b3a"
reason = "bidirectional on purpose: product slicers filter stores"
until = "2026-12-31"                    # after this date it is reported again

[tool.tmdl-preflight.profiles.ci]
strict = true                           # tmdl-preflight check . --profile ci
```

Unknown keys, unknown rule ids and wrongly typed options are errors (exit
2), never silent no-ops. An exemption without a `reason` is rejected.

## Baselines

Adopting the tool on an existing model? Record what fails today and gate on
new violations only:

```console
$ tmdl-preflight baseline .                     # writes .tmdl-preflight-baseline.json
$ tmdl-preflight check . --baseline .tmdl-preflight-baseline.json
$ tmdl-preflight baseline . --update            # drop entries you have fixed
```

The baseline stores rule id, project-relative file and object (no line
numbers), so unrelated edits do not churn it. `--update` only ever removes
entries; `--update --accept-new` is the explicit way to grow it. A baseline
is never written from a `--select`/`--ignore` run or while files fail to
parse, and the defects that stop a model from opening (M003, M006, M007,
M010, M015, R006) can never be baselined.

## Inventory

`tmdl-preflight stats <path>` (or `--json`) prints counts: tables, columns,
measures, relationships, partitions by kind, calculation groups, field
parameters, descriptions, display folders, and so on. No thresholds, just
numbers worth watching in a pull request.

## In CI and pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/c-kapsalis/tmdl-preflight
    rev: v1.1.0
    hooks:
      - id: tmdl-preflight
```

[`examples/ci/`](examples/ci/) has a GitHub Actions workflow that annotates
the pull request (`--format github`) and uploads SARIF for code scanning,
plus an example configuration file.

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
locally). `run()` returns the report without asserting. See the "run in
pytest" how-to guide in the [documentation](#documentation) below.

## How `fix` works

`fix` runs every selected rule, applies the fixers of the rules that failed,
then drops the parse cache and runs every rule **again** from disk; the run
only counts as clean if the re-check is clean. A fixer never gets to vouch
for itself: only repairs fully determined by the failure itself (a fresh
UUID, a deleted orphan comma, `"2"` becoming `2`) earn one, and everything
that requires human intent stays a plain failure. Each fixer edits the file
text surgically and proves the edit before writing it; if it cannot, it
leaves the file alone and the violation stays on the report. The full rationale is in
the "imposition pattern" explanation page linked below.

## Documentation

The full documentation, organized with the
[Diátaxis](https://diataxis.fr) framework (a tutorial, how-to guides, a
reference, and explanation pages, including the rule catalog and the
imposition-pattern rationale mentioned above), is published on Read the Docs at
<https://tmdl-preflight-documentation.readthedocs.io/en/latest/>.

Release notes for each version are in [RELEASE-NOTES.md](RELEASE-NOTES.md).

## Part of a small family of Power BI tools

tmdl-preflight is the validator a few related, independently installable
tools build on; a team adopts whichever ones it needs, not all of them.

- [`pbip-model-forge`](https://github.com/C-Kapsalis/pbip-model-forge):
  builds a sample Power BI model from a plain-language description, and
  gates every build on this tool.
- [`tmdl-drift-doctor`](https://github.com/C-Kapsalis/tmdl-drift-doctor):
  keeps many derived models in sync with one shared template.
- [`pbi-plot-styler`](https://github.com/C-Kapsalis/pbi-plot-styler): keeps
  report visuals on-brand as measures are added.
- [`BI-report-template-site`](https://github.com/C-Kapsalis/BI-report-template-site):
  not a tool, a documentation paradigm demonstrating what Diátaxis-style
  documentation looks like applied to a Power BI report.

## Contributing

Run the suite with `pip install -e ".[test]" && pytest`. New rules follow
the recipe in [CONTRIBUTING.md](CONTRIBUTING.md); test them like the
built-ins in `tests/test_rules_*.py`: every rule test plants a defect in a
copy of the clean fixture and asserts the rule fires, next to a clean-case
test; for fixers, assert that fix then re-check comes back clean and
idempotent.

## License

MIT © 2026 Christoforos Kapsalis. See [LICENSE](LICENSE).
