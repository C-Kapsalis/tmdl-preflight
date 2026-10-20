"""P0: no DAX VAR declared twice in the same scope.

A DAX VAR name must be unique within its scope. Declaring the same VAR twice in
one scope makes the measure fail to evaluate on refresh:

    MdxScript(Model) Variable 'temp_alt' cannot be created because a table or
    variable with the same name already exists.

The SAME name is legal in DIFFERENT (nested) sub-expressions — e.g. `___f`
reused inside separate IF() branches, each with its own RETURN — so this only
flags duplicates at the OUTER scope of a measure (parenthesis depth 0), which is
the scope collision that actually breaks.

Incident: a branch merge stacked two top-level `VAR temp_alt` blocks in one
f-All measure; the model imported but every visual bound to it errored on
refresh.

Implementation: the kernel finder is replaced by rule D005 (`check --select D005`);
the registry model by the stand-in `tests/fixtures/test_dax_parsable_bikeshop`.
The earlier check asserts zero vs non-zero only; D005 reports one finding per
re-declaration (three declarations -> 2 findings).
"""

from __future__ import annotations

import json

import pytest

from conftest import run_check, violations

FIXTURE = "test_dax_parsable_bikeshop"


def _materialize(stand_in, variant):
    root = stand_in(FIXTURE)
    if variant:
        for op in json.loads((root / "variants.json").read_text(encoding="utf-8"))[variant]:
            f = root / op["file"]
            text = f.read_text(encoding="utf-8")
            assert text.count(op["old"]) == 1
            f.write_text(text.replace(op["old"], op["new"]), encoding="utf-8")
    (root / "variants.json").unlink()
    return root / "BikeShop.SemanticModel"


def _gate(model_dir):
    tables = model_dir / "definition" / "tables"
    if not tables.exists():
        pytest.skip(f"no tables dir: {tables}")
    code, payload = run_check(model_dir, "D005")
    problems = [f"{v.get('object')}: {v['message']}" for v in violations(payload, "D005")]
    assert not problems, (
        f"{model_dir.name}: DAX VAR declared twice in the same scope — the measure "
        f"fails on refresh ('Variable … cannot be created'):\n  " + "\n  ".join(problems))
    return payload


@pytest.mark.parametrize("variant,verdict,count", [
    (None, "pass", 0),
    ("dup_var_twice", "fail", 1),
    ("dup_var_in_branches", "pass", 0),
    ("dup_var_thrice", "fail", 2),
])
def test_no_duplicate_scope_vars(stand_in, variant, verdict, count):
    model_dir = _materialize(stand_in, variant)
    if verdict == "pass":
        _gate(model_dir)
    else:
        with pytest.raises(AssertionError):
            _gate(model_dir)
    code, payload = run_check(model_dir, "D005")
    assert len(violations(payload, "D005")) == count
