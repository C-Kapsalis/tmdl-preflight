"""f-All analysis-category coverage gates (spec A-category-gate-coverage).

`f-Filters[f-All]` is the orchestrator every visual-level filter routes
through. It gates each analysis category with

    IF(CONTAINSSTRING(all_cats, "<Category>"), IF([f-<measure>] > 0, ...), ...)

once in the `temp_basic` (AND) chain and once in `temp_alt` (OR). A category
that owns an `f-` measure but has no gate is silently excluded from filtering;
a literal that matches no registered category never fires; a literal that is a
substring of two categories gates both on the wrong fact. Every query still
succeeds, so nothing else reports it.

Registered categories are decoded from the encoded mapping table (`z-Map*`).
Coverage is substring based, because that is what CONTAINSSTRING does.

The rule `category-gate-coverage` reports one finding per check; the
message names the check:
  (1) ``unpaired-chains``          AND and OR chains gate different literals [error]
  (2) ``undeclared-gate-measure``  `IF([f-X] > 0` names an undeclared measure [error]
  (3) ``coverage-gap``             category with a resolvable measure, ungated [warning, ratchet]
  (4) ``ungated-without-measure``  ungated category with no measure [warning, ratchet]
  (5) ``inert-literal``            literal matches no category [error]
  (6) ``over-broad-literal``       literal matches more than one category [warning, ratchet]
Baseline entries that no longer apply produce a finding of their own (the
baselines only shrink). Each earlier test fails when its check reports for
the model; the test asserts the tool reports exactly that.

A check that cannot run is listed as skipped, with the reason: no
f-Filters.tmdl, an f-All that is absent or non-canonical, or no decodable
z-Map to derive the registered categories from.

Stand-ins (tests/fixtures/b3-a2/f_all_category_coverage/roastery):
- ``universal/Performance``: every check clean, relying on the fleet-wide
  inert-literal allowance (``Keywords``) and the per-model over-broad allowance
  (``Email Marketing`` spans two categories); a commented `// [f-Sitemap]` gate
  line is ignored.
- ``cg_db/Roastery``: every check fires (``Beans`` only in AND; live
  `IF([f-Roast] > 0`; ``Email Marketing Lists`` resolves through
  ``f-Email_Marketing_Lists`` but is ungated; ``Cold Brew`` and
  ``Email Marketing Campaigns`` have no measure; literal ``Tea`` is inert;
  ``Spend`` matches ``Spend`` and ``Blended Spend``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import run_check, violations

RULE = "category-gate-coverage"

# Stand-in baseline: same keys as the spec's category-gates.baseline.json,
# holding only what the stand-in models need.
BASELINE = {
    "coverage_gaps": {},
    "ungated_without_measure": {},
    "inert_literals": {},
    "fleet_inert_literals": ["Keywords"],
    "over_broad_literals": {"universal/Performance": ["Email Marketing"]},
}

MODELS = [
    pytest.param("universal/Performance.SemanticModel", "pass", id="universal/Performance"),
    pytest.param("cg_db/Roastery.SemanticModel", "fail", id="cg_db/Roastery"),
]


@pytest.fixture
def report(stand_in, tmp_path):
    root = stand_in("b3-a2/f_all_category_coverage/roastery")

    def _run(baseline=None):
        base = tmp_path / "category-gates.baseline.json"
        base.write_text(json.dumps(baseline or BASELINE, indent=2), encoding="utf-8")
        _code, payload = run_check(root, RULE, config={"rules": {RULE: {"baseline": str(base)}}})
        assert "summary" in payload, payload   # the rule ran (no usage/config error)
        return payload

    return _run


def _hits(payload, folder, check):
    return [v for v in violations(payload)
            if folder in (v.get("file") or "").replace("\\", "/") and check in v["message"]]


def _assert_check(payload, folder, check, verdict, *expected_terms):
    hits = _hits(payload, folder, check)
    if verdict == "pass":
        assert hits == [], hits
    else:
        assert hits, f"expected a {check} finding for {folder}"
        text = " ".join(h["message"] for h in hits)
        for term in expected_terms:
            assert term in text


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_f_all_chains_are_paired(report, folder, verdict):
    """temp_basic and temp_alt gate exactly the same categories (p0)."""
    _assert_check(report(), folder, "unpaired-chains", verdict, "Beans")


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_f_all_gates_reference_existing_measures(report, folder, verdict):
    """Every live `IF([f-X] > 0` resolves to a declared f- measure (p0)."""
    payload = report()
    _assert_check(payload, folder, "undeclared-gate-measure", verdict, "f-Roast")
    assert not any("f-Sitemap" in v["message"] for v in violations(payload))


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_f_all_gates_every_registered_category(report, folder, verdict):
    """Registered category + resolvable f- measure => gated (p1, ratchet)."""
    payload = report()
    _assert_check(payload, folder, "coverage-gap", verdict, "Email Marketing Lists")
    assert not [h for h in _hits(payload, folder, "coverage-gap") if "stale" in h["message"]]


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_registered_category_without_measure_is_declared(report, folder, verdict):
    """Ungated category with no resolvable measure => declared (p1, ratchet)."""
    _assert_check(report(), folder, "ungated-without-measure", verdict,
                  "Cold Brew", "Email Marketing Campaigns")


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_f_all_literals_match_a_registered_category(report, folder, verdict):
    """Every gate literal matches some registered category, or is allowed (p0)."""
    payload = report()
    _assert_check(payload, folder, "inert-literal", verdict, "Tea")
    # the fleet-wide allowance is never reported stale
    assert not any("Keywords" in v["message"] for v in violations(payload))


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_f_all_literals_are_not_over_broad(report, folder, verdict):
    """No gate literal spans more than one category unless baselined (p1)."""
    _assert_check(report(), folder, "over-broad-literal", verdict, "Spend")


# --- ratchet tightening (each earlier test also fails on a stale entry) ---

def test_stale_baseline_entries_fail(report):
    stale = dict(BASELINE)
    stale["coverage_gaps"] = {"universal/Performance": ["Beans"]}          # Beans is gated
    stale["ungated_without_measure"] = {"universal/Performance": ["Radio"]}  # not registered
    stale["inert_literals"] = {"universal/Performance": ["Tea"]}            # literal gone
    stale["over_broad_literals"] = {"universal/Performance": ["Email Marketing", "Beans"]}
    payload = report(stale)
    folder = "universal/Performance.SemanticModel"
    for check, term, marker in (("coverage-gap", "Beans", "ratchet must tighten"),
                                ("ungated-without-measure", "Radio", "ratchet must tighten"),
                                ("inert-literal", "Tea", "now match a category"),
                                ("over-broad-literal", "Beans", "ratchet must tighten")):
        hits = [h for h in _hits(payload, folder, check) if marker in h["message"]]
        assert hits and term in hits[0]["message"], (check, payload)


def test_no_mapping_table_skips_checks_3_to_6(stand_in):
    root = stand_in("b3-a2/f_all_category_coverage/roastery")
    (root / "cg_db/Roastery.SemanticModel/definition/tables/z-Map Dimension-Measure Groupings.tmdl").unlink()
    _code, payload = run_check(root, RULE, config={"rules": {RULE: {}}})
    folder = "cg_db/Roastery.SemanticModel"
    assert _hits(payload, folder, "unpaired-chains")
    assert _hits(payload, folder, "undeclared-gate-measure")
    for check in ("coverage-gap", "ungated-without-measure", "inert-literal", "over-broad-literal"):
        assert _hits(payload, folder, check) == []


# --- the messages, one finding per check ----------------------------------

HINT = ("\nRepair: pbip-forge f-filters --model cg_db/Roastery"
        "\n        (append-only: existing/client-specific gates are never touched)")

EXPECTED = {
    "unpaired-chains": (
        "cg_db/Roastery: f-All's AND/OR chains gate different category sets — the "
        "model filters inconsistently depending on how many categories are in scope.\n"
        "  only in temp_basic (AND): ['Beans']\n"
        "  only in temp_alt   (OR): —" + HINT),
    "undeclared-gate-measure": (
        "cg_db/Roastery: f-All gates reference 1 f- measure(s) that are not declared "
        "in f-Filters.tmdl — f-All will fail to evaluate for the entire model: "
        "['f-Roast']"),
    "coverage-gap": (
        "cg_db/Roastery: 1 analysis categor(ies) are registered in the z-Map and own "
        "an f- measure, but f-All does not gate them — those categories are silently "
        "excluded from filtering: ['Email Marketing Lists']\n"
        "  (declared pre-existing gaps for this model: none)" + HINT),
    "ungated-without-measure": (
        "cg_db/Roastery: 2 analysis categor(ies) are registered in the z-Map, gated by "
        "no f-All line, and own no f- measure the gate could reference -- they render "
        "ungated and nothing else reports it: ['Cold Brew', 'Email Marketing Campaigns']\n"
        "  Either add `f-<Category>` (or the underscored variant) + run pbip-forge "
        "f-filters, or retire the z-Map rows, or declare the gap under "
        "ungated_without_measure in {baseline}." + HINT),
    "inert-literal": (
        "cg_db/Roastery: 1 f-All gate literal(s) match no registered z-Map category, "
        "so the gate never fires and the intended category renders ungated: ['Tea']\n"
        "  registered categories: ['Beans', 'Blended Spend', 'Cold Brew', "
        "'Email Marketing Campaigns', 'Email Marketing Lists', 'Spend']\n"
        "  Fix the literal to the z-Map spelling (substring match), or retire the line."),
    "over-broad-literal": (
        "cg_db/Roastery: 1 f-All gate literal(s) span more than one registered z-Map "
        "category, so every category but one is gated on the WRONG fact and nothing "
        "errors: 'Spend' -> ['Blended Spend', 'Spend']\n"
        "  Split into one exact literal per category, each resolving to its own f- "
        "measure, or declare the overlap intentional under over_broad_literals in "
        "{baseline} with a reason."),
}


def test_each_check_reports_one_finding_with_the_original_wording(report, tmp_path):
    payload = report()
    base = str(tmp_path / "category-gates.baseline.json")
    for check, expected in EXPECTED.items():
        hits = _hits(payload, "cg_db/Roastery.SemanticModel", check)
        assert len(hits) == 1, (check, hits)
        assert hits[0]["message"] == f"{check}: " + expected.replace("{baseline}", base)


def test_a_lower_case_gate_literal_is_not_a_gate(report):
    """The source tool spells the gate `CONTAINSSTRING(all_cats, "...")`."""
    payload = report()
    assert _hits(payload, "cg_db/Roastery.SemanticModel", "unpaired-chains")


def test_a_lower_case_gate_literal_is_ignored(stand_in):
    root = stand_in("b3-a2/f_all_category_coverage/roastery")
    gates = root / "cg_db/Roastery.SemanticModel/definition/tables/f-Filters.tmdl"
    gates.write_text(gates.read_text(encoding="utf-8").replace(
        'CONTAINSSTRING(all_cats, "Beans")', 'containsstring(all_cats, "Beans")'),
        encoding="utf-8")
    _code, payload = run_check(root, RULE, config={"rules": {RULE: {}}})
    assert _hits(payload, "cg_db/Roastery.SemanticModel", "unpaired-chains") == []


# --- a check that cannot run is listed as skipped --------------------------

def test_a_model_without_f_filters_is_skipped(stand_in, tmp_path):
    root = stand_in("b3-a2/f_all_category_coverage/roastery")
    (root / "cg_db/Roastery.SemanticModel/definition/tables/f-Filters.tmdl").unlink()
    base = tmp_path / "category-gates.baseline.json"
    base.write_text(json.dumps(BASELINE, indent=2), encoding="utf-8")
    code, payload = run_check(root, RULE,
                              config={"rules": {RULE: {"baseline": str(base)}}})
    assert code == 0, payload
    assert _hits(payload, "cg_db/Roastery.SemanticModel", "unpaired-chains") == []
    assert {"rule": "A004", "model": "cg_db/Roastery",
            "reason": "model has no f-Filters.tmdl"} in payload["skipped"]


def test_an_empty_mapping_table_skips_checks_3_to_6(stand_in, tmp_path):
    """A mapping table that decodes to no rows is no decodable mapping."""
    root = stand_in("b3-a2/f_all_category_coverage/roastery")
    zmap = root / "universal/Performance.SemanticModel/definition/tables/z-Map Dimension-Measure Groupings.tmdl"
    import base64
    import zlib
    blob = base64.b64encode(zlib.compress(b"[]", 9)[2:-4]).decode()
    zmap.write_text(re.sub(r'Binary\.FromText\("[^"]*"', f'Binary.FromText("{blob}")',
                            zmap.read_text(encoding="utf-8")), encoding="utf-8")
    base = tmp_path / "category-gates.baseline.json"
    base.write_text(json.dumps(BASELINE, indent=2), encoding="utf-8")
    code, payload = run_check(root / "universal", RULE,
                              config={"rules": {RULE: {"baseline": str(base)}}})
    assert code == 0, payload
    assert violations(payload) == []
    assert {"rule": "A004", "model": "Performance",
            "reason": "no decodable z-Map to derive registered categories from"} \
        in payload["skipped"]


# --- the priority of the checks --------------------------------------------

F_FILTERS = (
    "table 'f-Filters'\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111121\n\n"
    "\tmeasure 'f-All' =\n"
    "\t\t\tVAR all_cats = CONCATENATEX(VALUES('z-Map Dimension-Measure Groupings'"
    "[Analysis Category]), [Analysis Category], \",\")\n"
    "\t\t\tVAR temp_basic =\n"
    "\t\t\t    IF(CONTAINSSTRING(all_cats, \"Beans\"), IF([f-Beans] > 0, TRUE(), "
    "FALSE()), TRUE())\n"
    "\t\t\tVAR temp_alt =\n"
    "\t\t\t    IF(CONTAINSSTRING(all_cats, \"Beans\"), IF([f-Beans] > 0, TRUE(), "
    "FALSE()), FALSE())\n"
    "\t\t\tRETURN\n"
    "\t\t\t    IF(temp_basic || temp_alt, 1, 0)\n"
    "\t\tlineageTag: 11111111-1111-4111-8111-111111111122\n\n"
    "\tmeasure 'f-Beans' = COUNTROWS(Beans)\n"
    "\t\tlineageTag: 11111111-1111-4111-8111-111111111123\n\n"
    "\tmeasure 'f-Tea' = COUNTROWS(Beans)\n"
    "\t\tlineageTag: 11111111-1111-4111-8111-111111111124\n\n"
    "\tpartition 'f-Filters' = m\n"
    "\t\tmode: import\n"
    "\t\tsource = x\n"
)


def _model_with_gates(tmp_path, zmap_rows, f_filters) -> Path:
    """A model with a mapping table and an f-Filters table."""
    import base64
    import zlib
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\nref table 'z-Map Dimension-Measure Groupings'\nref table 'f-Filters'\n",
        encoding="utf-8")
    payload = json.dumps(zmap_rows, ensure_ascii=True, separators=(", ", ": ")).encode()
    comp = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    blob = base64.b64encode(comp.compress(payload) + comp.flush()).decode()
    (definition / "tables" / "z-Map Dimension-Measure Groupings.tmdl").write_text(
        "table 'z-Map Dimension-Measure Groupings'\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcolumn 'Analysis Category'\n\t\tdataType: string\n\t\tlineageTag: "
        "11111111-1111-4111-8111-111111111112\n\t\tsourceColumn: Analysis Category\n\n"
        "\tcolumn 'Analysis Subcategory'\n\t\tdataType: string\n\t\tlineageTag: "
        "11111111-1111-4111-8111-111111111113\n\t\tsourceColumn: Analysis Subcategory\n\n"
        "\tcolumn category_x_id\n\t\tdataType: string\n\t\tlineageTag: "
        "11111111-1111-4111-8111-111111111114\n\t\tsourceColumn: category_x_id\n\n"
        "\tpartition 'z-Map Dimension-Measure Groupings' = m\n"
        "\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\tlet\n"
        "\t\t\t\t    Source = Table.FromRows(Json.Document(Binary.Decompress("
        f'Binary.FromText("{blob}", BinaryEncoding.Base64), '
        "Compression.Deflate)), let _t = ((type nullable text) meta "
        '[Serialized.Text = true]) in type table [#"Analysis Category" = _t, '
        '#"Analysis Subcategory" = _t, category_x_id = _t])\n'
        "\t\t\t\tin\n"
        "\t\t\t\t    Source\n", encoding="utf-8")
    (definition / "tables" / "f-Filters.tmdl").write_text(f_filters, encoding="utf-8")
    return definition


def test_a_coverage_gap_alone_is_a_warning(tmp_path):
    """P1 = warning: the run passes, --strict is the full run."""
    model = _model_with_gates(tmp_path,
                              [["Beans", "", "Beans_x"], ["Tea", "", "Tea_x"]],
                              F_FILTERS)
    code, payload = run_check(model, RULE, config={"rules": {RULE: {}}})
    assert code == 0, payload
    found = violations(payload, "A004")
    assert len(found) == 1, found
    assert "coverage-gap" in found[0]["message"]
    assert found[0]["severity"] == "warning"


def test_strict_makes_a_coverage_gap_fail(tmp_path):
    model = _model_with_gates(tmp_path,
                              [["Beans", "", "Beans_x"], ["Tea", "", "Tea_x"]],
                              F_FILTERS)
    code, payload = run_check(model, RULE, strict=True, config={"rules": {RULE: {}}})
    assert code == 1, payload


