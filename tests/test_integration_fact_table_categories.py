"""Fact-table -> analysis-category attribution (C-zmap-category-attribution).

Library behaviour exposed as ``tmdl-preflight info --categories <model> --json``:
``{"groups": {group_id: [categories]}, "fact_tables": {table: [categories]}}``.
The encoded mapping table is many-to-many; non-attributing groups (axis
spacers, standard calendar groups) never enter the map.
"""
from __future__ import annotations

import json

import pytest

from conftest import run_cli

STANDIN = "layer3_integration_standin"
NON_ATTRIBUTING = {"Blank Measure_x", "Blank Dimension_y", "Date_y", "Date_day_y", "Date_week_y"}


def _categories(stand_in, client="universal", model="Performance.SemanticModel"):
    path = stand_in(STANDIN) / client / model
    code, out, err = run_cli("info", "--categories", path, "--json")
    assert code == 0, err
    return json.loads(out)
def test_zmap_category_map_preserves_many_to_many(stand_in):
    zmap = _categories(stand_in)["groups"]
    assert zmap, "z-Map parsed empty: decoder or model moved"
    multi = {gid: cats for gid, cats in zmap.items() if len(cats) > 1}
    assert multi
    assert len(zmap.get("Ad Group_y", [])) > 1
def test_zmap_non_attributing_groups_excluded(stand_in):
    zmap = _categories(stand_in)["groups"]
    leaked = NON_ATTRIBUTING & set(zmap)
    assert not leaked, sorted(leaked)
def test_derive_fans_out_shared_groups(stand_in):
    cats = _categories(stand_in)["fact_tables"]
    multi_ft = {ft: c for ft, c in cats.items() if len(c) > 1}
    assert multi_ft
    assert sorted(cats["Orders"]) == ["Marketing", "Sales"]
    assert set(cats) >= {"Orders", "Visits"}  # every fact appears
def test_insights_worked_example_m_users_across_x(stand_in):
    zmap = _categories(stand_in, "spinout_02_db", "insights.SemanticModel")["groups"]
    got = set(zmap.get("m_users_across_x", []))
    assert "Report Users" in got and len(got) > 1, sorted(got)
