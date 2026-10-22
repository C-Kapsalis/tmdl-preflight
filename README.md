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

- **115 rules** over the failure modes that reject imports or silently corrupt
  results: duplicate lineage tags and object names, TMDL properties leaked
  into DAX, dangling `///` descriptions, tables with no partition, inline
  `#table` entity sources that force a composite model, DAX references to
  tables and columns that are gone, broken relationship endpoints and
  ambiguous active paths, stray or missing commas in field-parameter
  sources, bookmark and report-definition defects, and more. Rules that
  encode one team's conventions (measure placement, naming, ratchets) are
  opt-in, and project contracts (required objects, pinned relationships,
  field-parameter registrations) are declared in the configuration. The
  full catalog is generated into [`docs/rules.md`](docs/rules.md).
- **22 auto-fixers** for the defects whose repair is fully mechanical,
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
  `rules`, `manifest`, `schema-check`, `refs` and more), a pytest fixture (`tmdl_preflight`), and a plain Python API
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
Power BI Desktop**: `Stores` copies its `lineageTag` from `Products`, which
Desktop refuses ("An object with lineage-tag ... already exists in the
collection"). It has three more defects: `Stores` lost its `ref table`
line, `__Calendar`'s tag is a placeholder, and a field-parameter row was
deleted without its comma. `check` names each one, with file, line,
severity, and whether the fixer can handle it:

```console
$ tmdl-preflight check examples/bike-shop-broken
BikeShop.SemanticModel/definition/tables/Metric Selector.tmdl:45  F001 error: stray comma run (1 orphan comma(s)) in calculated partition source. Power BI Desktop still opens the model, but every visual that uses this table fails ('Error fetching data for this visual'). Delete the orphan comma(s) (the auto-fix does). [Metric Selector (partition source)] (auto-fixable)
BikeShop.SemanticModel/definition/tables/Sales Measures.tmdl:21  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]
BikeShop.SemanticModel/definition/tables/Stores.tmdl  M006 warning: table 'Stores' is defined in tables/ but has no 'ref table' line in model.tmdl. Power BI Desktop still loads the table, but model.tmdl is out of step with tables/. Add: ref table Stores [Stores] (auto-fixable)
BikeShop.SemanticModel/definition/tables/Stores.tmdl:3  M003 error: lineageTag 'e689596a-59ea-4b2c-a14d-48596a7b8c9d' duplicates the one on table Products (Products.tmdl:3) [table Stores] (auto-fixable)
BikeShop.SemanticModel/definition/tables/__Calendar.tmdl:4  M004 warning: lineageTag 'calendar-tag-TODO' is not a canonical UUID [table __Calendar] (auto-fixable)

scanned: 1 model, 6 tables, 22 columns, 6 measures, 4 relationships, 8 DAX expressions, 1 report
tmdl-preflight: 2 error(s), 2 warning(s), 1 info(s)
```

Exit code 1. The four defects carry the `(auto-fixable)` marker; the S001
style nudge does not (info never blocks). `check` is strictly read-only.
`fix` repairs what it safely can, then re-checks from disk (`fix --dry-run`
shows the plan without writing; `fix --check` writes nothing and exits with
the number of objects the selected fixers would act on):

```console
$ cp -r examples/bike-shop-broken /tmp/bike-shop
$ tmdl-preflight fix /tmp/bike-shop
fixed  M006: model.tmdl: + ref table Stores
fixed  M003: Stores.tmdl:3 (table Stores): 'e689596a-...' -> '1556d6dd-6012-4be4-8d04-6383081d6e02'
fixed  M004: __Calendar.tmdl:4 (table __Calendar): 'calendar-tag-TODO' -> '1e41940d-23a7-4d0f-b260-4c40ecdd16fa'
fixed  F001: Metric Selector.tmdl: removed 1 orphan comma(s) from 'Metric Selector' partition source

BikeShop.SemanticModel/definition/tables/Sales Measures.tmdl:21  S001 info: visible measure has no formatString, so it renders with the engine's default formatting. Add a formatString, or run with --ignore S001 if your formatting strategy lives elsewhere. [Sales Measures[Units Sold]]

scanned: 1 model, 6 tables, 22 columns, 6 measures, 4 relationships, 8 DAX expressions, 1 report
tmdl-preflight: 0 error(s), 0 warning(s), 1 info(s), 4 fix(es) applied
```

Exit code 0, because the *re-check* came back clean, not because fixers
ran. Power BI Desktop opened the fixed copy and showed its data (Windows,
2026-10-18); the S001 info line is yours to act on or ignore. Diff, review,
commit.

## Rules

| ID | Protects you from | Severity | Auto-fix |
|------|-------------------|----------|----------|
| M001 | missing `model.tmdl` / `tables/` folder (truncated exports, bad merges) | error | no |
| M002 | unreadable files, null bytes, unpaired ```` ``` ```` fences, missing table declarations, declarations the parser could not attach | error | no |
| M003 | duplicate `lineageTag` values; Power BI Desktop refuses to open the model | error | yes |
| M004 | placeholder / non-UUID `lineageTag` values (Desktop still opens the model) | warning | yes |
| M005 | column `dataType` values the tabular engine does not accept | warning | no |
| M006 | a table file with no `ref table` line in `model.tmdl` (Desktop still loads it, but the list is out of step) | warning | yes |
| M007 | a table with no partition at all; Power BI Desktop crashes on open | error | no |
| M008 | an inline `#table(type table ...)` source, which forces a composite model and blocks open | error | no |
| M009 | a table literally named "Measures", a reserved name Power BI refuses to open | error | no |
| M010 | a TMDL property line (`lineageTag:`, `isHidden`, `annotation`, `kpi` ...) inside an expression body | error | no |
| M011 | a simple property written after a nested section (`annotation`, `kpi`, `detailRows`, `formatStringDefinition` ...) | error | yes |
| M012 | duplicate table names (case-insensitive), duplicate columns or measures in one table, a measure named like a column of its table | error | no |
| M013 | a `///` description followed by a blank line or the end of the file | error | yes |
| M014 | a calculation group in a model without `discourageImplicitMeasures` | error | no |
| M015 | a `ref table` line naming a table no file defines | error | no |
| M016 | missing `database.tmdl` or required table files, null bytes, whitespace-only fenced measures, one-tab root comments (CRLF check opt-in) | error | no |
| M017 | structure lines indented with four spaces instead of tabs | error | no |
| M018 | the same annotation name twice in one scope of `model.tmdl` | error | no |
| M019 | a `queryGroup:` reference to a folder `model.tmdl` never declares | error | yes |
| M020 | a calculated column declared with `=` but no expression | error | no |
| M021 | Q&A linguistic metadata in `cultures/` bound to a table that no longer exists | error | yes |
| M022 | a `diagramLayout.json` that is not the blank "All tables" layout (opt-in) | warning | yes |
| P001 | a `refreshPolicy` placed after its partition, with out-of-domain values, a `sourceExpression` that differs from the partition source, or an unwindowed source | error | yes (unsafe: only when selected; copies the partition source, adds the policies P002 reports missing) |
| P002 | an incremental-refresh-eligible fact with no `refreshPolicy` and no backlog entry (opt-in; `refresh_policy` config) | warning | via P001 |
| C001 | a required table (format calculation group, helper table ...) or required measure is missing (configured) | error | no |
| C002 | a declared object contract broke: a table, column or measure is gone, a key changed type, a DAX shape changed | error | no |
| C003 | a declared relationship contract broke: an unsanctioned axis edge, a guard that no longer matches the graph, a pinned edge changed | error | no |
| C004 | a declared field-parameter registration broke: a missing label, an ordinal outside its gap, a duplicate ordinal | error | no |
| C005 | a declared measure-reference contract broke (a helper names a table it must not, a consumer skips its partner helper, a ratio divides a raw measure) | error | no |
| C006 | a cost ratio over a re-allocated count is not wrapped in its window guard, or the guard/boundary drifted (configured) | error | no |
| C007 | a count flag compared with `= 1` or a boolean, or a boolean flag compared with a number (configured) | error | no |
| C008 | a filter that must stay on one arm of a blended measure moved, spread or changed literals (configured) | error | no |
| C009 | reach-guard helpers that disagree on their dimension list or key a table by the wrong column (configured) | error | no |
| C010 | a grain guard that misses a blocked table or axis column, or blocks a conformed one (configured) | error | no |
| C011 | a grain-policy exception that is not narrow (configured) | error | no |
| C012 | a missing format or time-intelligence calculation-group table (opt-in) | error | no |
| D001 | unbalanced `()`, `{}`, `[]`, quotes in any DAX expression; a clean share under `min_success_rate`; a model with no measures (warning) | error | no |
| D002 | `NAMEOF()` references to missing tables, columns or measures, unparseable field-parameter rows, names spelled with other casing | error | no |
| D003 | the same measure name declared in two tables (engine requires model-wide uniqueness, case-insensitive) | error | no |
| D004 | DAX references to tables or qualified columns that do not exist, or spelled with other casing (error); unresolved or ambiguous bare `[X]` (warning) | error | yes (unsafe: only when selected; removes generated `ISFILTERED('<missing table>') \|\|` lines) |
| D005 | the same `VAR` declared twice in one scope | error | no |
| D010 | no calculated-table, calculation-item or format-string DAX at all (opt-in sanity floor) | warning | no |
| D011 | a "Daily" calculation item that averages ratios per day | error | no |
| D012 | an OR chain longer than 60 terms in one VAR | error | no |
| X001 | two facts compared on a surrogate key whose dimension has several rows per entity (configured keys) | error | no |
| R001 | relationships pointing at missing tables or columns, missing an endpoint, or spelled with other casing | error | no |
| R002 | cardinality values other than `one`/`many` | error | no |
| R003 | two relationships over the same column pair (copy/paste or merge accident) | warning | no |
| R004 | unreviewed `bothDirections` cross-filters (ambiguous filter paths) | info | no |
| R005 | data tables with no relationships (load leftovers) | info | no |
| R006 | more than one active relationship between the same two tables | error | no |
| R007 | relationships created by Desktop's autodetection (id contains `autodetected`) | error | yes (unsafe: only when selected or `fix_autodetected_relationships`) |
| R008 | a fact table with no active relationship to the conformed dimension (configured; ratchet) | error | no |
| R009 | no `relationships.tmdl`, or one without a complete relationship (opt-in) | warning | no |
| R010 | a cycle of three or more tables over active relationships | info | no |
| R011 | fact tables with no relationship to the calendar (coverage under 90%) | warning | no |
| R012 | a calendar relationship that is not many-to-one | warning | no |
| R013 | a calendar missing Date/Year/Quarter/Month/Week/Day (opt-in) | info | no |
| R014 | a `_` dimension with no key-like column (opt-in) | info | no |
| R015 | a cohort calendar that does not reach a fact carrying its subject within two hops | error | no |
| R016 | an anchor calendar (`__...Calendar`) that filters nothing | error | no |
| F001 | stray commas in a field-parameter / calculated-table source; the model opens but its visuals fail | error | yes |
| F002 | a missing comma between two rows of a `{ (...), (...) }` constructor | error | yes |
| F003 | a trailing comma before the constructor's closing `}` | error | yes |
| F004 | rows of one constructor with different numbers of values | error | no |
| F005 | a field-parameter row without its category value (configured tables) | error | no |
| F006 | the same row twice in one field parameter | error | yes |
| F007 | sibling field parameters of one family that list different fields | error | yes |
| F008 | field-parameter rows all wider or narrower than the declared `ValueN` columns | error | no |
| F009 | drilldown levels (`y-Selector 1..N`) that list different dimensions, or a plot-specific table that adds one | error | no |
| F010 | a display name with different categories across sibling field parameters (opt-in; `fieldparam retag` fixes all siblings at once) | error | no |
| F011 | a numbered axis row (`x-Selector N`, `y-Selector N`) with no category value (opt-in) | error | no |
| F012 | measures and dimensions no axis exposes, helpers an axis does expose (opt-in) | info | no |
| F013 | a measure parked on a field-parameter table | error | no |
| F014 | a selector SWITCH branch that calls a measure that no longer exists | error | yes |
| F015 | an axis table that is not an import-mode `("label", NAMEOF(...))` field parameter (opt-in) | info | no |
| A001 | the category-mapping table or one of its key columns is missing (opt-in) | error | no |
| A002 | inventory of axis group ids and mapping-table relationships (opt-in) | info | no |
| A003 | an account-filterable category whose mapping rows lack the account groups (opt-in) | error | yes |
| A004 | `f-All` gate chains that disagree, name missing measures, miss a category, or use inert or over-broad literals (opt-in; baseline) | error | no |
| A005 | an `f-` filter measure that fits no known shape (opt-in) | warning | no |
| B001 | bookmark `howCreated`/`ComparisonKind`/`Version` stored as strings; the report loader rejects them | error | yes |
| B002 | bookmarks referencing renamed or deleted visuals | error | no |
| B003 | bookmark `options` keys outside the report schema | error | yes |
| B004 | `definition.pbir` pointing at a missing model, `pages.json` naming missing pages, unparseable `visual.json` | error | no |
| B005 | `pages.json` missing, with an unexpected `$schema`, or without a `pageOrder` list (opt-in) | error | no |
| B006 | a `HierarchyLevel` binding with its `Level` inside the `Expression`, or missing either part | error | no |
| L001 | a role without `modelPermission: read`, or a `tablePermission` with no filter | error | no |
| L002 | a row filter that calls `USERNAME()` instead of `USERPRINCIPALNAME()` | error | no |
| L003 | an `IN VALUES(...)` row filter that does not restrict the mapping table to the signed-in user | error | no |
| L004 | a visible user-mapping table (a `UserPrincipalName` column) | error | no |
| L005 | a relationship to the user-mapping table | error | no |
| L006 | RLS inventory and posture (opt-in) | info | no |
| S001 | visible measures without a `formatString` | info | no |
| S002 | visible measures without a real `///` description | info | no |
| S003 | a visible measure whose name gives a format-picking calculation group nothing to go on (opt-in) | info | no |
| S004 | ticket numbers (`#365`) in model comments above the recorded floor (opt-in ratchet) | error | no |
| S005 | a measure that resolves to too few decimals through the format calculation group (configured expectations) | error | no |
| O001 | a helper measure in a user-only (`#`) table (opt-in) | warning | no |
| O002 | a helper measure in the wrong table for its kind (opt-in; `profile = "lenient"` for infos) | warning | no |
| O003 | a user-facing measure parked in a dimension or helper table (opt-in) | warning | no |
| O004 | a user-facing measure homed on a fact table (opt-in) | warning | no |
| O005 | measures on a dimension table (opt-in) | info | no |
| O006 | a measures table with no measures (opt-in) | info | no |
| N020 | fewer `_` dimension tables than the template's floor (opt-in, disabled by default) | warning | no |
| O007 | a fact table no measure reads (opt-in ratchet) | error | no |
| O008 | an intermediary helper (`-Name`) without a display folder (opt-in) | warning | no |
| O009 | a visible helper measure not on the always-visible list (opt-in) | warning | yes |
| O010 | helper measures nothing references, and the most used ones (opt-in) | info | no |
| O011 | a hidden user-facing measure (opt-in) | error | no |
| O012 | user-facing measures without a display folder (opt-in) | info | no |
| O013 | user-facing measures without a description of at least 10 characters (opt-in) | info | no |
| O014 | table description coverage (opt-in) | info | no |
| O015 | a fact table user-facing measures read but no `f-` filter measure does (opt-in) | error | no |

Details, scopes, examples and severity semantics: see the generated
[`docs/rules.md`](docs/rules.md) and the rule catalog in the
[documentation](#documentation) below. Print the same catalog from the
tool: `tmdl-preflight rules` (or `--json`, or `--format markdown --out
FILE`, with `--check` to fail when a committed copy is stale). Opt-in rules
run only when named in `--select` or the configuration's `select`; the
generated catalog lists the whole opt-in set as a `select` line you can
paste into your configuration file.

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
exclude = ["**/*_backup*/**"]          # globs relative to the folder you scan

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
parse, and the defects that stop a model from opening (M003, M007, M010,
M015, R006) can never be baselined.

## Inventory

`tmdl-preflight stats <path>` (or `--json`) prints counts: tables, columns,
measures, relationships, partitions by kind, calculation groups, field
parameters, descriptions, display folders, and so on. No thresholds, just
numbers worth watching in a pull request. `stats --measures` adds how the
measures are organised: user-facing vs helper names, helper kinds, which
measures a field parameter surfaces, the busiest tables, and how many
dash-prefixed helpers carry a description.

`tmdl-preflight report complexity|nameof|relationships <path>` prints the
measure-length distribution with threshold suggestions, the NAMEOF inventory
(with the broken references and per-table counts), or the relationship
topology (cardinalities, both-direction filters, hubs, unrelated tables).
`tmdl-preflight format-resolve <path> --name NAME [--compare NAME2]` shows
the format a measure name gets from a format calculation group on every
axis the group branches on, before a rename ships.

`tmdl-preflight grain <path> --cost-fact T --backend-fact T ...` works out
from the relationship graph which dimensions can filter both sides of a
ratio (conformed, cost-only, backend-only, partial, neither); `--check
--guard-table T --guard-measure M` confirms the guard blocks every
non-conformed dimension, and `--emit-config` prints the lists for C010.

`tmdl-preflight info --categories <path> [--json]` decodes the encoded
category-mapping table and lists, per group id, the analysis categories it
belongs to, and per fact table the categories its measures are offered under
(the relation is many-to-many).
`tmdl-preflight fieldparam retag <files> --names N1,N2 --from OLD --to NEW`
moves the named rows to another category in every sibling table at once; if
any name is not found live under OLD it writes nothing.

`tmdl-preflight manifest <Model.SemanticModel> [--check] [--targets FILE]`
writes a deterministic JSON manifest (tables with their role, columns,
measures, the warehouse table each partition reads, relationships) for the
pipelines next to the model; `--check` fails when the committed copy is stale,
and a targets file pins the warehouse project and dataset each model must
declare. `tmdl-preflight schema-check --manifest M --schema SNAPSHOT
[--strict]` compares it with a schema snapshot you export (model columns the
warehouse lost fail; columns the model does not import are informational), and
`schema-check --sql-dir DIR --entries FILE` proves from view SQL files that the
views expose the columns a model needs. Nothing connects to a warehouse.

`tmdl-preflight live <Model.SemanticModel> --workspace ID --dataset ID
[--checks ...]` is the one command that talks to the Power BI service: it
asks the published dataset whether its tables hold rows (a row-limit
parameter left at `LIMIT 1` imports one row per table), whether measures
evaluate, whether the last refresh succeeded and the data is fresh, and runs
a best-practice pass over the published metadata. It signs in as a service
principal (`PBI_TENANT_ID`, `PBI_CLIENT_ID`, `PBI_CLIENT_SECRET`) or, with
the optional `msal` package, interactively; credentials are never stored.
It refuses to run when the dataset name does not match the local model.
`--record DIR` saves every response and `--replay DIR` answers from such a
folder without any network access.

`tmdl-preflight refs NAME [PATH ...] [--files]` counts every place a table,
column or measure name appears, model side and report side, before a rename
or delete.

`tmdl-preflight comment-refs <path>` counts ticket references (`#365`) in
comments per model; `--floors FILE --tighten` lowers a ratchet file to
today's counts and never raises it (rule S004 gates on the same file).

`tmdl-preflight dead-facts <path>` lists the fact tables no measure reads.
`--capture FILE` records them as the floor the dead-fact gate compares
against (rule O007): a JSON object of model key to the sorted list of dead
fact tables, with the models that have none left out.

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
locally). `run()` returns the report without asserting. List models that are
still being brought into line under `advisory = [...]` in
`[tool.tmdl-preflight]`: a failing test whose parameters name such a model is
reported as an expected failure instead of failing the run (passes stay
passes, setup errors stay errors). See the "run in pytest" how-to guide in the
[documentation](#documentation) below.

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
