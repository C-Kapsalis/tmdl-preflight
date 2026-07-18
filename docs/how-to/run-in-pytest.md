# How to run tmdl-preflight inside pytest

Goal: make model health a test, so `pytest` fails when the semantic model
regresses — the workflow these rules originally grew up in.

Installing the package registers a pytest plugin automatically; no
`conftest.py` wiring is needed.

## The `tmdl_preflight` fixture

```python
# tests/test_model_health.py

def test_model_is_deployable(tmdl_preflight):
    tmdl_preflight.assert_clean("src/Shop.SemanticModel")
```

On failure you get the full violation list in the assertion message:

```
Failed: tmdl-preflight found 1 blocking violation(s) in src/Shop.SemanticModel:
  M003 error: lineageTag '...' duplicates the one on table Products (...)
```

`assert_clean` fails on errors; pass `strict=True` to fail on warnings too.
`info` findings never fail a test.

## Scoping

```python
def test_lineage_only(tmdl_preflight):
    tmdl_preflight.assert_clean("src/Shop.SemanticModel",
                                select={"M003", "M004"})

def test_everything_but_style(tmdl_preflight):
    tmdl_preflight.assert_clean("src/Shop.SemanticModel",
                                ignore={"S001"})
```

## Auto-fix in the test (the imposition pattern)

With `autofix=True` the runner repairs what it safely can and asserts on the
**re-check** — the repair becomes part of the test rather than a separate
chore:

```python
def test_model_is_deployable(tmdl_preflight):
    report = tmdl_preflight.assert_clean("src/Shop.SemanticModel",
                                         autofix=True)
    if report.fixes_applied:
        print("auto-fixed; review and commit:", *report.fixes_applied, sep="\n  ")
```

You can also flip auto-fix from the environment without touching test code —
useful for keeping CI read-only while developers repair locally:

```console
$ TMDL_PREFLIGHT_AUTOFIX=1 pytest tests/test_model_health.py   # local: repair
$ pytest tests/test_model_health.py                            # CI: check only
```

## Inspecting instead of asserting

`run()` returns the report without failing the test, if you want custom
assertions:

```python
def test_no_new_bidirectional_filters(tmdl_preflight):
    report = tmdl_preflight.run("src/Shop.SemanticModel", select={"R004"})
    assert len(report.infos) <= 2   # the two we have documented
```
