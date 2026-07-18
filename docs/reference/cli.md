# CLI reference

```
tmdl-preflight [--version] [--rules] <command> [options]
```

## Commands

### `tmdl-preflight check <path>`

Run every selected rule and report violations. Strictly read-only.

| Option | Effect |
|---|---|
| `--select IDS` | Comma-separated rule ids or names to run (default: all). Case-insensitive. |
| `--ignore IDS` | Comma-separated rule ids or names to skip. |
| `--json` | Emit the machine-readable report instead of text. |
| `--strict` | Exit nonzero on warnings as well as errors. |

### `tmdl-preflight fix <path>`

Run every selected rule; for each **fixable** rule that reported violations,
apply its auto-fix; then re-run every selected rule from disk and report
what remains. Takes the same options as `check`.

The exit code reflects the *post-fix* state: `0` means the re-check came
back clean, `1` means violations survived the repair (or were never
fixable).

### `tmdl-preflight rules`

Print the rule catalog (id, name, severity, fixability, description).
`--json` emits it as a JSON array. The top-level flag `tmdl-preflight
--rules` is an alias.

## `<path>` resolution

`<path>` may be any of:

| You pass | tmdl-preflight uses |
|---|---|
| a PBIP project root | every `*.SemanticModel/definition` and every `*.Report` found beneath it |
| a `*.SemanticModel` folder | its `definition/` |
| a `definition` folder (has `tables/`) | itself |
| a `*.Report` folder | itself (report-side rules only) |

Multiple models/reports under one root are all checked in a single run.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | clean (after fixes, for `fix`) |
| `1` | violations remain — errors, or warnings with `--strict` |
| `2` | usage error: path missing, nothing to check, unknown rule id, empty rule selection |

## Text output format

```
<file>:<line>  <RULE> <severity>: <message> [<object>] (auto-fixable)
```

Files are shown relative to the checked path when possible. `fix` runs
prefix the report with one `fixed  <RULE>: <description>` line per applied
repair.

## JSON output format

```json
{
  "summary": {
    "errors": 0,
    "warnings": 0,
    "infos": 0,
    "fixes_applied": 1
  },
  "fixes": ["M003: Stores.tmdl:3 (table Stores): '...' -> '...'"],
  "violations": [
    {
      "rule": "M003",
      "severity": "error",
      "message": "...",
      "file": "...",
      "line": 3,
      "object": "table Stores",
      "fixable": true
    }
  ]
}
```

`violations` reflects the final state of the run (post-fix for `fix`).

## Environment

The CLI reads no environment variables. The pytest fixture honors
`TMDL_PREFLIGHT_AUTOFIX=1` as a default for its `autofix` parameter — see
[Run rules inside pytest](../how-to/run-in-pytest.md).
