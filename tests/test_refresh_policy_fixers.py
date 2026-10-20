"""The refresh-policy fixer (P001 refresh-policy-repair, which also adds the
policies P002 refresh-policy-coverage reports missing): explicit selection
only, narrow, idempotent."""
from __future__ import annotations

from conftest import run_check, run_fix, violations

ROOT = "b3-a2/incremental_refresh_policy/roastery"
CONFIG = {"refresh_policy": {"loader_function": "source_filter_dates",
                             "window_markers": ["ir_dfilter"]}}


def _tables(root, model):
    return root / model / "definition" / "tables"


def test_blanket_fix_leaves_policies_alone(stand_in):
    root = stand_in(ROOT)
    before = {p: p.read_bytes() for p in root.rglob("*.tmdl")}
    run_fix(root, config=CONFIG)
    assert {p: p.read_bytes() for p in root.rglob("*.tmdl")} == before


def test_invalid_source_expression_is_realigned_and_idempotent(stand_in):
    root = stand_in(ROOT)
    model = root / "ir_bad_db" / "Roastery.SemanticModel"
    orders = _tables(root, "ir_bad_db/Roastery.SemanticModel") / "Orders.tmdl"
    text = orders.read_text(encoding="utf-8")
    run_fix(model, "refresh-policy-repair", config=CONFIG, args=("--only", "invalid"))
    new = orders.read_text(encoding="utf-8")
    assert "orders_m" not in new
    # everything outside the sourceExpression body is byte-identical; the
    # body (and its fence state) now copies the bare partition source
    assert new.split("\t\tsourceExpression")[0] == text.split("\t\tsourceExpression")[0]
    assert new.split("\tpartition")[1] == text.split("\tpartition")[1]
    assert "\t\tsourceExpression =\n" in new
    code, payload = run_check(model, "refresh-policy-repair", config=CONFIG)
    assert not [v for v in violations(payload) if v["object"] == "Orders"]
    first = orders.read_bytes()
    run_fix(model, "refresh-policy-repair", config=CONFIG, args=("--only", "invalid"))
    assert orders.read_bytes() == first


def test_only_missing_does_not_realign(stand_in):
    root = stand_in(ROOT)
    model = root / "ir_bad_db" / "Roastery.SemanticModel"
    orders = _tables(root, "ir_bad_db/Roastery.SemanticModel") / "Orders.tmdl"
    before = orders.read_bytes()
    run_fix(model, "refresh-policy-repair", config=CONFIG, args=("--only", "missing"))
    assert orders.read_bytes() == before


def test_windowed_source_gets_its_policy_back(stand_in):
    root = stand_in(ROOT)
    model = root / "universal" / "Performance.SemanticModel"
    f = _tables(root, "universal/Performance.SemanticModel") / "Deliveries.tmdl"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    run_fix(model, "refresh-policy-repair", config=CONFIG, args=("--only", "missing"))
    raw = f.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    assert "\n\n\trefreshPolicy\n" in text
    assert "\n\n\tpartition Deliveries = m" in text
    code, payload = run_check(model, "refresh-policy-coverage", "refresh-policy-repair",
                              config=CONFIG)
    assert not [v for v in violations(payload) if v["object"] == "Deliveries"]
    first = f.read_bytes()
    run_fix(model, "refresh-policy-repair", config=CONFIG, args=("--only", "missing"))
    assert f.read_bytes() == first


def test_loader_form_needs_a_template(stand_in):
    root = stand_in(ROOT)
    model = root / "universal" / "Performance.SemanticModel"
    f = _tables(root, "universal/Performance.SemanticModel") / "Tastings.tmdl"
    before = f.read_bytes()
    run_fix(model, "refresh-policy-repair", config=CONFIG, args=("--only", "missing"))
    assert f.read_bytes() == before
    cfg = {"refresh_policy": dict(CONFIG["refresh_policy"], inline_template=(
        'let\n    ir_dfilter = "{date_column} >= " & Text.From(RangeStart) & " and {date_column}'
        ' < " & Text.From(RangeEnd),\n    Source = Value.NativeQuery(Warehouse, "select * from'
        ' {view} where " & ir_dfilter)\nin\n    Source'))}
    code, payload = run_fix(model, "refresh-policy-repair", config=cfg, args=("--only", "missing"))
    assert any("full refresh" in x for x in payload["fixes"]), payload
    text = f.read_text(encoding="utf-8")
    assert "tastings_v" in text and "source_filter_dates" not in text
    code, payload = run_check(model, "refresh-policy-repair", config=cfg)
    assert not [v for v in violations(payload) if v["object"] == "Tastings"]
