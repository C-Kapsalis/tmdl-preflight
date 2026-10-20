"""Incremental-refresh (`refreshPolicy`) gates (specs B-refresh-policy-repair,
A-refresh-policy-coverage).

An eligible fact table with no `refreshPolicy` reloads IN FULL on every
scheduled refresh. A policy whose `sourceExpression` has drifted from its
partition `source` is worse than none: Power BI requires the two to be
identical, so the refresh fails or silently reprocesses the wrong slice. Both
are invisible from the report side.

Two tiers:
  structural (hard)  laws on policies that already exist: identity with the
                     partition source, placement before the partition, in-domain
                     scalars, a windowed source  -> rule `refresh-policy-repair`
  coverage (ratchet) every eligible fact carries a policy or is declared in the
                     per-model backlog; stale backlog entries fail
                     -> rule `refresh-policy-coverage`
Tables whose M source is hand-written are "undecidable": listed as INFO,
never failed.

No auto-imposition: the repair is `safe: false` (it rewrites what the
partition stores) and never runs in a blanket `fix`.

Stand-ins (tests/fixtures/b3-a2/incremental_refresh_policy/roastery):
- ``ir_ok_db/Roastery``: Orders has a valid windowed policy; Returns is
  eligible and backlogged; Waste is hand-written (undecidable); Samples
  (no-filter true) and Imports (empty date column) are ineligible; _Stores is
  not a fact.
- ``ir_bad_db/Roastery``: Orders' sourceExpression differs from its source;
  Brews has policyType hybrid / granularity week / periods 0; Refunds is
  eligible and not backlogged; the backlog lists Oldies, which is not eligible.
- ``universal/Performance`` (the template): 2 invalid policies (drifted source;
  policy after the partition) + 3 eligible tables without a policy.
"""
from __future__ import annotations

import pytest

from conftest import run_check, run_cli, violations, write_config

ROOT = "b3-a2/incremental_refresh_policy/roastery"
STRUCT = "refresh-policy-repair"
COVER = "refresh-policy-coverage"

REFRESH_POLICY = {
    "loader_function": "source_filter_dates",
    "window_markers": ["ir_dfilter"],
    "exempt": {},
    "backlog": {"ir_ok_db/Roastery": ["Returns"], "ir_bad_db/Roastery": ["Oldies"]},
}
CONFIG = {"refresh_policy": REFRESH_POLICY}

MODELS = ["ir_ok_db/Roastery.SemanticModel", "ir_bad_db/Roastery.SemanticModel",
          "universal/Performance.SemanticModel"]


def _ids(m):
    return m.replace(".SemanticModel", "")


def _mine(payload, folder, severity=None):
    assert "summary" in payload, payload   # the rule ran (no usage/config error)
    return [v for v in violations(payload)
            if folder in (v.get("file") or "").replace("\\", "/")
            and (severity is None or v["severity"] == severity)]


@pytest.fixture
def root(stand_in):
    return stand_in(ROOT)


@pytest.mark.parametrize("folder,verdict", list(zip(MODELS, ["pass", "fail", "fail"])),
                         ids=[_ids(m) for m in MODELS])
def test_existing_refresh_policies_are_structurally_valid(root, folder, verdict):
    """sourceExpression == partition source, correct placement, sane scalars."""
    _code, payload = run_check(root, STRUCT, config=CONFIG)
    found = _mine(payload, folder, "error")
    if verdict == "pass":
        assert found == [], found
        return
    text = " ".join(v["message"] for v in found)
    assert "sourceExpression" in text                      # identity, with line + column
    if folder.startswith("ir_bad"):
        assert {v["object"] for v in found} >= {"Orders", "Brews"}
        for term in ("policyType", "rollingWindowGranularity", "rollingWindowPeriods"):
            assert term in text
    else:
        assert {v["object"] for v in found} == {"Orders", "Brews"}
        assert "partition" in text                         # policy after the partition


@pytest.mark.parametrize("folder,verdict,new,stale", [
    ("ir_ok_db/Roastery.SemanticModel", "pass", set(), set()),
    ("ir_bad_db/Roastery.SemanticModel", "fail", {"Refunds"}, {"Oldies"}),
    ("universal/Performance.SemanticModel", "fail", {"Refunds", "Tastings", "Deliveries"}, set()),
], ids=[_ids(m) for m in MODELS])
def test_ir_eligible_facts_have_refresh_policy(root, folder, verdict, new, stale):
    """Every eligible fact carries a policy, or is a DECLARED pre-existing gap."""
    _code, payload = run_check(root, COVER, config=CONFIG)
    failing = [v for v in _mine(payload, folder) if v["severity"] != "info"]
    if verdict == "pass":
        assert failing == [], failing
        return
    got_stale = {v["object"] for v in failing if "stale" in v["message"].lower()}
    got_new = {v["object"] for v in failing} - got_stale
    assert got_new == new
    assert got_stale == stale


@pytest.mark.parametrize("folder", MODELS, ids=_ids)
def test_report_undecidable_ir_tables(root, folder):
    """Advisory inventory of facts with a hand-written M source (never fails)."""
    _code, payload = run_check(root, COVER, config=CONFIG)
    infos = {v["object"] for v in _mine(payload, folder, "info")}
    if folder.startswith("ir_ok"):
        assert infos == {"Waste"}
    else:
        assert infos == set()
    assert all(v["severity"] != "error" for v in _mine(payload, folder)
               if v["object"] == "Waste")


def test_fixer_check_mode_agrees_with_gate(root, tmp_path):
    """`fix --check` exit code == structural count + missing count on the template.

    Guards the split-brain failure: gate and fixer must share one parser.
    """
    template = root / "universal" / "Performance.SemanticModel"
    if not (template / "definition" / "tables").is_dir():
        pytest.skip("template model not present")
    folder = "universal/Performance.SemanticModel"
    _c, structural = run_check(root, STRUCT, config=CONFIG)
    _c, coverage = run_check(root, COVER, config=CONFIG)
    invalid = {v["object"] for v in _mine(structural, folder, "error")}
    missing = {v["object"] for v in _mine(coverage, folder)
               if v["severity"] != "info" and "stale" not in v["message"].lower()}
    expected = min(len(invalid) + len(missing), 255)   # exit statuses are 8-bit
    assert expected == 5
    cfg = write_config(tmp_path, CONFIG)
    before = {p: p.read_bytes() for p in template.rglob("*.tmdl")}
    code, out, err = run_cli("fix", str(template), "--check", "--select", f"{STRUCT},{COVER}",
                             "--config", str(cfg))
    assert code == expected, (out, err)
    assert {p: p.read_bytes() for p in template.rglob("*.tmdl")} == before
