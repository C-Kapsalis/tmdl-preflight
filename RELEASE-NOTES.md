# Release notes

## Unreleased

This release ports a large private pytest suite into the tool: its checks
become rules, its scripts become commands, and its tests become the
tool's own test suite (fictional stand-in models, no client data).

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
| M011 property-after-child-block | warning | error | Stricter of the ported test and the rule. |
| M013 dangling-description at end of file | warning | error | Stricter of the ported test and the rule. |

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

Rules that encode one team's conventions are **opt-in**: they run only when
named in `--select` or in the configuration's `select` (`rules` marks them).
Contract rules (C001-C004, R008, F005) read their contracts from the
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
- **D004** reports an unqualified `[X]` that names a measure declared in two
  or more tables as an ambiguous reference (warning).
- **NAMEOF** extraction ignores a malformed reference whose quoted table
  name contains a double quote.
- Names declared with trailing spaces inside quotes (`'Frame Size   '`) are
  read trimmed.

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
- `stats --measures` summarises how measures are organised (name classes,
  helper kinds, field-parameter surfacing, top tables, described helpers).
- `comment-refs <path> [--list] [--json] [--floors FILE] [--tighten]`
  counts ticket references in comments; `--tighten` only ever lowers floors
  and drops all-zero entries.
- Ratchet files for O007, R008 and S004 keep the shape teams already use: a
  JSON object keyed by the `*.SemanticModel` folder relative to the scanned
  root (with or without the suffix). Recorded entries that no longer fail
  produce a tighten hint in the report's `notes`.
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

### Bug fixes carried over from the ported suite

- A lineage tag followed by a tab or several spaces after `lineageTag:` is
  rewritten like any other (the original script only handled one space).
- Three or more copies of a tag in one file: the later copies are
  rewritten, the first is kept.

### Ported test suite: changed expectations

Each ported test whose expectation differs from the original's verdict is
listed with the reason (BUGFIX: a bug in the original is fixed; STRICTER:
the stricter of test and rule wins; DESKTOP: Power BI Desktop evidence).

- DESKTOP: `test_lineage_tag_uniqueness::test_lineage_tag_format_validity[placeholder-fail]`
  expects M004 as a warning (the porter expected an error).
- STRICTER: `test_tmdl_parser_explore::test_ec020_column_and_measure_share_a_name_target`
  accepts any severity; M012 already reports a measure named like a column
  of its own table as an error.
- Port convention: `test_p0_tmdl_guardian` turns on M016's opt-in
  `check_line_endings` (off by default because Windows checkouts are often
  CRLF) to reproduce the original verdicts.
- BUGFIX: `test_naming_conventions::TestHelperMeasuresFollowConventions`
  counts 2 described dash helpers where the original printed 1 (its index
  dropped the description of a measure that directly follows another).
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
