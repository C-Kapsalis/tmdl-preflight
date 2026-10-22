"""Spec cases for relationships, calendars and grain beyond the ported tests:
the grain command (B-grain-guard-coverage), R007's fixer edge cases, the
OR-chain counting and the opt-in R007 fixer flag."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_check, run_cli, run_fix, violations

TAG = "3c4d5e6f-0000-4000-8000-{:012d}"


def _table(d: Path, name: str, cols: list[str], extra: str = "", n: int = 1) -> None:
    body = f"table '{name}'\n\tlineageTag: {TAG.format(n)}\n\n"
    for k, c in enumerate(cols):
        body += (f"\tcolumn {c}\n\t\tdataType: string\n\t\tlineageTag: {TAG.format(n * 100 + k)}\n"
                 f"\t\tsourceColumn: {c}\n\n")
    body += extra
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = Sql.Database(\"s\", \"d\")\n"
    (d / f"{name}.tmdl").write_text(body, encoding="utf-8")


def _delivery(tmp_path: Path, guard: str, rels: str) -> Path:
    d = tmp_path / "Coffee.SemanticModel" / "definition"
    t = d / "tables"
    t.mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    for n, (name, cols) in enumerate({
        "Campaigns": ["campaign_id", "country_id", "region_id"],
        "_Users": ["user_id", "country_id", "region_id"],
        "Transactions": ["user_id", "offer_id", "country_id", "region_id", "date"],
        "_Countries": ["country_id", "Country"],
        "_Campaigns": ["campaign_id", "Name"],
        "_Offers": ["offer_id"],
        "_Regions": ["region_id"],
        "_Crawl": ["crawl_id"],
        "__Calendar": ["Date"],
    }.items(), start=1):
        _table(t, name, cols, n=n)
    _table(t, "#Backend Measures", [], n=20, extra=f"\tmeasure '-helper Grain' = ```\n{guard}\n\t\t\t```\n"
           f"\t\tlineageTag: {TAG.format(2001)}\n\n"
           f"\tmeasure Rides = CALCULATE(COUNTROWS(Transactions), "
           f"USERELATIONSHIP(Transactions[date], '__Calendar'[Date]))\n\t\tlineageTag: {TAG.format(2002)}\n\n")
    (t / "y-Selector 1.tmdl").write_text(
        f"table 'y-Selector 1'\n\tlineageTag: {TAG.format(30)}\n\n"
        "\tpartition 'y-Selector 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\t{ (\"Campaign\", NAMEOF('_Campaigns'[Name]), 0),\n"
        "\t\t\t\t  (\"Country\", NAMEOF('_Countries'[Country]), 1) }\n", encoding="utf-8")
    (d / "relationships.tmdl").write_text(rels, encoding="utf-8")
    return d.parent


RELS = "".join(
    f"relationship r{k}\n\tfromColumn: {f}\n\ttoColumn: {t_}\n" + ("\tisActive: false\n" if inactive else "")
    + ("\tcrossFilteringBehavior: bothDirections\n" if both else "") + "\n"
    for k, (f, t_, inactive, both) in enumerate([
        ("Campaigns.country_id", "_Countries.country_id", False, False),
        ("_Users.country_id", "_Countries.country_id", False, False),
        ("Transactions.country_id", "_Countries.country_id", False, False),
        ("Campaigns.campaign_id", "_Campaigns.campaign_id", False, False),
        ("Transactions.offer_id", "_Offers.offer_id", False, False),
        ("Campaigns.region_id", "_Regions.region_id", False, False),
        ("Transactions.region_id", "_Regions.region_id", False, False),
        ("Transactions.date", "__Calendar.Date", True, False),
        ("_Crawl.crawl_id", "Campaigns.campaign_id", False, False),
    ])
)
FULL_GUARD = "\t\t\tISFILTERED ( '_Campaigns' ) || ISINSCOPE ( '_Campaigns'[Name] )"


def _grain(model, *extra):
    code, out, err = run_cli("grain", model, "--cost-fact", "Campaigns", "--backend-fact", "_Users",
                             "--backend-fact", "Transactions", "--json", *extra)
    return code, json.loads(out) if out.strip() else {"stderr": err}


def test_verdicts(tmp_path):
    code, data = _grain(_delivery(tmp_path, FULL_GUARD, RELS))
    v = {r["dimension"]: r["verdict"] for r in data["dimensions"]}
    assert v["_Countries"] == "CONFORMED"
    assert v["_Campaigns"] == "cost-only"
    assert v["_Offers"] == "backend-only"
    assert v["_Regions"] == "partial"
    assert v["_Crawl"] == "neither"
    # the inactive calendar link counts through USERELATIONSHIP
    cal = next(r for r in data["dimensions"] if r["dimension"] == "__Calendar")
    assert cal["backend_reached"] == ["Transactions"]


def test_permit_and_check(tmp_path):
    model = _delivery(tmp_path, FULL_GUARD, RELS)
    code, data = _grain(model, "--permit", "_Offers")
    assert {r["dimension"]: r["verdict"] for r in data["dimensions"]}["_Offers"] == "CONFORMED"
    code, data = _grain(model, "--check", "--guard-table", "#Backend Measures", "--guard-measure=-helper Grain")
    assert code == 0 and data["gaps"] == []


def test_check_finds_gaps(tmp_path):
    guard = "\t\t\tISINSCOPE ( '_Campaigns'[Name] ) || ISFILTERED ( '_Countries' )"
    model = _delivery(tmp_path, guard, RELS)
    code, data = _grain(model, "--check", "--guard-table", "#Backend Measures", "--guard-measure=-helper Grain")
    assert code == 1
    assert any("_Campaigns: no table-level ISFILTERED" in g for g in data["gaps"])
    assert any("_Countries: conformed table is blocked table-wide" in g for g in data["gaps"])
    code, data = _grain(model, "--check", "--guard-table", "#Backend Measures", "--guard-measure", "Nope")
    assert code == 1 and data["error"]


def test_or_chain_counting(tmp_path):
    terms = " || ".join(f"ISFILTERED('_Campaigns'[c{i}])" for i in range(62))
    model = _delivery(tmp_path, "\t\t\tVAR a = " + terms + "\n\t\t\tRETURN a", RELS)
    found = violations(run_check(model, "dax-or-chain-depth")[1])
    assert len(found) == 1 and "61" in found[0]["message"]
    split = " || ".join(f"ISFILTERED('_Campaigns'[c{i}])" for i in range(50))
    model2 = _delivery(tmp_path / "b", f"\t\t\tVAR a = {split}\n\t\t\tVAR b = {split}\n\t\t\tRETURN a || b", RELS)
    assert violations(run_check(model2, "D012")[1]) == []


def _autodetected(tmp_path, ids):
    model = _delivery(tmp_path, FULL_GUARD, RELS)
    rel = model / "definition" / "relationships.tmdl"
    rel.write_text(rel.read_text(encoding="utf-8") + "".join(
        f"relationship {i}\n\tfromColumn: Campaigns.campaign_id\n\ttoColumn: _Campaigns.campaign_id\n"
        f"\tisActive: false\n" + ("\n" if k < len(ids) - 1 else "") for k, i in enumerate(ids)),
        encoding="utf-8")
    return model, rel


def test_r007_matches_anywhere_and_removes_back_to_back(tmp_path):
    model, rel = _autodetected(tmp_path, ["7c9e-autodetected-xy", "AutoDetectedX"])
    assert len(violations(run_check(model, "R007")[1])) == 2
    run_fix(model, "R007")
    text = rel.read_text(encoding="utf-8")
    assert "autodetected" not in text.lower() and text.endswith("\n") and not text.endswith("\n\n")


def test_r007_config_flag_opts_into_blanket_fix(tmp_path):
    model, rel = _autodetected(tmp_path, ["AutoDetected_1"])
    run_fix(model)
    assert "AutoDetected_1" in rel.read_text(encoding="utf-8")
    run_fix(model, config={"rules": {"R007": {"fix_autodetected_relationships": True}}})
    assert "AutoDetected_1" not in rel.read_text(encoding="utf-8")
