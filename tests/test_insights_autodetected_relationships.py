"""Zero AutoDetected relationships, and no two ACTIVE relationships on one table pair.

Ported from the layer-1 suite (the original was scoped to one client model,
spinout_02_db/insights, via a module constant; the tool checks every model it scans).
Power BI Desktop re-enables "Autodetect new relationships after data is loaded"
after updates, so the setting is no defence: each refresh can write
``AutoDetected_<guid>`` relationships nobody chose. A wrong one is deleted in
Model view; a right one is ADOPTED by stripping the marker, leaving the bare GUID.

Rules: R007 autodetected-relationships (error; id CONTAINS ``autodetected``, any
case) and R006 ambiguous-active-pair (unordered, case-insensitive).
Stand-ins: ``tests/fixtures/insights_autodetected_relationships/<variant>``; each
variant's relationships.tmdl was placed at the original's constant path and the
original test run unmodified (verdicts in parity-expected.json).
"""

from __future__ import annotations

import pytest

from conftest import run_check, run_fix, violations

FIX = "insights_autodetected_relationships"
AD_ID = "AutoDetected_1a2b3c4d-0000-4000-8000-0000000000aa"


def _model(stand_in, variant):
    return stand_in(FIX) / variant / "Model.SemanticModel"


@pytest.mark.parametrize(
    "variant, verdict, offenders",
    [
        ("ad_active", "fail", 1),
        ("ad_adopted", "pass", 0),
        ("ad_first_line", "fail", 1),      # regression pin: block on line 1
        ("ad_inactive", "fail", 1),        # inactive ones are traps too
        # STRICTER: original matched only ids STARTING with AutoDetected -> pass
        ("ad_mid_lowercase", "fail", 1),
        ("ad_no_underscore", "fail", 1),
        ("dup_active_paths", "pass", 0),
        ("dup_second_inactive", "pass", 0),
        ("dup_reverse_pair", "pass", 0),
    ],
)
def test_insights_has_no_autodetected_relationships(stand_in, variant, verdict, offenders):
    code, payload = run_check(_model(stand_in, variant), "R007")
    found = violations(payload, "R007")
    assert len(found) == offenders, (
        f"{len(found)} AutoDetected relationship(s) in {variant}; Power BI invented "
        "these on a schema refresh. WRONG -> delete in Model view; RIGHT -> adopt it "
        "by stripping the 'AutoDetected_' prefix, leaving the bare GUID."
    )
    if verdict == "fail":
        assert code == 1
        assert all(v["severity"] == "error" for v in found)
    else:
        assert code == 0


@pytest.mark.parametrize(
    "variant, verdict",
    [
        ("ad_active", "pass"),
        ("ad_adopted", "pass"),
        ("ad_first_line", "pass"),
        ("ad_inactive", "pass"),
        ("ad_mid_lowercase", "pass"),
        ("ad_no_underscore", "pass"),
        ("dup_active_paths", "fail"),
        ("dup_second_inactive", "pass"),
        # STRICTER: Orders->Stores plus Stores->Orders, both active. The original
        # keyed the pair directionally and passed; R006 keys it unordered.
        ("dup_reverse_pair", "fail"),
    ],
)
def test_insights_no_duplicate_active_paths(stand_in, variant, verdict):
    code, payload = run_check(_model(stand_in, variant), "R006")
    found = violations(payload, "R006")
    if verdict == "fail":
        assert found, "multiple ACTIVE relationships join the same table pair"
        assert code == 1
    else:
        assert found == [], (
            "Multiple ACTIVE relationships join the same table pair, creating an "
            f"ambiguous filter path: {found}"
        )


# --- fixer (spec H-autodetected-relationship-fix cases 6-8; new tool tests) ---


def test_fix_select_r007_removes_only_the_autodetected_block(stand_in):
    model = _model(stand_in, "ad_active")
    rel_file = model / "definition" / "relationships.tmdl"
    before = rel_file.read_text(encoding="utf-8")
    keep = before.split(f"relationship {AD_ID}")[0]
    code, payload = run_fix(model, "R007")
    after = rel_file.read_text(encoding="utf-8")
    assert AD_ID not in after
    assert after.rstrip("\n") == keep.rstrip("\n")
    assert after.endswith("\n") and not after.endswith("\n\n")
    assert violations(payload, "R007") == []
    # idempotent
    run_fix(model, "R007")
    assert rel_file.read_text(encoding="utf-8") == after


def test_blanket_fix_never_removes_relationships(stand_in):
    model = _model(stand_in, "ad_active")
    rel_file = model / "definition" / "relationships.tmdl"
    before = rel_file.read_bytes()
    code, payload = run_fix(model)
    assert rel_file.read_bytes() == before, "R007 removal is safe:false, opt-in only"
    assert violations(payload, "R007")
