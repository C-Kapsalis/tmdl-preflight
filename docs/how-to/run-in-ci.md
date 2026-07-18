# How to run tmdl-preflight in CI

Goal: fail a pull request when a PBIP semantic model carries a defect,
without CI ever mutating the repository.

## The one rule of CI usage

**CI checks; developers fix.** Run `tmdl-preflight check` (read-only) in the
pipeline. Auto-fixes belong on a developer's machine, where the diff gets
reviewed and committed like any other change.

## GitHub Actions

```yaml
name: tmdl-preflight
on:
  pull_request:
    paths:
      - "**/*.SemanticModel/**"
      - "**/*.Report/**"

jobs:
  preflight:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install tmdl-preflight
      - run: tmdl-preflight check . --strict
```

`--strict` makes warnings fail the job as well as errors. Drop it if you
only want hard failures to block.

## Azure DevOps

```yaml
steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: "3.12"
  - script: pip install tmdl-preflight
  - script: tmdl-preflight check $(Build.SourcesDirectory) --strict
    displayName: TMDL preflight
```

## Scoping and tuning

- **Check one model in a multi-model repo:** pass the specific folder —
  `tmdl-preflight check src/Finance.SemanticModel`.
- **Silence an advisory rule** that does not apply to your architecture
  (for example S001 in a model that formats via calculation groups):
  `tmdl-preflight check . --ignore S001`.
- **Gate on a subset** while you clean up legacy debt:
  `tmdl-preflight check . --select M002,M003,D001,R001`.

## Machine-readable output

For annotations or dashboards, use `--json` and parse the payload:

```console
$ tmdl-preflight check . --json > preflight.json
```

```json
{
  "summary": {"errors": 1, "warnings": 0, "infos": 0, "fixes_applied": 0},
  "fixes": [],
  "violations": [
    {
      "rule": "M003",
      "severity": "error",
      "message": "lineageTag '...' duplicates the one on table Products (...)",
      "file": ".../tables/Stores.tmdl",
      "line": 3,
      "object": "table Stores",
      "fixable": true
    }
  ]
}
```

Exit codes: `0` clean, `1` violations (errors; warnings too under
`--strict`), `2` usage or path errors — so a missing model folder fails the
job loudly instead of passing vacuously.
