# Contributing to tmdl-preflight

tmdl-preflight is a preflight linter and auto-fixer for Power BI semantic
models saved in TMDL format (PBIP folders): it catches the defects that stop
Power BI Desktop from opening a project (missing `ref table` lines, tables
with no partition, inline `#table` entity sources, duplicate or malformed
lineage tags, field-parameter comma runs) and mechanically repairs the ones
whose fix is fully determined by the failure.

Contributions are welcome: new rules, fixers, docs, and bug reports. This
guide covers how to set up, where things live, and how to add a rule.

## Development setup

The tool has **zero runtime dependencies** (standard library only, Python
≥ 3.10); the only dev dependency is `pytest`.

```console
$ git clone https://github.com/c-kapsalis/tmdl-preflight.git
$ cd tmdl-preflight
$ python -m venv .venv
$ source .venv/bin/activate       # Windows: .venv\Scripts\activate
$ pip install -e ".[test]"        # editable install + the pytest extra
$ pytest                          # run the suite
```

`pip install -e .` puts the `tmdl-preflight` console command on your PATH and
registers the `tmdl_preflight` pytest plugin. Verify with:

```console
$ tmdl-preflight --version
tmdl-preflight 1.1.0
```

## Project layout

```
src/tmdl_preflight/
├── cli.py            # the `tmdl-preflight` command (check, fix, baseline, stats, rules)
├── engine.py         # check → fix → re-check loop, scanned counts, apply_policy()
├── config.py         # config discovery + validation, profiles, excludes, exemptions
├── baseline.py       # baseline files: record, apply, update
├── output.py         # text / json / github / sarif / markdown renderers
├── stats.py          # the `stats` inventory
├── model.py          # parsed SemanticModel: tables, columns, measures, …
├── parser.py         # TMDL / PBIP folder parsing, path resolution
├── dax.py            # DAX region classifier + lexing helpers (references,
│                     #   VARs, table constructors, comma runs)
├── recognizers.py    # line-level TMDL recognizers shared by checks and fixers
├── edits.py          # read_text_file() / verified_write() for every fixer
├── pytest_plugin.py  # the `tmdl_preflight` fixture
└── rules/
    ├── base.py             # Rule, Violation, Severity, Context, RuleSet
    ├── structural.py       # M001–M015
    ├── dax_rules.py        # D001–D005
    ├── relationships.py    # R001–R007
    ├── field_parameters.py # F001–F004
    ├── report.py           # B001–B004
    ├── style.py            # S001–S002
    └── __init__.py         # ALL_RULES registry + default_ruleset()

tests/                # pytest suite; fixtures/ holds the clean example model
examples/             # bike-shop-clean and bike-shop-broken PBIP projects,
                      #   plus ci/ (GitHub Actions, pre-commit, config examples)
```

The full Diátaxis documentation (tutorials, how-to guides, reference,
explanation) lives in the separate `tmdl-preflight-documentation`
repository, published on Read the Docs at
<https://tmdl-preflight-documentation.readthedocs.io/en/latest/>.

Each rule has an `id` (`M003`), a `name` (`lineage-duplicates`), a
`Severity` (`ERROR` / `WARNING` / `INFO`), and a one-paragraph `description`.
A rule's `check()` returns `Violation`s; a rule that can repair its own
violation class sets `fixable = True` and implements `fix()`. Two optional
class attributes complete the picture: `baselinable = False` for defects
that must never be accepted into a baseline (the model would not open or
deploy at all), and `option_defaults = {...}` for per-rule options that
users can set in the config file (`[tool.tmdl-preflight.rules.<ID>]`).

## Design principles

- **The detector and the fixer share one recognizer.** A fixable rule's
  `check()` and `fix()` both call the same function (for example
  `recognizers.find_dangling_descriptions` or `dax.scan_table_constructors`),
  so they can never disagree about what counts as a defect.
- **Every edit is surgical and verified.** Fixers change the file text in
  place (never re-serialize a parsed object) and write through
  `edits.verified_write()`, whose `verify(old, new)` callback proves the edit
  (for JSON: parse both versions and compare). If the proof fails, nothing
  is written and the violation stays on the report.
- **Nothing is dropped silently.** The parser keeps duplicates, keeps
  malformed relationships for R001, and compares a raw count of declaration
  lines with what it parsed (M002).
- **Every rule test plants a defect.** Each rule has a clean-case test and
  at least one test that breaks a copy of the clean fixture in exactly one
  way and asserts the rule fires.
- **New rules that can fire on clean, Desktop-generated models are
  `warning` or `info`, never `error`.** Errors are reserved for defects that
  stop a model from opening, deploying or evaluating.

## Adding a new rule

1. **Subclass `Rule`** in the appropriate `rules/*.py` module (or a new one).
   Give it a unique `id`, a `name`, a `severity`, and a `description`, then
   implement `check(self, ctx) -> list[Violation]`:

   ```python
   from .base import Context, Rule, Severity, Violation

   class TableDescriptionRule(Rule):
       id = "X001"                 # unique; pick a prefix outside M/D/R/F/B/S
       name = "table-descriptions"
       severity = Severity.WARNING
       description = "Visible tables should carry a /// description comment."

       def check(self, ctx: Context) -> list[Violation]:
           out = []
           for model in ctx.models:
               for table in model.tables.values():
                   if not table.is_hidden and needs_description(table):
                       out.append(self.violation(
                           "visible table has no /// description",
                           file=table.file, line=table.line, obj=table.name,
                       ))
           return out
   ```

   `ctx.models` are parsed `SemanticModel`s; `ctx.report_dirs` are the
   `*.Report` folders for report-side rules; `ctx.reload()` drops the parse
   cache (the engine calls it after fixers run).

2. **(Optional) add a fixer.** Set `fixable = True` and implement
   `fix(self, ctx) -> list[str]`, returning one human-readable line per
   change. Honor the safety contract: only repair what the failure fully
   determines, be idempotent, make minimal line-level edits, and never
   overwrite human-authored semantics (names, DAX, relationships). The
   engine re-checks from disk afterward, so a fixer never vouches for
   itself.

3. **Register it** in `src/tmdl_preflight/rules/__init__.py`: import the
   class and add it to the `ALL_RULES` list. If it has a fixer, route the
   write through `edits.verified_write()`.

4. **Add a test** in `tests/` (see below).

5. **Document it** by adding an entry to the rule catalog reference page, and,
   for a substantial rule, an explanation page, both in
   `tmdl-preflight-documentation`.

The long-form version of this recipe, including the plain-Python API, is in
that repository's "add a custom rule" how-to guide.

## Testing

Tests live in `tests/`, one `test_rules_*.py` file per rule module. The
shared fixtures in `tests/conftest.py` give you a pristine copy of the
"Pedal & Sprocket Bike Co." model:

- `project`, a disposable copy of the clean model in `tmp_path`, safe to
  mutate;
- `definition` / `report_dir`, the model and report folders inside it;
- `clean_project`, the pristine fixture (never mutate it).

Follow the built-in pattern (the `replace_in` fixture plants a defect by
replacing one exact snippet and fails loudly if the snippet is missing):
copy the clean fixture, break **exactly one**
thing to trigger your failure mode, assert the violation is detected, and,
for a fixer, assert that fix → re-check comes back clean and that a second
fix is a no-op (idempotent). For example:

```python
def test_duplicate_lineage_tag_is_flagged(project, definition):
    stores = definition / "tables" / "Stores.tmdl"
    # ...copy Products' lineageTag onto Stores, then:
    violations = LineageTagUniquenessRule().check(Context(project))
    assert any(v.rule_id == "M003" for v in violations)
```

## Before you open a PR

Run both of these; both must pass:

```console
$ pytest
$ tmdl-preflight check examples/bike-shop-clean

scanned: 1 model, 6 tables, 22 columns, 6 measures, 4 relationships, 8 DAX expressions, 1 report
tmdl-preflight: 0 error(s), 0 warning(s), 0 info(s)
```

The second command is the end-to-end smoke test: the shipped clean example
must stay clean. If you touched a fixer, also confirm
`tmdl-preflight fix` on a copy of `examples/bike-shop-broken` clears the four
blockers and leaves only the S001 info finding.

## Commit and PR conventions

- Branch off `master`; keep each PR focused on one rule, fix, or topic.
- Write imperative, present-tense commit subjects ("Add M009 partition-mode
  rule", not "Added…"); keep the subject under ~72 characters and explain
  the *why* in the body when it isn't obvious.
- Keep auto-fix changes to a model in their own commit so reviewers can wave
  them through.
- A PR should describe what it changes and why, note any new/changed rule
  ids, and confirm that `pytest` and the clean-example check both pass.

## Reporting issues

Open an issue on the
[GitHub tracker](https://github.com/c-kapsalis/tmdl-preflight/issues) with:

- what you ran (the exact `tmdl-preflight` command and flags),
- what you expected versus what happened (paste the report output),
- your Python version and OS, and
- a minimal TMDL/PBIP snippet that reproduces it, if you can share one.

Security-sensitive reports should go to the maintainer privately rather than
a public issue.

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE) (© 2026 Christoforos Kapsalis).
