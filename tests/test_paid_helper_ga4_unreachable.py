"""`-helper y-drilldown paid performance` never blanks the paid surface on
_Queries / _Keywords.

Ported from the layer-1 suite. Per model that declares the paid helper:
  1. the paid helper names neither `_Queries` nor `_Keywords`;
  2. the model declares `-helper y-drilldown ga4 unreachable`, naming both;
  3. every GA4 consumer that blanks on "non_compatible" also blanks on the
     GA4 helper.

Rule (new, selected by name): measure-reference-contract, configured with
the original contracts. The registry universe and the block extractor are
replaced by the stand-in fleet and the tool's model loader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FIXTURES, run_check, violations
from tmdl_preflight.parser import parse_model

FLEET = "measure_organization_fleet"
MODELS = ["universal/Performance.SemanticModel", "spinout_02_db/Performance.SemanticModel"]
IDS = [m.replace(".SemanticModel", "") for m in MODELS]
PAID_HELPER = "-helper y-drilldown paid performance"
GA4_HELPER = "-helper y-drilldown ga4 unreachable"
UNREACHABLE_TABLES = ["_Queries", "_Keywords"]
RULE = "measure-reference-contract"
CONTRACTS = {"rules": {RULE: {"contracts": [
    {"kind": "must_not_reference", "table": "Helper Measures", "measure": PAID_HELPER,
     "tables": UNREACHABLE_TABLES},
    {"kind": "must_reference", "table": "Helper Measures", "measure": GA4_HELPER,
     "tables": UNREACHABLE_TABLES, "anchor": PAID_HELPER},
    {"kind": "co_reference", "table": "Analytics Measures", "measure": PAID_HELPER,
     "literal": "non_compatible", "partner": GA4_HELPER},
]}}}


def _declares(model_dir: Path, name: str) -> bool:
    model = parse_model(model_dir / "definition")
    t = model.tables.get("Helper Measures")
    return bool(t and name in t.measures)


def _findings(stand_in, model_rel, needle):
    code, payload = run_check(stand_in(FLEET) / model_rel, RULE, config=CONTRACTS)
    return code, [v for v in violations(payload) if needle in v["message"]]


def test_universe_is_the_fleet():
    models = [FIXTURES / FLEET / m for m in MODELS if _declares(FIXTURES / FLEET / m, PAID_HELPER)]
    assert len(models) >= 2 and any("universal" in str(m) for m in models)


@pytest.mark.parametrize("model_rel", MODELS, ids=IDS)
def test_paid_helper_never_names_queries_or_keywords(stand_in, model_rel):
    code, found = _findings(stand_in, model_rel, "must not reference")
    if model_rel.startswith("universal"):
        assert code == 0
        assert found == []
    else:
        # original: "the paid helper names ['_Queries']"
        assert len(found) == 1 and "_Queries" in found[0]["message"]
        assert code == 1


@pytest.mark.parametrize("model_rel", MODELS, ids=IDS)
def test_ga4_helper_carries_the_unreachable_tables(stand_in, model_rel):
    code, found = _findings(stand_in, model_rel, "must reference")
    if model_rel.startswith("universal"):
        assert code == 0
        assert found == []
    else:
        # original: "[-helper y-drilldown ga4 unreachable] does not name ['_Keywords']"
        # (a `--` comment line naming the table does not count)
        assert len(found) == 1 and "_Keywords" in found[0]["message"]
        assert code == 1


@pytest.mark.parametrize("model_rel", MODELS, ids=IDS)
def test_ga4_consumers_blank_on_the_ga4_helper(stand_in, model_rel):
    model = stand_in(FLEET) / model_rel
    if not (model / "definition" / "tables" / "Analytics Measures.tmdl").is_file():
        pytest.skip("no Analytics Measures")
    code, payload = run_check(model, RULE, config=CONTRACTS)
    bare = [v for v in violations(payload) if "Analytics Measures" in v["message"]]
    if model_rel.startswith("universal"):
        assert code == 0
        assert bare == []
    else:
        # original: '1 GA4 consumer(s) blank only on "non_compatible"'
        assert len(bare) == 1
        assert code == 1
