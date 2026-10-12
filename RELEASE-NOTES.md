# Release notes

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
