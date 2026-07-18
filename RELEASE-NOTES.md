# Release notes

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
