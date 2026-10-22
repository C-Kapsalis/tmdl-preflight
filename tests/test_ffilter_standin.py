"""The f-filter stand-in: how a fact is judged "already gated".

The forge's gap-fill planner changed what counts as a covered fact, and
tmdl-preflight's `fact-table-filter-coverage` rule follows it:

- an x-row measure with a mapped group that reads the fact DIRECTLY (a
  data read, not only inside a sensor) means the fact is already gated, so
  no f- measure is owed;
- the x-row measure must be user-facing: a helper on an x row is the
  model's own business and never exempts a fact.
"""

from __future__ import annotations

from pathlib import Path

from conftest import run_check, stand_in  # noqa: F401

STANDIN = "layer3_integration_standin"
RULE = "fact-table-filter-coverage"


def _model(stand_in, client="universal") -> Path:
    return stand_in(STANDIN) / client / "Performance.SemanticModel"


def _add_measure(model: Path, table: str, text: str) -> None:
    f = model / "definition" / "tables" / f"{table}.tmdl"
    f.write_text(f.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + text,
                 encoding="utf-8")


def _violations(payload) -> list:
    return payload.get("violations", [])


def test_a_directly_read_fact_is_reported(stand_in):
    """A user-facing x-row measure that reads the fact directly is a gap."""
    model = _model(stand_in, "failing_db")
    code, payload = run_check(model, RULE)
    assert code == 1, payload
    assert "Refunds" in " ".join(v["message"] for v in _violations(payload))


def test_a_helper_on_an_x_row_never_exempts_a_fact(stand_in):
    """A helper measure on an x row is the model's own business."""
    model = _model(stand_in, "failing_db")
    # a helper on the x-Selector's own table, reading the fact directly
    _add_measure(model, "Coffee Measures",
                 "\tmeasure '-Helper Refund' = SUM(Refunds[amount])\n"
                 "\t\tlineageTag: 7c8d9e0f-1a2b-4c3d-8e4f-5a6b7c8d9e0f\n")
    code, payload = run_check(model, RULE)
    assert code == 1, payload
    assert "Refunds" in " ".join(v["message"] for v in _violations(payload))


def test_the_rule_only_reads(stand_in):
    """The rule reports; it never writes."""
    model = _model(stand_in, "failing_db")
    before = {p: p.read_bytes()
              for p in (model / "definition").rglob("*.tmdl")}
    code, payload = run_check(model, RULE)
    assert code == 1, payload
    assert {p: p.read_bytes()
            for p in (model / "definition").rglob("*.tmdl")} == before
