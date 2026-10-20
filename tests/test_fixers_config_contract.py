"""The fixer registry contract (specs H-rule-catalog-markdown, A-check-is-read-only).

The tool's rule registry says, per check, which repair exists and whether
it is safe to impose automatically:

* safety class: every fixable rule reports ``safe`` in ``rules --json``; the
  data-affecting or deleting repairs (refresh-policy repair, the DAX
  table-reference cleanup, autodetected-relationship removal) are
  ``safe: false``, every other fixer ``safe: true``;
* a blanket ``fix`` never runs a ``safe: false`` fixer; selecting it by rule
  id does;
* repairs are opt-in: ``check`` never writes, whatever the environment (an old ``PBI_AUTOFIX=1`` has no effect), and the write verb
  is the only switch.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import run_check, run_cli, run_fix

# The data-affecting refresh-policy repair, the DAX table-reference cleanup
# (D004 dax-reference-resolution) and the autodetected-relationship removal
# (R007) are the unsafe fixers.
UNSAFE = {"refresh-policy-repair", "dax-reference-resolution", "autodetected-relationships"}
FIXABLE_IDS = {"M003", "M004", "M006", "M011", "M013", "F001", "F002", "F003", "B001", "B003"}


def _catalog():
    code, out, _err = run_cli("rules", "--json")
    assert code == 0
    data = json.loads(out)
    return data["rules"] if isinstance(data, dict) else data


def test_every_fixer_declares_a_safety_class():
    fixable = [r for r in _catalog() if r.get("fixable")]
    ids = {r["id"] for r in fixable}
    assert FIXABLE_IDS <= ids
    for r in fixable:
        assert isinstance(r.get("safe"), bool), r
        expected = r.get("name") not in UNSAFE
        assert r["safe"] is expected, r


def test_unsafe_fixers_are_exactly_the_data_affecting_ones():
    unsafe = {r.get("name") for r in _catalog() if r.get("fixable") and r.get("safe") is False}
    assert unsafe == UNSAFE


def _snapshot(root: Path) -> dict:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_blanket_fix_skips_safe_false_fixers(stand_in):
    root = stand_in("b3-a2/incremental_refresh_policy/roastery")
    model = root / "ir_bad_db" / "Roastery.SemanticModel"
    orders = model / "definition" / "tables" / "Orders.tmdl"
    before = orders.read_bytes()
    cfg = {"refresh_policy": {"loader_function": "source_filter_dates",
                              "window_markers": ["ir_dfilter"]}}
    run_fix(model, config=cfg)                       # blanket fix
    assert orders.read_bytes() == before
    run_fix(model, "refresh-policy-repair", config=cfg, args=("--only", "invalid"))
    assert orders.read_bytes() != before             # explicit selection repairs


def test_check_is_read_only_even_with_the_old_repair_switch(stand_in, monkeypatch):
    monkeypatch.setenv("PBI_AUTOFIX", "1")
    root = stand_in("b3-a2/dangling_description_comments/dd_bad")
    before = _snapshot(root)
    code, _payload = run_check(root)
    assert code == 1
    assert _snapshot(root) == before


def test_actions_only_fixers_are_safe_and_run_only_through_fix(stand_in):
    """A CI 'actions only' list (duplicate lineage tags,
    comma runs, missing separators, blank diagram layouts) ran without pytest.
    In the tool those are ordinary safe fixers behind the `fix` verb."""
    by_id = {r["id"]: r for r in _catalog()}
    for rule_id in ("M003", "F001", "F002"):
        assert by_id[rule_id]["fixable"] and by_id[rule_id]["safe"] is True
