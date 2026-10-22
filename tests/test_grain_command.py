"""The `grain` command: the derived verdict table, its layout, the coverage
check and the two error paths (spec B-grain-guard-coverage).

The fixture is a fictional delivery model: a cost fact (`Campaigns`), two
backend facts (`_Users`, `Transactions`) and a set of dimensions that reach
one, the other or neither. Every measurement below is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli

TAG = "3c4d5e6f-0000-4000-8000-{:012d}"

TABLES = {
    "Campaigns": ["campaign_id", "country_id", "region_id", "user_id"],
    "_Users": ["user_id", "country_id", "region_id"],
    "Transactions": ["user_id", "offer_id", "country_id", "region_id", "date"],
    "_Countries": ["country_id", "Country"],
    "_Campaigns": ["campaign_id", "Name"],
    "_Offers": ["offer_id"],
    "_Regions": ["region_id"],
    "_Crawl": ["crawl_id"],
    "__Calendar": ["Date"],
}

RELS = "".join(
    f"relationship r{k}\n\tfromColumn: {f}\n\ttoColumn: {t_}\n"
    + ("\tisActive: false\n" if inactive else "")
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

GUARD_TABLE = "#Backend Measures"
GUARD_MEASURE = "-helper Cost Grain Valid"

#: The columns the y-axis field parameter puts on an axis.
ALL_COLUMNS = [("_Campaigns", "Name"), ("_Campaigns", "Channel"),
               ("_Offers", "offer_id"), ("_Countries", "Country")]


def _table(d: Path, name: str, cols: list[str], extra: str = "", n: int = 1) -> None:
    body = f"table '{name}'\n\tlineageTag: {TAG.format(n)}\n\n"
    for k, c in enumerate(cols):
        body += (f"\tcolumn {c}\n\t\tdataType: string\n\t\tlineageTag: {TAG.format(n * 100 + k)}\n"
                 f"\t\tsourceColumn: {c}\n\n")
    body += extra
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = Sql.Database(\"s\", \"d\")\n"
    (d / f"{name}.tmdl").write_text(body, encoding="utf-8")


def _delivery(tmp_path: Path, guard: str, rels: str = RELS, columns=None,
              users_is_fact: bool = False) -> Path:
    d = tmp_path / "Coffee.SemanticModel" / "definition"
    t = d / "tables"
    t.mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    for n, (name, cols) in enumerate(TABLES.items(), start=1):
        _table(t, name, cols, n=n)
    guard_body = f"\tmeasure '{GUARD_MEASURE}' = ```\n{guard}\n\t\t\t```\n" \
                 f"\t\tlineageTag: {TAG.format(2001)}\n\n"
    _table(t, GUARD_TABLE, [], n=20, extra=guard_body)
    rows = ALL_COLUMNS if columns is None else columns
    source = "".join(f"\t\t\t\t  (\"{t_}\", NAMEOF('{t_}'[{c}]), {i})\n"
                      for i, (t_, c) in enumerate(rows))
    (t / "y-Selector 1.tmdl").write_text(
        f"table 'y-Selector 1'\n\tlineageTag: {TAG.format(30)}\n\n"
        "\tpartition 'y-Selector 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\t{\n" + source + "\t\t\t\t }\n", encoding="utf-8")
    (d / "relationships.tmdl").write_text(rels, encoding="utf-8")
    if users_is_fact:
        # _Users becomes a backend fact of its own: it is related to the cost
        # fact and to the other backend fact, so a filter on it reaches both.
        rel = d / "relationships.tmdl"
        rel.write_text(rel.read_text(encoding="utf-8") +
                       "relationship ru\n\tfromColumn: Campaigns.user_id\n\ttoColumn: _Users.user_id\n\n"
                       "relationship ru2\n\tfromColumn: Transactions.user_id\n"
                       "toColumn: _Users.user_id\n\n",
                       encoding="utf-8")
    return d.parent


FULL_GUARD = ("\t\t\tISFILTERED ( '_Campaigns' ) || ISINSCOPE ( '_Campaigns'[Name] ) "
              "|| ISINSCOPE ( '_Campaigns'[Channel] ) "
              "|| ISFILTERED ( '_Offers' ) || ISINSCOPE ( '_Offers'[offer_id] )")


def _grain(model, *extra):
    return run_cli("grain", model, *extra)


# ---------------------------------------------------------------------------
# CG-1: a dimension reaches itself
# ---------------------------------------------------------------------------


def test_a_dimension_that_is_also_a_fact_reaches_itself(tmp_path):
    """A backend fact that is also a dimension lists itself among the backend
    facts it reaches, and is CONFORMED when it reaches them all."""
    model = _delivery(tmp_path, FULL_GUARD, users_is_fact=True)
    code, out, _err = _grain(model, "--cost-fact", "Campaigns",
                             "--backend-fact", "_Users", "--backend-fact", "Transactions", "--json")
    assert code == 0
    rows = {r["dimension"]: r for r in json.loads(out)["dimensions"]}
    users = rows["_Users"]
    assert users["backend_reached"] == ["_Users", "Transactions"]
    assert users["verdict"] == "CONFORMED"


# ---------------------------------------------------------------------------
# CG-2: the defaults
# ---------------------------------------------------------------------------


def test_defaults_read_the_cost_and_backend_facts(tmp_path):
    """Without the fact flags the cost fact is Campaigns and the backend facts
    are _Users and Transactions."""
    model = _delivery(tmp_path, FULL_GUARD)
    code, out, _err = _grain(model, "--json")
    assert code == 0
    rows = {r["dimension"]: r for r in json.loads(out)["dimensions"]}
    assert rows["_Countries"]["reaches_cost"] is True
    assert rows["_Countries"]["backend_reached"] == ["_Users", "Transactions"]
    assert rows["_Campaigns"]["verdict"] == "cost-only"
    assert rows["_Offers"]["verdict"] == "backend-only"


def test_backend_fact_flag_replaces_the_default_list(tmp_path):
    model = _delivery(tmp_path, FULL_GUARD)
    code, out, _err = _grain(model, "--backend-fact", "Transactions", "--json")
    assert code == 0
    rows = {r["dimension"]: r for r in json.loads(out)["dimensions"]}
    assert rows["_Countries"]["backend_reached"] == ["Transactions"]
    assert rows["_Users"]["backend_reached"] == []


def test_check_reads_the_default_guard_measure(tmp_path):
    """The guard measure's name starts with a dash, so the flag needs the
    ``=`` form; the default needs no flag at all."""
    model = _delivery(tmp_path, FULL_GUARD)
    code, _out, _err = _grain(model, "--check", "--guard-table", GUARD_TABLE)
    assert code == 0
    code, _out, _err = _grain(model, "--check", "--guard-table", GUARD_TABLE,
                              f"--guard-measure={GUARD_MEASURE}")
    assert code == 0


def test_the_help_text_names_the_equals_form(tmp_path):
    code, out, _err = run_cli("grain", "--help")
    assert code == 0
    assert "--guard-measure=" in out


# ---------------------------------------------------------------------------
# CG-3: the table layout
# ---------------------------------------------------------------------------


def test_the_table_layout_is_byte_exact(tmp_path):
    model = _delivery(tmp_path, FULL_GUARD)
    code, out, _err = _grain(model)
    assert code == 0
    lines = out.split("\n")
    assert lines[0] == ("dimension table                      ->cost ->backend                      "
                        "verdict        y-Selector cols")
    body = [ln for ln in lines[1:] if ln.strip()]
    names = [ln[:36].strip() for ln in body]
    assert names == sorted(names)
    offers = next(ln for ln in body if ln.startswith("_Offers"))
    assert offers == ("_Offers                              -      Transactions                   "
                      "backend-only   1")


def test_every_verdict_appears_in_the_table(tmp_path):
    model = _delivery(tmp_path, FULL_GUARD)
    code, out, _err = _grain(model)
    assert code == 0
    for verdict in ("CONFORMED", "cost-only", "backend-only", "partial", "neither"):
        assert verdict in out


# ---------------------------------------------------------------------------
# CG-4: the --check output
# ---------------------------------------------------------------------------


def test_check_reports_the_gaps_in_order(tmp_path):
    """One missing ISFILTERED, two missing columns and a blocked conformed
    table: the gaps come in the documented order and the count line leads."""
    guard = "\t\t\tISFILTERED ( '_Countries' )"
    model = _delivery(tmp_path, guard, columns=[("_Campaigns", "Name"),
                                                 ("_Campaigns", "Channel"),
                                                 ("_Countries", "Country")])
    code, out, _err = _grain(model, "--check", "--guard-table", GUARD_TABLE)
    assert code == 1
    lines = out.split("\n")
    index = next(i for i, ln in enumerate(lines) if "coverage gap(s)" in ln)
    assert lines[index] == ("4 coverage gap(s) — absence from the deny-list reads as permission:")
    gaps = [ln for ln in lines[index + 1:] if ln.strip()]
    assert gaps[0] == "   _Campaigns: no table-level ISFILTERED"
    assert gaps[1] == "   _Campaigns: axis column '_Campaigns'[Channel] has no ISINSCOPE term"
    assert gaps[2] == "   _Campaigns: axis column '_Campaigns'[Name] has no ISINSCOPE term"
    assert gaps[3] == ("   _Countries: conformed table is blocked table-wide — that blanks the "
                       "headline ratios (column-level ISINSCOPE terms on it are rate-eligibility "
                       "rulings and stay allowed)")
    assert len(gaps) == 4


def test_check_without_gaps_says_so(tmp_path):
    model = _delivery(tmp_path, FULL_GUARD)
    code, out, _err = _grain(model, "--check", "--guard-table", GUARD_TABLE)
    assert code == 0
    assert "guard covers every axis-exposed column of every non-conformed dimension table" in out


# ---------------------------------------------------------------------------
# CG-5: the error paths
# ---------------------------------------------------------------------------


def test_check_without_a_guard_table_is_a_usage_error(tmp_path):
    """BUGFIX: the table still prints first, but a missing --guard-table is
    a usage error (exit 2), not a gap (exit 1)."""
    model = _delivery(tmp_path, FULL_GUARD)
    code, out, err = _grain(model, "--check")
    assert code == 2
    assert "dimension table" in out
    assert err.strip() == "--check needs --guard-table"


def test_check_with_a_guard_that_is_not_fenced(tmp_path):
    model = _delivery(tmp_path, FULL_GUARD)
    code, out, err = _grain(model, "--check", "--guard-table", GUARD_TABLE,
                             "--guard-measure", "Rides")
    assert code == 1
    assert "dimension table" in out
    assert err.strip() == ("guard measure 'Rides' not found in #Backend Measures.tmdl "
                           "(fenced form expected)")


pytestmark = pytest.mark.layer1
