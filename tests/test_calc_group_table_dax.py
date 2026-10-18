"""
P0: Calc-group & calculated-table DAX — Delimiter Validation

Measures and calculated columns are not the only DAX in a model. DAX also lives
in three other TMDL containers:

- calculated-table partition `source =` blocks (x-/y-Selector field params,
  z-Toggle/z-Selector parameter tables, ...)
- `calculationItem <name> = <expr>` (calculation groups)
- `formatStringDefinition =` blocks (dynamic format strings)

Incident (z-Selector Format): a malformed edit inside the calc group's
formatStringDefinition SWITCH left an orphan `), "P2",` fragment. Nothing parsed
that block, and the broken dynamic format string took down every visual touching
the calc group. This gate closes that hole.

BLOCKING: any unbalanced delimiter in these blocks is a critical break
(the model deploys but visuals error at render time).

Ported: the registry-driven model is replaced by the stand-in
`tests/fixtures/test_dax_parsable_bikeshop` (and its variants); the block
extractor by `SemanticModel.dax_blocks()` / rule `calc-dax-blocks-present`
(spec E-calc-dax-blocks-present, proposed id D010); the balance checker by
rule D001 (spec E-dax-delimiter-balance).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, violations
from tmdl_preflight.parser import parse_model

FIXTURE = "test_dax_parsable_bikeshop"
CALC_KINDS = ("partition_source", "calculation_item", "format_string_definition")
BLOCKS_RULE = "calc-dax-blocks-present"
BLOCKS_CONFIG = {"rules": {BLOCKS_RULE: {"enabled": True}}}


def _materialize(stand_in, variant):
    root = stand_in(FIXTURE)
    if variant:
        for op in json.loads((root / "variants.json").read_text(encoding="utf-8"))[variant]:
            f = root / op["file"]
            if op.get("delete"):
                f.unlink()
            elif "write" in op:
                f.write_text(op["write"], encoding="utf-8")
            else:
                text = f.read_text(encoding="utf-8")
                assert text.count(op["old"]) == 1
                f.write_text(text.replace(op["old"], op["new"]), encoding="utf-8")
    (root / "variants.json").unlink()
    return root / "BikeShop.SemanticModel"


def _calc_blocks(model_dir: Path):
    model = parse_model(model_dir / "definition")
    return [b for b in model.dax_blocks() if b.kind in CALC_KINDS]


def _blocks_found_gate(model_dir: Path):
    """Extractor sanity: every model ships field params + the format calc group,
    so finding zero blocks means an extractor regression, not a clean model."""
    tmdl_dax_blocks = _calc_blocks(model_dir)
    assert tmdl_dax_blocks, (
        "No calculated-table / calculation-group DAX blocks extracted — "
        "extractor regression or unexpected TMDL layout."
    )
    code, payload = run_check(model_dir, BLOCKS_RULE, config=BLOCKS_CONFIG)
    assert code in (0, 1), f"preflight usage error: {payload}"
    assert violations(payload) == [], payload
    by_type: dict[str, int] = {}
    for b in tmdl_dax_blocks:
        by_type[b.kind] = by_type.get(b.kind, 0) + 1
    return by_type


def _balanced_gate(model_dir: Path):
    """Every calc-table source / calculationItem / formatStringDefinition
    expression must have balanced delimiters (comments stripped first,
    so commented-out rows are NOT false positives)."""
    calc_names = {(b.table, b.name) for b in _calc_blocks(model_dir)}
    code, payload = run_check(model_dir, "D001")
    failures = [
        v for v in violations(payload, "D001")
        if any(t in (v.get("object") or "") for t, _ in calc_names)
    ]
    assert not failures, (
        f"Found {len(failures)} calc-group/calc-table DAX block(s) with "
        f"unbalanced delimiters — CRITICAL: this breaks visuals at render "
        f"time while still deploying cleanly:\n"
        + "\n".join(f"  [FAIL] {v.get('object')}: {v['message']}" for v in failures)
    )


@pytest.mark.parametrize("variant,verdict", [
    (None, "pass"),
    ("only_m_partitions", "fail"),
])
def test_calc_group_and_calc_table_dax_blocks_found(stand_in, variant, verdict):
    model_dir = _materialize(stand_in, variant)
    if verdict == "pass":
        by_type = _blocks_found_gate(model_dir)
        assert by_type == {"partition_source": 1, "calculation_item": 1,
                           "format_string_definition": 1}
    else:
        with pytest.raises(AssertionError):
            _blocks_found_gate(model_dir)
        code, payload = run_check(model_dir, BLOCKS_RULE, config=BLOCKS_CONFIG)
        found = violations(payload)
        assert found and all(v["severity"] == "warning" for v in found)


@pytest.mark.parametrize("variant,verdict", [
    (None, "pass"),
    ("fsd_orphan_fragment", "fail"),
])
def test_calc_group_and_calc_table_dax_balanced(stand_in, variant, verdict):
    model_dir = _materialize(stand_in, variant)
    if verdict == "pass":
        _balanced_gate(model_dir)
    else:
        with pytest.raises(AssertionError):
            _balanced_gate(model_dir)
