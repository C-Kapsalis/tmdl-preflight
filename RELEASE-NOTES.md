# Release notes

## Unreleased

This release adds a large set of rules and commands, with a test suite
that runs on fictional stand-in models.

### Severity changes

Power BI Desktop (Windows, installer build, 2026-10-18) was run on copies of
the example model with one defect each. Where that evidence and the
"stricter wins" policy disagree, the evidence wins.

| Rule | Was | Now | Why |
|---|---|---|---|
| M006 model-table-refs | error, "Power BI will not open the project" | warning, baselinable | Desktop opened a model whose only defect was a table file with no `ref table` line, loaded the table and kept its relationship. The fixer stays: model.tmdl should list every table file. |
| M004 lineage-format | warning | warning | Desktop opened a model whose only defect was a placeholder tag. |
| M003 lineage-duplicates | error | error | Desktop refused to open the model: "Failed to add a deserialized Table object into the model ... An object with lineage-tag '...' already exists in the collection." |
| F001 fieldparam-comma-runs | error | error, new message | Desktop opened the model, but every visual that uses the field parameter failed ("Error fetching data for this visual. Failed to move the data reader to the next row."). F002 and F003 are expected to behave the same; not observed. |
| M011 property-after-child-block | warning | error | The stricter verdict wins. |
| R007 autodetected-relationships | warning | error | Stricter: zero tolerance. Its id match widened to "contains autodetected, any case", and it gains an unsafe fixer that deletes the relationship blocks. |
| M013 dangling-description at end of file | warning | error | The stricter verdict wins. |

### New rules

| ID | Name | Severity | Auto-fix |
|---|---|---|---|
| M016 | tmdl-file-sanity | error | no |
| M017 | space-indentation | error | no |
| M018 | model-annotation-duplicates | error | no |
| M019 | undefined-query-group | error | yes |
| C001 | required-model-objects | error | no |
| C002 | model-contract-objects | error | no |
| C003 | model-contract-relationships | error | no |
| C004 | fieldparam-registration-contract | error | no |
| R008 | fact-conformed-dimension-join | error | no |
| F005 | fieldparam-category-column | error | no |
| S003 | format-inference-naming (opt-in) | info | no |
| S004 | comment-ticket-refs (opt-in) | error | no |
| O001 | user-only-table-purity (opt-in) | warning | no |
| O002 | helper-measure-placement (opt-in) | warning (info in the lenient profile) | no |
| O003 | user-facing-in-helper-tables (opt-in) | warning | no |
| O004 | measures-in-fact-tables (opt-in) | warning (info for advisories) | no |
| O005 | measures-in-dimension-tables (opt-in) | info | no |
| O006 | empty-measure-tables (opt-in) | info | no |
| O007 | dead-fact-tables (opt-in) | error | no |
| N020 | dimension-prefix-floor (opt-in, disabled by default) | warning | no |
| C012 | required-calc-groups (opt-in) | error | no |
| O008 | intermediary-helper-folder (opt-in) | warning | no |
| O009 | helper-measures-hidden (opt-in) | warning | yes |
| O010 | unused-helper-measures (opt-in) | info | no |
| O011 | user-facing-measure-visible (opt-in) | error | no |
| O012 | user-facing-display-folder (opt-in) | info | no |
| O013 | user-facing-measure-description (opt-in) | info | no |
| O014 | table-description-coverage (opt-in) | info | no |
| O015 | fact-table-filter-coverage (opt-in) | error | no |
| D010 | calc-dax-blocks-present (opt-in) | warning | no |
| D011 | calc-item-blind-average | error | no |
| X001 | cross-fact-multirow-key-join | error | no |
| C005 | measure-reference-contract | error | no |
| C006 | guarded-ratio-wrapper | error | no |
| C007 | typed-flag-predicates | error | no |
| C008 | measure-arm-scoped-filter | error | no |
| S005 | format-min-decimals | error | no |
| R009 | relationships-presence (opt-in) | warning | no |
| R010 | relationship-cycles | info | no |
| R011 | fact-calendar-coverage | warning | no |
| R012 | calendar-relationship-cardinality | warning | no |
| R013 | calendar-standard-columns (opt-in) | info | no |
| R014 | dimension-key-columns (opt-in) | info | no |
| R015 | cohort-calendar-reach | error | no |
| R016 | dead-anchor-calendar | error | no |
| C009 | reach-guard-helper-consistency | error | no |
| C010 | grain-guard-coverage | error | no |
| C011 | grain-policy-exception | error | no |
| D012 | dax-or-chain-depth | error | no |
| M020 | calculated-column-expression-present | error | no |
| F006 | fieldparam-duplicate-rows | error | yes |
| F007 | fieldparam-family-consistency | error | yes |
| F008 | fieldparam-arity | error | no |
| F009 | fieldparam-level-consistency | error | no |
| F010 | fieldparam-retag (opt-in) | error | no (`fieldparam retag` command) |
| F011 | fieldparam-category-required (opt-in) | error | no |
| F012 | fieldparam-coverage (opt-in) | info | no |
| F013 | field-parameter-table-no-measures | error | no |
| F014 | selector-branch-resolution | error | yes |
| F015 | field-parameter-partition-shape (opt-in) | info | no |
| P001 | refresh-policy-repair | error | yes (unsafe; also adds P002's missing policies) |
| M021 | culture-orphan-bindings | error | yes |
| M022 | diagram-layout-blank (opt-in) | warning | yes |
| B005 | pages-metadata-schema (opt-in) | error | no |
| B006 | hierarchy-level-binding-shape | error | no |
| L001 | rls-role-grammar | error | no |
| L002 | rls-username-function | error | no |
| L003 | rls-in-values-bypass | error | no |
| L004 | rls-mapping-table-hidden | error | no |
| L005 | rls-mapping-table-no-relationship | error | no |
| L006 | rls-inventory (opt-in) | info | no |
| P002 | refresh-policy-coverage (opt-in) | warning | via P001 |
| A001 | mapping-table-required-columns (opt-in) | error | no |
| A002 | mapping-table-info-reports (opt-in) | info | no |
| A003 | mapping-category-required-keys (opt-in) | error | yes |
| A004 | category-gate-coverage (opt-in, baseline) | error | no |
| A005 | f-measure-pattern (opt-in) | warning | no |

Rules that encode one team's conventions are **opt-in**: they run only when
named in `--select` or in the configuration's `select` (`rules` marks them).
Contract rules (C001-C008, R008, F005, S005, X001) read their contracts from the
configuration (`contracts` section or rule options) and report nothing
until configured.

### Changed rules

- **M002** pairs ``` fences by structure (a fence opens after `=` and closes
  on the next line that starts with backticks), so backticks inside a fenced
  string literal are no longer an "unpaired fence". It also reports a
  broken quoted name (`'Rider's Name'`, an apostrophe not doubled) as an
  error and an empty name as a warning.
- **M003** keeps a shared tag on the occurrence that most plausibly owns
  it: table files first, then `relationships.tmdl`, `expressions.tmdl`,
  `cultures/`, everything else (path, then line, inside a class). Before, a
  column could lose its tag to an expression because `expressions.tmdl`
  sorts before `tables/`. Expression occurrences now name the expression.
- **M010** recognises `kpi`, `detailRows` and `relatedColumnDetails`, and in
  DAX bodies matches a metadata keyword as a whole word whatever follows it
  (`displayFolder` with no colon counts). Shared expressions are checked
  too; in M bodies only a line shaped like a property counts.
- **M011** knows the nested sections `kpi`, `detailRows`,
  `relatedColumnDetails` and `formatStringDefinition`, resets at `role`
  declarations, and its fixer moves the line to the object's first property
  slot (right after the expression) instead of the end of the property
  section. Valued properties move like flags; a file that would need more
  than 200 moves is left alone.
- **M013** fix removes the run and the one blank line directly after it, at
  the end of the file too; blank lines before a run are never touched. New
  option `fix_mode = "attach"` deletes the blank lines between a
  description and its object instead, keeping the documentation.
- **R001** messages say "not found"; an endpoint spelled with different
  casing is an error; new option `min_endpoint_success_rate` (default 0.95)
  notes a low share of valid relationships (each broken endpoint is an
  error whatever the share, so the rate never adds a finding).
- Policy toggles (`require_fact_link`, `require_dimension_keys`, D010's
  `enabled`, ...) set to false skip their rule: the run lists it under
  `skipped` and reports nothing for it.
- A fixer marked unsafe can be opted into a blanket `fix` by its own option
  (R007 `fix_autodetected_relationships`).
- **D001** messages name the delimiter kind ("double quote", "single
  quote", "bracket", "parenthesis", "brace"). New option `min_success_rate`
  (default 0.90): when fewer measure and calculated-column expressions are
  clean, one extra error says so (each unbalanced expression stays an error
  whatever the share). A model with tables but no measures gets a warning.
- **D002** is rebuilt on the new `tmdl_preflight.nameof` module: quoted
  members (`Sales['Amount']`), double-quoted tables and dotted table names
  are accepted; an unparseable NAMEOF in a field-parameter row is an error;
  a table-qualified measure outside a field parameter is a warning ("use
  the bare form"); new option `excluded_tables`. Every unresolved-reference
  message contains "not found".
- **Casing mismatches are errors** (project decision): D002 and D004 report
  a table, column or measure spelled with different casing from its
  declaration as an error, although DAX itself resolves it.
- **D004** reports an unqualified `[X]` that names a measure declared in two
  or more tables as an ambiguous reference (warning), ignores TMDL property
  lines that leaked into an expression (M010 reports those), and gains a
  fixer marked unsafe: selected explicitly, it deletes whole generated
  `ISFILTERED('<missing table>') || ...` lines and nothing else.
- **NAMEOF** extraction ignores a malformed reference whose quoted table
  name contains a double quote.
- Names declared with trailing spaces inside quotes (`'Frame Size   '`) are
  read trimmed.

- **B002** reports a bookmark file that is not valid JSON.
- **B001-B003** skip bookmarks of archived report copies: paths containing
  `legacy/`, `_backup/`, `_legacy/`, `_b2/`, `DemoData.` or `demodata/`
  (project section `bookmarks.archive_markers`; an empty list scans them).
- `check`/`fix --select B003` on a path with no bookmark file exits 2
  (nothing scanned is not a clean result).
- `fix` exits 2 when a fixer refuses a repair it cannot prove (the file is
  left unchanged and listed under `refused_fixes`); other files are still
  repaired.

### Commands and options

- `exclude` globs match the path relative to the scan root (the folder you
  pass), as well as the path inside the PBIP item. Folders above the scan
  root never take part, so a checkout under `~/legacy/` is still scanned. A
  model or report whose files are all excluded is skipped before parsing.
  The JSON summary gains `files_scanned`, `excluded_files`, and `excluded`
  now counts skipped files as well as excluded violations. A partly
  excluded model is still parsed in full (so references into excluded files
  resolve); only its findings in excluded files are dropped.
- A bare `definition/` folder is accepted as a model when it holds
  `tables/`, `model.tmdl` or `expressions.tmdl`.
- `fix --dry-run` reports what would be repaired and writes nothing.
- `fix --clear-cache` deletes `<Model>.SemanticModel/.pbi/cache.abf` after
  lineage tags changed; without it the tool prints a hint when the cache
  exists.
- `grain <path> --cost-fact T --backend-fact T ... [--permit T] [--check
  --guard-table T --guard-measure M] [--emit-config]` derives conformed and
  blocked dimensions from the relationship graph (USERELATIONSHIP to a
  calendar counts) and checks a grain guard against it.
- `report complexity|nameof|relationships <path> [--json]`: read-only
  reports (measure length distribution and threshold suggestions, NAMEOF
  inventory, relationship topology).
- `format-resolve <path> --name NAME [--axis T] [--label L] [--compare N2]`
  resolves the format a name gets from a format calculation group; the same
  evaluator backs S005. Python API: `tmdl_preflight.format_resolver`
  (`resolve`, `decimals`, `UNKNOWN`).
- `stats --measures` summarises how measures are organised (name classes,
  helper kinds, field-parameter surfacing, top tables, described helpers).
- `comment-refs <path> [--list] [--json] [--floors FILE] [--tighten]`
  counts ticket references in comments; `--tighten` only ever lowers floors
  and drops all-zero entries.
- Ratchet files for O007, R008 and S004 keep the shape teams already use: a
  JSON object keyed by the `*.SemanticModel` folder relative to the scanned
  root (with or without the suffix). Recorded entries that no longer fail
  produce a tighten hint in the report's `notes`.
- `info --categories <path> [--json]` decodes the encoded category-mapping
  table: `groups` maps each group id to its categories (many-to-many; axis
  spacers and the standard calendar groups excluded) and `fact_tables`
  maps every fact table to the categories its metric-axis measures reach.
  Python API: `tmdl_preflight.categories`.
- `fix --check` writes nothing and exits with the number of objects the
  selected fixers would act on (capped at 255); `fix --only missing|invalid`
  narrows the refresh-policy fixers. The project section `refresh_policy`
  holds `loader_function`, `window_markers` (default `["RangeEnd"]`),
  `window`, `exempt`, `backlog` (per model), `etl_stamp_columns` and
  `inline_template`.
- `manifest <MODEL> [--out FILE] [--check] [--targets FILE]` writes a
  byte-stable JSON manifest (table roles, columns with their warehouse
  origin through Power Query renames, measures, the warehouse table each
  partition reads in loader-call, inline-window or navigator form,
  relationships, domains). The warehouse project and dataset the model
  declares are compared with an optional targets file; a mismatch exits 1
  and writes nothing. Config section `manifest` (`sources`, `target`,
  `domains`, ...). Python API: `tmdl_preflight.manifest`.
- `schema-check --manifest M --schema SNAPSHOT [--ignore-columns FILE]
  [--strict]` reconciles a manifest with an exported schema snapshot
  (`missing_in_source` fails, `needs_review` for programmatically renamed
  tables, `not_imported` and suspicious type pairs are informational);
  `schema-check --sql-dir DIR --entries FILE [--write-holdbacks]` proves
  view-column exposure from SQL files (exit 3 when an entry is held).
  Python API: `tmdl_preflight.reconcile`.
- `refs NAME [PATH ...] [--files] [--include-history] [--loose]` counts
  the anchored references to a name, model side and report side, live and
  archived.
- `live <MODEL> --workspace ID --dataset ID [--checks ...] [--strict]
  [--record DIR | --replay DIR]` (opt-in, the only command that uses the
  network): checks the published dataset over the Power BI REST API.
  Checks: `live-refresh-status`, `live-freshness`, `live-table-sample`,
  `live-dimension-rows`, `live-measure-sample`,
  `live-parameter-table-measures` (off unless `live.parameter_table_measures`),
  `live-uniform-row-limit`, `live-calendar-rows`, `live-dimension-multirow`,
  `live-calendar-scan`, `live-calendar-vs-parameters`, `live-parameter-audit`,
  `live-identity`, `live-filter-compare`, `live-metadata`,
  `live-filter-diagnostic`, `live-smoke` and `live-bpa`. Outcomes are pass,
  warn, fail, skip or error; exit 1 on fail or error (and on warn with
  `--strict`). The dataset name must match the local model folder unless
  `--expect-name` or `--no-coupling-check` is given. Recordings are keyed
  on the whitespace-normalised query text. Settings: config section `live`.
  Python API: `tmdl_preflight.live` (`ReplayClient`, `LiveBPA`, ...).
- The pytest plugin demotes test-body failures on the models listed in the
  configuration's `advisory` list to expected failures; passes stay passes
  and setup failures stay failures.
- `fieldparam retag <files> --names N1,N2 --from OLD --to NEW` changes the
  category value of the named live rows across sibling tables; a name not
  found live under OLD fails with "retag incomplete" and nothing is written.
- New Python API: `tmdl_preflight.measure_classes.classify_measure_name`
  (helper vs user-facing names, helper subcategory, scaffolding noise) and
  `tmdl_preflight.roles.fact_tables` (the shared fact-table law).
- The configuration accepts project sections (`contracts`,
  `refresh_policy`, `live`, `advisory`); rule options whose default is
  unset accept any JSON value.
- Rules carry a `safe` flag (`rules --json`). A fixer marked `safe: false`
  (it changes data or regenerates content) never runs in a blanket `fix`;
  select its rule explicitly to run it. The JSON payload lists such
  fixers under `skipped_fixers`.

### Bug fixes

- **A qualified measure reference is an edge in the fact trace.** A
  reference of the form `'Table'[Name]` or `Table[Name]`, where `Name` is a
  measure the model declares, is followed like a bare `[Name]`. The
  qualifier says which table owns the measure; it does not change what the
  reference means. Without this, a filter measure that reached a fact
  through a qualified reference was not counted as coverage, and the
  filter-coverage rule reported a false error.
- **A single-model lineage fix clears Desktop's cache by default.** The
  cache (`.pbi/cache.abf`) is what makes Power BI Desktop reuse the old
  lineage tags, so a run that changed a tag now deletes it and says
  `🗑️  Deleted cache file: <path>`. A whole-repository run never deletes
  a cache; it says that it exists. `--keep-cache` opts out on a
  single-model run, and `--clear-cache` forces the deletion.
- **Every line that starts with four spaces is an M017 error, expression
  bodies included.** The rule's `strict` option (on by default) exempts
  expression bodies; the default now flags them too, and the message is
  `Line <N>: Uses spaces instead of tabs for indentation`. A line that
  starts with tabs and then has spaces is still never flagged. The bare
  quoted multi-line measure note is always computed, as a non-failing info
  note.
- **M018 reports one finding per duplicated annotation name.** A name used
  three times yielded two findings that each said "appears twice". There is
  now one finding per name, saying how many times it occurs and listing
  every line.
- **Archived copies are skipped by default.** With no `exclude` list
  configured, every file whose path relative to the scan root has a folder
  segment that holds `legacy`, `_backup` or `_b2` is skipped. A configured
  `exclude` list replaces the default; an empty list turns it off.
- **A file that mixes its line endings is never rewritten.** A fleet
  committed from Windows and then touched by a tool that writes LF ends up
  with a file that mixes CRLF and LF. Such a file cannot be split on one
  style and joined on another: the lines that use the other style fold into
  one, and the edit computed on that deleted the model — a three-measure
  table went from 28 lines to 3. Such a file is now left exactly as it is,
  and the violation stays on the report.
- A file whose lines end with a lone CR (no LF) is read line by line like
  any other file. Before, it was read as one line, so the check reported a
  different set of findings than the same model with LF.
- A manifest or a schema snapshot that is valid JSON but not an object, and
  a field-parameter table that is not UTF-8, are configuration errors:
  exit 2, a message on standard error, and never a Python traceback.
- A lineage tag followed by a tab or several spaces after `lineageTag:` is
  rewritten like any other (before, only one space was handled).
- Three or more copies of a tag in one file: the later copies are
  rewritten, the first is kept.
- The `fact-table-filter-coverage` rule now exempts a fact the way the
  forge's gap-fill planner does: a user-facing measure on an x row with a
  mapped group that reads the fact directly (a data read, not only inside
  a sensor) means the fact is already gated, so no `f-` measure is owed.
  A helper measure on an x row never exempts a fact: it is the model's own
  business. Before, the exemption needed the x-row measure to be one of
  the fact's consumers, so the two tools could disagree about the same
  model.

### Test expectations and why

Tests whose expectation follows a deliberate choice are listed with the
reason (BUGFIX: earlier behaviour was a bug; STRICTER: the stricter of test
and rule wins; DESKTOP: Power BI Desktop evidence).

- DESKTOP: `test_lineage_tag_uniqueness::test_lineage_tag_format_validity[placeholder-fail]`
  expects M004 as a warning (an error was expected before).
- STRICTER: `test_tmdl_parser_explore::test_ec020_column_and_measure_share_a_name_target`
  accepts any severity; M012 already reports a measure named like a column
  of its own table as an error.
- Test convention: `test_p0_tmdl_guardian` turns on M016's opt-in
  `check_line_endings` (off by default because Windows checkouts are often
  CRLF) to pin the line-ending verdicts.
- BUGFIX: `test_naming_conventions::TestHelperMeasuresFollowConventions`
  counts 2 described dash helpers where earlier versions printed 1 (its index
  dropped the description of a measure that directly follows another).
- STRICTER (project decision): `test_dax_table_references::test_dax_references_resolve[reference_casing-*]`
  now fail: `sales[Amount]` against table `Sales` resolves in DAX, but casing
  mismatches are D004 errors (the earlier verdict was pass).
- STRICTER: `test_dax_parsable::test_dax_comprehensive_syntax_check[one_unmatched_paren]`
  asserts the D001 error even though the clean share (90.9%) meets the
  threshold (earlier versions passed).
- Existing test updated: `test_rules_dax::test_case_mismatch_resolves_but_is_an_error`
  (was `test_case_insensitive_resolution`) expects three casing errors.
- STRICTER (project decision): `test_relationships::test_relationship_endpoints_exist[rel_casing-fail]`
  expects the casing mismatch as an error that fails without `--strict`
  (a warning was expected before).
- Test convention: R001's success rate is a note, not a finding (the
  tests count exactly one R001 finding per broken endpoint).
- Test convention: R010 does not report a two-table loop (a reverse pair is
  R006's); the cycle test expects no finding for it.
- STRICTER: `test_reference_integrity_xselector` and `_yselector`
  `::test_case_only_mismatch_is_a_casing_error` expect a D004 casing error
  (the reference resolves in Power BI, but casing mismatches are errors).
- STRICTER: `test_reference_integrity_xselector::test_calculated_column_with_empty_expression_fails`:
  `column X =` followed directly by a property line is a calculated column
  with an empty expression (M020).
- BUGFIX: `test_connection_parameters::test_generate_connection_parameter_audit_report[limit-100]`:
  only `LIMIT 1` itself is CRITICAL; `LIMIT 10` and `LIMIT 100` are warnings.
- BUGFIX: `test_fabric_bpa_validation::TestBPAPerformanceRules::test_calculated_columns_detected`:
  calculated columns are found by the integer column type (the text
  comparison found none).
- Test convention: `test_policy_defaults::test_dax_success_rate_threshold_never_suppresses_per_expression_errors`
  sets `min_success_rate` to 0.8: the example model has 7 expressions, so
  one unbalanced expression is 85.7%.
- Test convention: `test_fixers_config_contract` lists the unsafe fixers by
  their rule names: refresh-policy-repair, dax-reference-resolution and
  autodetected-relationships.
- STRICTER: `test_rls::test_mapping_table_is_hidden` judges the table's own
  `isHidden`; a hidden column no longer makes a visible mapping table pass.
- BUGFIX: `test_integration_f_categories::test_f_measure_coverage_analytics_zero_f_measures`:
  a model with no f- measures reports nothing instead of dividing by zero.
- Existing tests updated: `test_rules_relationships` expects R007 as an
  error and an R001 casing error for `sales.STORE_ID`.
- Existing tests updated for the severity changes above: M011 is an error
  and its fixer targets the first property slot; M013 at end of file is an
  error and keeps blank lines before the run; the M002 fence message
  changed; `rules --json` no longer pins the rule count.

## 1.1.0 (2026-10-12)

### Highlights

- **16 new rules** (37 in total) covering defects that stop Power BI from
  opening, deploying or evaluating a model: TMDL properties leaked into
  expressions, dangling `///` descriptions, duplicate object names, DAX
  references to tables and columns that no longer exist, duplicate
  variables, ambiguous active relationships, missing and trailing commas in
  field-parameter rows, bookmark option keys outside the schema, and broken
  report definitions.
- **5 new auto-fixers** (10 in total): M011, M013, F002, F003, B003.
- **Project configuration**: `[tool.tmdl-preflight]` in `pyproject.toml`,
  `.tmdl-preflight.toml` (Python 3.11+) or `.tmdl-preflight.json` (any
  supported Python), with `select`, `ignore`, `strict`,
  `severity_overrides`, `exclude`, per-rule options, `profiles` (`--profile`)
  and `--config PATH`. Unknown keys and rule ids are errors.
- **Exemptions** with a mandatory `reason` and an optional `until` date;
  once the date passes, the violation is reported again.
- **Baselines**: `tmdl-preflight baseline <path>` records today's violations;
  `check --baseline FILE` fails only on new ones and reports fixed and stale
  entries; `baseline --update` only shrinks the file unless `--accept-new` is
  given.
- **Output formats**: `--format text|json|github|sarif|markdown` (`--json`
  stays as an alias). SARIF 2.1.0 output plugs into GitHub code scanning.
- **`tmdl-preflight stats <path>`**: an inventory of the project, counts only.
- **CI integration**: a `.pre-commit-hooks.yaml` and an example GitHub
  Actions workflow under `examples/ci/`.

### New rules

| ID | Name | Severity | Auto-fix |
|---|---|---|---|
| M010 | metadata-in-expression | error | no |
| M011 | property-after-child-block | warning | yes |
| M012 | duplicate-object-names | error | no |
| M013 | dangling-description | error (warning at end of file) | yes |
| M014 | calc-group-implicit-measures | error | no |
| M015 | ref-table-target-missing | error | no |
| D004 | dax-reference-resolution | error (warning for an unresolved bare `[X]`) | no |
| D005 | duplicate-var-in-scope | error | no |
| R006 | ambiguous-active-pair | error | no |
| R007 | autodetected-relationships | warning | no |
| F002 | fieldparam-missing-separator | error | yes |
| F003 | fieldparam-trailing-comma | error | yes |
| F004 | fieldparam-ragged-rows | warning | no |
| B003 | bookmark-options-schema | error | yes |
| B004 | report-definition-integrity | error | no |
| S002 | measure-descriptions | info | no |

M003, M006, M007, M010, M015 and R006 are marked `baselinable = False`: they
stop a model from opening or deploying, so a baseline can never hide them.

### Parser robustness

- Files are read as `utf-8-sig`, so a byte-order mark no longer hides the
  first declaration of a file.
- An unreadable `relationships.tmdl` is reported by M002 instead of
  crashing the run.
- Duplicate declarations are kept (lists alongside the name-keyed dicts,
  first declaration wins) instead of the last one silently overwriting the
  first; tables, columns and measures also have case-insensitive lookups.
- Relationships with a missing endpoint are kept and reported by R001
  instead of being dropped.
- A raw count of `column`/`measure`/`relationship` declaration lines is
  compared with what was parsed; a difference is reported by M002 ("parser
  dropped N object(s)"), typically a mis-indented declaration.
- The parser now reads `///` descriptions, `displayFolder`,
  `expressions.tmdl` (names and `meta` records), `refreshPolicy` placement,
  and `discourageImplicitMeasures` / `ref table` lines from `model.tmdl`.
- A measure-level `formatStringDefinition` is attributed to its measure.
- DAX lexer: `''` inside quoted table names, `]]` inside brackets and `--`
  inside brackets are covered by tests.

### Fixes

- **Fixers no longer rewrite line endings.** The M003, M004, M006 and F001
  fixers read files with universal newlines and wrote them back with LF, so
  on a CRLF checkout a one-line repair showed up as a whole-file diff. Every
  fixer now preserves the file's newline style and byte-order mark.
- **B001 is surgical.** It used to re-serialize the whole bookmark JSON; it
  now edits only the offending values in the text and proves the edit by
  parsing both versions (refusing to write otherwise). All fixers share the
  new `verified_write` helper.
- **S001** exempts only the measure that carries a `formatStringDefinition`.
  A model is exempt as a whole only when calculation-group items define
  format strings. Previously any format-string definition exempted the whole
  model.
- **D003** compares measure names case-insensitively, as the engine does,
  and leaves duplicates inside one table to M012.
- **D002 and R001** resolve table, column and measure names
  case-insensitively.
- Properties are attached by indentation to the object they belong to, so
  a hierarchy's or annotation's lines no longer overwrite properties of the
  column declared before them.

### Compatibility

- The CLI invocation (`tmdl-preflight check <path>`) and the exit codes
  (`0` clean, `1` violations, `2` usage or path error) are unchanged. Exit
  code `2` now also covers configuration and baseline errors.
- JSON output is additive only: `summary` gains `excluded`, `exempted` and
  `baselined`; the payload gains `scanned`, and `exemptions` / `baseline`
  when they apply; each violation gains `path` (project-relative). Existing
  fields are unchanged. `rules --json` gains `baselinable` and `options`.
- The text report prints a `scanned:` line just before the final
  `tmdl-preflight:` summary line, which is still the last line.
- The new error-level rules only fire on defects that stop a model from
  opening, deploying or evaluating. Rules that can fire on clean,
  Desktop-generated models (M011, R007, F004, S002, and D004 for bare
  references) are warning or info.
- A configuration file found next to (or above) the checked path now
  changes the run. Pass `--no-config` to ignore it.
- Python 3.10 remains supported. TOML configuration needs Python 3.11+
  (`tomllib`); on 3.10 use `.tmdl-preflight.json`.
- Version numbering: the previous release was tagged `v1.0.0-stable` on
  GitHub, but its package metadata (`pyproject.toml` and `__version__`)
  still said `0.1.0`. This release sets both to `1.1.0`.

## 0.1.0

First public release.

### Highlights

- **21 rules** covering the TMDL/PBIP failure modes that reject imports or
  silently corrupt results: model structure (M001–M009), DAX integrity
  (D001–D003), relationship topology (R001–R005), field-parameter sources
  (F001), bookmark JSON (B001–B002), and formatting hygiene (S001).
- **5 auto-fixers** (M003, M004, M006, F001, B001) applied through a
  check → fix → re-check loop: a run only counts as clean when the re-check
  from disk is clean, so a fixer never vouches for itself.
- **Three entry points**: the `tmdl-preflight` CLI (`check`, `fix`,
  `rules`), a pytest fixture (`tmdl_preflight`), and a plain Python API.
- **Zero runtime dependencies**; Python 3.10+.

### Validated against production-scale models

Before release, the suite was run end to end against several multi-megabyte
production semantic models (hundreds of tables, thousands of measures,
calculation groups, legacy expression fences, non-ASCII object names).
Findings folded back into this release:

- **D002 (nameof-resolution)** no longer flags fully-qualified measure
  references such as `NAMEOF('Table'[Measure])`. Power BI Desktop writes
  that form itself when building field parameters, so flagging it buried
  real breaks under hundreds of false alarms per model.
- **R005 (orphan-tables)** now exempts hidden tables and tables whose
  columns are all hidden (the measure-home pattern). Real models declare
  dozens of these and they are unrelated by design.
- **CLI output is resilient to console code pages.** Object names outside
  the console's encoding (Greek, accented, emoji) no longer risk a
  `UnicodeEncodeError`; unencodable characters are replaced instead of
  crashing the report.
- `--select`/`--ignore` now reject rule ids that do not exist (exit code 2)
  instead of silently running a smaller rule set.

### Error-message conventions

Every human-facing message follows a fixed shape: what is wrong, where it
is, why it breaks deployments or analysis, and the concrete next action.
Messages avoid blame, jargon-only phrasing, and vague words such as
"invalid".
