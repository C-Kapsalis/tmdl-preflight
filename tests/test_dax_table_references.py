"""
Layer 2 (DAX validity): every table a DAX expression references must exist.

WHY THIS GATE EXISTS (spinout-05): `_Client_c Campaigns` was removed by a
merge-conflict resolution rather than by `retire.table`. A guard that refuses to
drop a table while a reference to it survives is a **precondition on an action**,
not an invariant on the model. Delete the table any other way (merge side-pick,
hand `git rm`, a script that unlinks the file) and nothing re-checks. The model
then imports cleanly and fails at query time on EVERY visual:

    MdxScript(Model) (17, 16) Cannot find table '_Client_c Campaigns'.

TMDL import validates structure and syntax, not DAX name resolution
(expressions compile lazily into MdxScript). This test makes the rule an
invariant, so it holds however the table disappeared.

Auto-fix is narrow by design and never rewrites arbitrary DAX: only a whole
generated enumeration line (`ISFILTERED('T') || ISINSCOPE('T'[c]) || ...`)
naming the dead table is dropped. Its safety class is `safe: false`, so it runs
only when D004 is selected explicitly.

Implementation: the script subprocess is replaced by `tmdl-preflight check --select D004`
and `tmdl-preflight fix --select D004`; model discovery by the stand-in
`tests/fixtures/test_dax_parsable_bikeshop` and its variants; the repair switch
`PBI_AUTOFIX` by an explicit `autofix` parameter (the generic env knob is
`PREFLIGHT_AUTOFIX`, default off).
"""
from __future__ import annotations

import json
import os

import pytest

from conftest import run_check, run_fix

FIXTURE = "test_dax_parsable_bikeshop"


def _autofix_enabled() -> bool:
    """PREFLIGHT_AUTOFIX defaults to 0; only an explicit non-zero value enables repair."""
    return os.getenv("PREFLIGHT_AUTOFIX", "0") != "0"


def _materialize(stand_in, variant):
    root = stand_in(FIXTURE)
    if variant:
        for op in json.loads((root / "variants.json").read_text(encoding="utf-8"))[variant]:
            f = root / op["file"]
            if "write" in op:
                f.write_text(op["write"], encoding="utf-8")
            else:
                text = f.read_text(encoding="utf-8")
                assert text.count(op["old"]) == 1
                f.write_text(text.replace(op["old"], op["new"]), encoding="utf-8")
    (root / "variants.json").unlink()
    return root / "BikeShop.SemanticModel" / "definition"


def _gate(definition, autofix: bool):
    if not (definition / "tables").is_dir():
        pytest.skip("model has no tables/")

    code, first = run_check(definition, "D004")
    if code == 0:
        return

    if not autofix:
        raise AssertionError(
            "DAX references a table that does not exist in the model — this "
            "imports fine and then breaks every visual at query time.\n\n"
            f"{first}\nRepair with:\n  tmdl-preflight fix --select D004 {definition}\n"
            "If a table was removed outside `retire.table`, also check the culture "
            "rule for orphan bindings."
        )

    fix_code, fixed = run_fix(definition, "D004")
    again_code, again = run_check(definition, "D004")
    assert again_code == 0, (
        "dangling DAX table references remain after auto-fix (arbitrary DAX is "
        "never rewritten — these need a human decision):\n\n"
        f"--- fix output ---\n{fixed}\n--- re-check ---\n{again}"
    )


def _snapshot(root):
    return {p: p.read_bytes() for p in root.rglob("*.tmdl")}


@pytest.mark.parametrize("variant,autofix,verdict,changed", [
    (None, False, "pass", []),
    (None, True, "pass", []),
    ("dangling_table_measure", False, "fail", []),
    ("dangling_table_measure", True, "fail", []),
    ("dangling_enumeration_line", False, "fail", []),
    ("dangling_enumeration_line", True, "pass", ["Shop Measures.tmdl"]),
    ("escaped_quote_table", False, "pass", []),
    ("escaped_quote_table", True, "pass", []),
    ("leaked_sort_by_line", False, "pass", []),
    ("leaked_sort_by_line", True, "pass", []),
    # STRICTER (project decision): a reference spelled with other casing still
    # resolves in DAX, but casing mismatches are D004 errors, and the narrow
    # fixer never rewrites them. The earlier verdict was pass.
    ("reference_casing", False, "fail", []),
    ("reference_casing", True, "fail", []),
])
def test_dax_references_resolve(stand_in, variant, autofix, verdict, changed):
    definition = _materialize(stand_in, variant)
    before = _snapshot(definition)
    if verdict == "pass":
        _gate(definition, autofix)
    else:
        with pytest.raises(AssertionError):
            _gate(definition, autofix)
    after = _snapshot(definition)
    assert sorted(p.name for p in before if before[p] != after.get(p)) == changed


def test_enumeration_line_fix_is_exact_and_idempotent(stand_in):
    """Spec case 1c / 2: the fixer deletes exactly the dead-table line; a second
    fix changes nothing."""
    definition = _materialize(stand_in, "dangling_enumeration_line")
    shop = definition / "tables" / "Shop Measures.tmdl"
    before = shop.read_text(encoding="utf-8")
    run_fix(definition, "D004")
    after = shop.read_text(encoding="utf-8")
    removed = [l for l in before.splitlines() if l not in after.splitlines()]
    assert len(removed) == 1 and "'Rentals'" in removed[0]
    run_fix(definition, "D004")
    assert shop.read_text(encoding="utf-8") == after


def test_blanket_fix_skips_the_narrow_d004_fixer(stand_in):
    """safe: false fixers never run in a blanket fix (A-check-is-read-only rule 4)."""
    definition = _materialize(stand_in, "dangling_enumeration_line")
    shop = definition / "tables" / "Shop Measures.tmdl"
    before = shop.read_text(encoding="utf-8")
    run_fix(definition)
    assert "ISFILTERED('Rentals')" in shop.read_text(encoding="utf-8")
    assert shop.read_text(encoding="utf-8") == before
