"""A blanket ``fix`` names an unsafe fixer it skipped ("not fixed R007: ...
blanket fix skips it") only when that fixer had work in the model: findings
of its own rule, or (P001) the missing policies P002 reports. A model with
nothing for it gets no line about it, and the summary counts do not move.

The unsafe fixers are the ``safe: false`` rows of ``rules --json``.
"""
from __future__ import annotations

import json

from conftest import run_check, run_cli, run_fix

UNSAFE = {"P001", "D004", "R007", "F016"}
SKIP_TEXT = "a blanket fix skips"


def _skipped(payload: dict) -> set[str]:
    return set(payload.get("skipped_fixers", []))


def test_rules_json_lists_exactly_four_unsafe_fixers():
    code, out, _ = run_cli("rules", "--json")
    rows = json.loads(out)
    rows = rows if isinstance(rows, list) else rows["rules"]
    assert {r["id"] for r in rows if r.get("safe") is False} == UNSAFE


def test_clean_model_mentions_no_unsafe_fixer(project):
    code, payload = run_fix(project)
    assert _skipped(payload) == set()
    code, out, _ = run_cli("fix", project, "--no-config")
    assert SKIP_TEXT not in out and "not fixed" not in out


def test_safe_repairs_without_unsafe_findings_mention_none(stand_in):
    """The bike-shop case: safe fixers repair what they can; no unsafe rule
    has a finding, so no 'not fixed' line, and the counts are the re-check's."""
    root = stand_in("fieldparam_double_slash")
    for f in root.rglob("*.tmdl"):
        text = f.read_text(encoding="utf-8")
        # drop the F016 rows so only the safe fixers have work
        if "//" in text:
            f.write_text("\n".join(l for l in text.split("\n")
                                   if "//" not in l or "///" in l), encoding="utf-8")
    code, payload = run_fix(root)
    assert _skipped(payload) & UNSAFE == set()
    assert payload["summary"]["fixes_applied"] > 0
    code, again = run_check(root)
    counts = ("errors", "warnings", "infos")
    assert [payload["summary"][k] for k in counts] == [again["summary"][k] for k in counts]


def test_r007_mentioned_only_with_an_autodetected_relationship(stand_in):
    root = stand_in("insights_autodetected_relationships/ad_mid_lowercase")
    rels = next(root.rglob("relationships.tmdl"))
    before = rels.read_bytes()
    code, out, _ = run_cli("fix", root, "--no-config")
    assert "not fixed  R007: its fixer can change data, so a blanket fix skips it" in out
    assert rels.read_bytes() == before
    code, payload = run_fix(root)
    assert "R007" in _skipped(payload)


def test_r007_selected_on_a_clean_model_still_reports(project):
    """Selecting R007 still runs its fixer, which says it found nothing."""
    code, out, _ = run_cli("fix", project, "--select", "R007", "--no-config")
    assert "No autodetected relationships found" in out
    assert "not fixed" not in out


def test_f016_mentioned_only_with_double_slash_rows(stand_in):
    root = stand_in("fieldparam_double_slash")
    code, payload = run_fix(root)
    assert _skipped(payload) == {"F016"}


def test_d004_mentioned_only_with_a_dangling_reference(stand_in):
    root = stand_in("test_dax_parsable_bikeshop")
    variants = json.loads((root / "variants.json").read_text(encoding="utf-8"))
    (root / "variants.json").unlink()
    code, payload = run_fix(root)
    assert "D004" not in _skipped(payload)
    for op in variants["dangling_table_measure"]:
        f = root / op["file"]
        if "write" in op:
            f.write_text(op["write"], encoding="utf-8")
        else:
            f.write_text(f.read_text(encoding="utf-8").replace(op["old"], op["new"]),
                         encoding="utf-8")
    code, payload = run_fix(root)
    assert "D004" in _skipped(payload)


def test_p001_mentioned_only_with_refresh_policy_work(stand_in):
    root = stand_in("b3-a2/incremental_refresh_policy/roastery")
    code, payload = run_fix(root / "ir_bad_db")
    assert _skipped(payload) == {"P001"}


P002_CONFIG = {"refresh_policy": {"loader_function": "source_filter_dates",
                                  "window_markers": ["ir_dfilter"]}}


def test_p001_not_mentioned_for_unreported_missing_policies(stand_in):
    """ir_ok_db has no P001 finding; P002 (opt-in) is not selected, so the
    report shows nothing P001's fixer would repair and P001 is not named."""
    root = stand_in("b3-a2/incremental_refresh_policy/roastery")
    code, payload = run_fix(root / "ir_ok_db", config=P002_CONFIG)
    assert "P001" not in _skipped(payload)


def test_p001_mentioned_when_p002_reports_a_missing_policy(stand_in):
    """P002's repair belongs to P001's fixer, so a reported P002 finding
    names the skipped P001 fixer, and the files stay as they were."""
    root = stand_in("b3-a2/incremental_refresh_policy/roastery")
    model = root / "ir_ok_db"
    before = {p: p.read_bytes() for p in model.rglob("*.tmdl")}
    cfg = dict(P002_CONFIG, select=["P001", "P002"])
    code, payload = run_fix(model, config=cfg)
    assert [v["rule"] for v in payload["violations"] if v["rule"] == "P002"]
    assert _skipped(payload) == {"P001"}
    assert {p: p.read_bytes() for p in model.rglob("*.tmdl")} == before
