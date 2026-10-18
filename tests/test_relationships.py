"""P0 relationship validation, ported from the layer-1 suite.

Every relationship's endpoints exist, cardinalities are valid, bidirectional
relationships and orphan tables are surfaced, active cycles are reported, and no
two ACTIVE relationships share a table pair.

The original ran on every registered client model; here each case runs on a
stand-in under ``tests/fixtures/relationships_standins/<id>/Model.SemanticModel``.
The original kernel relationship parser and ``index`` are replaced by
``tmdl-preflight check --select <rule> --json``:

* relationships-presence (new, opt-in) - file exists and declares >= 1 relationship
* R001 relationship-endpoints (+ option ``min_endpoint_success_rate`` 0.95)
* R002 relationship-cardinality (valid-values half; the many-to-one floor against
  the template baseline is a template comparison owned by tmdl-drift-doctor)
* R004 relationship-bidirectional, R005 orphan-tables (informational)
* relationship-cycles (new, info)
* R006 ambiguous-active-pair
"""

from __future__ import annotations

import pytest

from conftest import run_check, violations

FIX = "relationships_standins"
ALL = [
    "rel_bad_cardinality", "rel_bidirectional", "rel_capital_cardinality", "rel_casing",
    "rel_clean", "rel_comment_only", "rel_cycle", "rel_cycle_broken", "rel_dup_active",
    "rel_dup_mixed", "rel_dup_one_inactive", "rel_escaped_quotes", "rel_inactive",
    "rel_missing_column", "rel_missing_table", "rel_no_file", "rel_orphans",
    "rel_reverse_pair",
]
ENDPOINT_CONFIG = {"rules": {"R001": {"min_endpoint_success_rate": 0.95}}}


def _model(stand_in, sid):
    return stand_in(FIX) / sid / "Model.SemanticModel"


def _cases(fails, overrides=None):
    overrides = overrides or {}
    return [(s, overrides.get(s, "fail" if s in fails else "pass")) for s in ALL]


@pytest.mark.p0
@pytest.mark.parametrize("sid, verdict", _cases({"rel_comment_only", "rel_no_file"}))
def test_relationships_file_exists(stand_in, sid, verdict):
    code, payload = run_check(_model(stand_in, sid), "relationships-presence", strict=True)
    found = violations(payload)
    if verdict == "fail":
        assert found, "relationships.tmdl missing or parses to zero relationships"
        assert code == 1
    else:
        assert found == []


@pytest.mark.p0
@pytest.mark.parametrize(
    "sid, verdict", _cases({"rel_casing", "rel_missing_column", "rel_missing_table"})
)
def test_relationship_endpoints_exist(stand_in, sid, verdict):
    model = _model(stand_in, sid)
    # --strict kept from the port; casing mismatches are errors (DECISIONS 5)
    code, payload = run_check(model, "R001", config=ENDPOINT_CONFIG, strict=True)
    found = violations(payload, "R001")
    if verdict == "pass":
        assert found == [], f"Broken relationship endpoints: {len(found)}"
        assert code == 0
        return
    assert code == 1
    msgs = " ".join(v["message"] for v in found)
    if sid == "rel_missing_table":
        assert "_Stores" in msgs and "not found" in msgs.lower()
        assert any(v["severity"] == "error" for v in found)
    elif sid == "rel_missing_column":
        assert "store_id" in msgs and "not found" in msgs.lower()
        assert any(v["severity"] == "error" for v in found)
    else:  # rel_casing: DECISIONS 5 makes a casing mismatch an ERROR
        assert [v["severity"] for v in found] == ["error"]
        assert "casing" in msgs.lower()
        code_default, _ = run_check(model, "R001", config=ENDPOINT_CONFIG)
        assert code_default == 1  # fails without --strict too


@pytest.mark.p0
@pytest.mark.parametrize(
    "sid, verdict",
    [c for c in _cases({"rel_bad_cardinality"}) if c[0] not in ("rel_comment_only", "rel_no_file")],
)
def test_relationship_cardinality_valid(stand_in, sid, verdict):
    code, payload = run_check(_model(stand_in, sid), "R002")
    found = violations(payload, "R002")
    if verdict == "fail":
        assert len(found) == 1
        assert "single" in found[0]["message"]
        assert code == 1
    else:
        assert found == [], f"Found {len(found)} invalid cardinalities"


@pytest.mark.p1
@pytest.mark.parametrize("sid", ALL)
def test_bidirectional_relationships_documented(stand_in, sid):
    code, payload = run_check(_model(stand_in, sid), "R004")
    found = violations(payload, "R004")
    assert len(found) == (1 if sid == "rel_bidirectional" else 0)
    assert all(v["severity"] != "error" for v in found)  # advisory only


@pytest.mark.p1
@pytest.mark.parametrize("sid", ALL)
def test_no_orphan_tables(stand_in, sid):
    code, payload = run_check(_model(stand_in, sid), "R005")
    assert all(v["severity"] == "info" for v in violations(payload, "R005"))
    assert code == 0  # informational test


@pytest.mark.p1
@pytest.mark.parametrize("sid", ALL)
def test_no_circular_dependencies(stand_in, sid):
    code, payload = run_check(_model(stand_in, sid), "relationship-cycles")
    found = violations(payload)
    assert len(found) == (1 if sid == "rel_cycle" else 0)
    if found:
        assert all(t in found[0]["message"] for t in ("Alpha", "Beta", "Gamma"))
        assert found[0]["severity"] == "info"
    assert code == 0  # informational test


@pytest.mark.p0
@pytest.mark.parametrize(
    "sid, verdict",
    # STRICTER: rel_reverse_pair (A->B and B->A both active) passed the original
    # (directional key); R006 keys the pair unordered and fails it.
    _cases({"rel_dup_active", "rel_dup_mixed"}, {"rel_reverse_pair": "fail"}),
)
def test_no_ambiguous_active_relationships(stand_in, sid, verdict):
    code, payload = run_check(_model(stand_in, sid), "R006")
    found = violations(payload, "R006")
    if verdict == "fail":
        assert found, "Ambiguous active relationships (>1 active per table pair)"
        assert code == 1
    else:
        assert found == []
