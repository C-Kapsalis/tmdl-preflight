"""Refresh-policy parity: the finding texts, the repair report and the
coverage gate (P001 refresh-policy-repair, P002 refresh-policy-coverage).

The wording of a finding is part of the contract: a team reads the message,
not the rule id, so the texts are checked byte for byte here.

Stand-ins (tests/fixtures/b3-a2/incremental_refresh_policy/parity):
- ``ir_worse_db``: Worse carries a policy with every scalar out of its
  domain and an unknown property; Empty carries a policy with no
  sourceExpression on a table with only a calculated partition.
- ``ir_fix_db``: Ads has a windowed source and no policy, Drift's
  sourceExpression drifted from its partition source, Orders loads through
  the loader call.
- ``ir_ledger_db``: Ledger's source keeps other steps around the loader call.
- ``ir_stamp_db``: Stamp windows on the ETL load stamp.
"""
from __future__ import annotations

import json

from conftest import run_check, run_cli, violations, write_config
from tmdl_preflight.refresh import read_layout

ROOT = "b3-a2/incremental_refresh_policy/parity"
STRUCT = "refresh-policy-repair"
COVER = "refresh-policy-coverage"

TEMPLATE = ("let ir_dfilter = \" cast({date_column} as date) >= RangeStart\", "
            "ir_qstr = \"SELECT * FROM {view}\", ir_src = Value.NativeQuery(Warehouse, ir_qstr) "
            "in ir_src")

CONFIG = {"refresh_policy": {"loader_function": "source_filter_dates",
                             "window_markers": ["ir_dfilter"],
                             "etl_stamp_columns": ["updated_at_db"],
                             "inline_template": TEMPLATE}}


def _model(root, name):
    return root / name / "Roastery.SemanticModel"


def _table(root, model, name):
    return _model(root, model) / "definition" / "tables" / f"{name}.tmdl"


def _messages(payload, rule):
    return [v["message"] for v in violations(payload, rule)]


# ---------------------------------------------------------------------------
# P001: the finding texts
# ---------------------------------------------------------------------------


def test_policy_problems_use_the_original_wording(stand_in):
    """One finding per problem, the message '<table>: <problem>'."""
    root = stand_in(ROOT)
    code, payload = run_check(_model(root, "ir_worse_db"), STRUCT, config=CONFIG)
    found = [v["message"] for v in violations(payload, "P001") if v["object"] == "Worse"]
    assert found == [
        "Worse: policyType 'hybrid' not in ('basic',)",
        "Worse: rollingWindowGranularity 'week' not in "
        "('day', 'month', 'quarter', 'year')",
        "Worse: rollingWindowPeriods must be a positive integer (got -1)",
        "Worse: incrementalPeriods must be a positive integer (got 0)",
        "Worse: unrecognized refreshPolicy propert(ies): foo",
    ]


def test_a_policy_without_a_source_expression_is_reported_once(stand_in):
    """'no sourceExpression' hides the partition and the window problems."""
    root = stand_in(ROOT)
    code, payload = run_check(_model(root, "ir_worse_db"), STRUCT, config=CONFIG)
    found = [v for v in violations(payload, "P001") if v["object"] == "Empty"]
    assert _messages({"violations": found}, "P001") == [
        "Empty: refreshPolicy has no sourceExpression"]


def test_only_the_drifted_source_expression_is_auto_fixable(stand_in):
    """The other problems need a human, so they are not counted."""
    root = stand_in(ROOT)
    code, payload = run_check(_model(root, "ir_worse_db"), STRUCT, config=CONFIG)
    assert all(not v["fixable"] for v in violations(payload, "P001"))


# ---------------------------------------------------------------------------
# P001: the repair report
# ---------------------------------------------------------------------------


def test_repair_report_lists_what_was_repaired_and_what_owes_a_refresh(stand_in):
    root = stand_in(ROOT)
    cfg = write_config(root, CONFIG)
    code, out, err = run_cli("fix", str(_model(root, "ir_fix_db")),
                             "--select", STRUCT, "--config", str(cfg))
    assert "REPAIRED 3 table(s):" in out, out
    assert "  [invalid] Drift: realigned sourceExpression to partition 'Drift'" in out, out
    assert ("  [missing] Ads: reinstated refreshPolicy over an already-windowed source "
            "(metadata-only); archive 6xyear, incremental 3xmonth") in out, out
    assert ("  [missing] Orders: windowed on order_date (view 'orders_n', "
            "floor #\"v-fromdate\"); archive 6xyear, incremental 3xmonth") in out, out
    assert ("Metadata-only (1 table(s)) -- block reinstated over an already-windowed "
            "source, NO refresh owed:") in out, out
    assert "  - Ads" in out, out
    assert ("==========================================================================\n"
            "(!)  MANUAL XMLA FULL REFRESH REQUIRED -- the partition M source changed\n"
            "==========================================================================") in out, out
    assert "Tables needing a full refresh (1):" in out, out
    assert "  - Orders" in out, out


def test_a_loader_table_without_a_template_is_reported_not_skipped(stand_in):
    root = stand_in(ROOT)
    cfg = write_config(root, {"refresh_policy": {
        "loader_function": "source_filter_dates", "window_markers": ["ir_dfilter"]}})
    before = _table(root, "ir_fix_db", "Orders").read_bytes()
    code, out, err = run_cli("fix", str(_model(root, "ir_fix_db")),
                             "--select", f"{STRUCT},{COVER}", "--config", str(cfg))
    assert _table(root, "ir_fix_db", "Orders").read_bytes() == before
    assert "FAILED 1 table(s) -- repair NOT applied:" in out, out
    assert "  [missing] Orders: no inline_template configured" in out, out


def test_the_repair_replaces_only_the_loader_call(stand_in):
    """The rest of the source stands: the other steps, the line breaks."""
    root = stand_in(ROOT)
    cfg = write_config(root, CONFIG)
    code, out, err = run_cli("fix", str(_model(root, "ir_ledger_db")),
                             "--select", STRUCT, "--config", str(cfg))
    text = _table(root, "ir_ledger_db", "Ledger").read_text(encoding="utf-8")
    layout = read_layout(text.split("\n"))
    body = layout.partitions[0].source.lines(layout.lines)
    assert body[0] == "\t\t\tlet"
    assert body[1] == "\t\t\t    Source = " + TEMPLATE.format(
        view="orders_n", date_column="order_date", floor="#\"v-fromdate\"",
        table="Ledger") + ","
    assert body[2] == "\t\t\t    Other = 1"
    assert body[3] == "\t\t\tin"
    assert body[4] == "\t\t\t    Source"
    # the policy's sourceExpression is the new partition body, line for line
    assert layout.policy.expression.lines(layout.lines) == body


def test_the_written_policy_closes_its_fence_with_four_tabs(stand_in):
    """The partition's own fence may sit at three tabs; the policy's is
    always four."""
    root = stand_in(ROOT)
    cfg = write_config(root, CONFIG)
    code, out, err = run_cli("fix", str(_model(root, "ir_framed_db")),
                             "--select", STRUCT, "--config", str(cfg))
    text = _table(root, "ir_framed_db", "Framed").read_text(encoding="utf-8")
    assert "\n\t\t\t```\n" in text          # the partition's own fence
    assert "\n\t\t\t\t```\n" in text        # the policy's fence


# ---------------------------------------------------------------------------
# P002: the coverage texts
# ---------------------------------------------------------------------------


def test_the_loader_reason_carries_the_load_stamp_caution(stand_in):
    root = stand_in(ROOT)
    code, payload = run_check(_model(root, "ir_stamp_db"), COVER, config=CONFIG)
    found = [v for v in violations(payload, "P002") if v["object"] == "Stamp"]
    assert len(found) == 1
    assert found[0]["message"] == (
        "Stamp: event-date fact on view 'stamps_n' windowing on 'updated_at_db' -- should be "
        "incrementally refreshed. CAUTION: 'updated_at_db' is the ETL load stamp, not an event "
        "date -- windowing on it freezes rows the ETL never re-touches. Adjudicate before "
        "policying (exempt it, or repoint the source to a real event date).")


def test_an_exempt_list_of_tables_removes_the_finding(stand_in):
    root = stand_in(ROOT)
    cfg = dict(CONFIG)
    cfg["refresh_policy"] = dict(CONFIG["refresh_policy"])
    cfg["refresh_policy"]["exempt"] = [{"table": "Stamp", "reason": "not an event fact"}]
    code, payload = run_check(_model(root, "ir_stamp_db"), COVER, config=cfg)
    assert not [v for v in violations(payload, "P002") if v["object"] == "Stamp"]


def test_the_backlog_declares_a_gap(stand_in):
    root = stand_in(ROOT)
    cfg = dict(CONFIG)
    cfg["refresh_policy"] = dict(CONFIG["refresh_policy"])
    cfg["refresh_policy"]["backlog"] = {"ir_stamp_db/Roastery": ["Stamp"]}
    code, payload = run_check(root, COVER, config=cfg)
    assert not [v for v in violations(payload, "P002") if v["object"] == "Stamp"]


# ---------------------------------------------------------------------------
# fix --check
# ---------------------------------------------------------------------------


def test_a_blanket_fix_check_does_not_count_the_unsafe_fixer(stand_in):
    """P001's fixer changes what the partition stores, so a blanket fix
    does not run it -- and a blanket `fix --check` does not count it."""
    root = stand_in(ROOT)
    cfg = write_config(root, CONFIG)
    code, out, err = run_cli("fix", str(_model(root, "ir_drift_db")), "--check",
                             "--config", str(cfg))
    assert code == 0, out
    assert "P001" not in out, out
    code, out, err = run_cli("fix", str(_model(root, "ir_drift_db")), "--check",
                             "--select", STRUCT, "--config", str(cfg))
    assert code == 1, out
    assert "P001" in out, out


# ---------------------------------------------------------------------------
# the backlog ratchet
# ---------------------------------------------------------------------------


def test_a_repaired_table_is_pruned_from_its_own_model_entry_only(stand_in):
    root = stand_in(ROOT)
    cfg = write_config(root, dict(CONFIG, refresh_policy=dict(
        CONFIG["refresh_policy"],
        backlog={"ir_fix_db/Roastery": ["Orders"], "ir_stamp_db/Roastery": ["Orders"]})))
    code, out, err = run_cli("fix", str(root), "--select", STRUCT, "--config", str(cfg))
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["refresh_policy"]["backlog"]["ir_fix_db/Roastery"] == []
    assert data["refresh_policy"]["backlog"]["ir_stamp_db/Roastery"] == ["Orders"]
    assert "Ratchet: pruned 1 entr(ies) from .tmdl-preflight.json `backlog:`." in out, out
