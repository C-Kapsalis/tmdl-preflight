# How to add a custom rule

Goal: enforce a convention of your own — say, "every visible table must have
a description" — with the same engine, CLI selection and (optionally)
auto-fix machinery the built-in rules use.

## 1. Subclass `Rule`

A rule is a class with four attributes and a `check()` method:

```python
from tmdl_preflight import Rule, Severity
from tmdl_preflight.rules.base import Context, Violation


class TableDescriptionRule(Rule):
    id = "X001"                      # unique; pick a prefix outside M/D/R/F/B/S
    name = "table-descriptions"
    severity = Severity.WARNING
    description = "Visible tables should carry a /// description comment."

    def check(self, ctx: Context) -> list[Violation]:
        out = []
        for model in ctx.models:                    # parsed SemanticModel(s)
            for table in model.tables.values():
                if table.is_hidden:
                    continue
                text = table.file.read_text(encoding="utf-8")
                if not text.lstrip().startswith("///"):
                    out.append(self.violation(
                        "visible table has no /// description",
                        file=table.file,
                        line=table.line,
                        obj=table.name,
                    ))
        return out
```

What `ctx` gives you:

- `ctx.models` — a list of parsed `SemanticModel` objects (tables, columns,
  measures, relationships, lineage tags, `dax_blocks()`).
- `ctx.report_dirs` — every `*.Report` folder found, for report-side rules.
- `ctx.reload()` — drops the parse cache; the engine calls it after fixes.

## 2. (Optional) add a fixer

Set `fixable = True` and implement `fix()`. Respect the safety contract:

> A fixer only repairs what its rule's failure mode describes, is
> idempotent, and never overwrites human-authored semantics.

```python
    fixable = True

    def fix(self, ctx: Context) -> list[str]:
        applied = []
        for model in ctx.models:
            for table in model.tables.values():
                ...  # edit table.file surgically, then:
                applied.append(f"{table.file.name}: added description stub")
        return applied
```

Return one human-readable string per change; the engine prints them and
re-checks from disk afterwards. If your fixer did not actually resolve the
violation, the re-check will say so — you do not need to verify yourself.

## 3. Run it

Build a `RuleSet` that includes your rule and hand it to the engine:

```python
from tmdl_preflight import Context, check, default_ruleset
from tmdl_preflight.rules.base import RuleSet

ruleset = default_ruleset()
ruleset.rules.append(TableDescriptionRule())

report = check(Context("MyProject/"), ruleset)
for v in report.violations:
    print(v.rule_id, v.message)
```

Inside pytest the same works through the fixture's building blocks, or run
the report yourself and assert on it:

```python
def test_custom_convention():
    report = check(Context("MyProject/"), ruleset)
    assert not report.errors
```

## 4. Test it like the built-ins

Follow the pattern in `tests/test_rules_*.py`: copy a clean fixture model
into `tmp_path`, mutate it to trigger exactly your failure mode, assert the
violation is detected — and, if you wrote a fixer, assert that
fix → re-check comes back clean and that the fix is idempotent.
