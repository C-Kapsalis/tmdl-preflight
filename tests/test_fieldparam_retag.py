"""Field-parameter category retag (C-fieldparam-retag).

Position 4 of a field-parameter tuple is the row's category. Retagging moves
a field out of one category without deleting it. Three silent failure
modes, one test each: a partial retag across a family of sibling tables, a
same-named row in a different category changed by accident, and a
commented-out row switched back on.

Command under test: ``tmdl-preflight fieldparam retag <files> --names N1,N2
--from OLD --to NEW`` (all or nothing; error text "retag incomplete").
Family rule: ``fieldparam-retag``.
"""
from __future__ import annotations

import re

import pytest

from conftest import run_check, run_cli, violations


STANDIN = "layer3_integration_standin"

_TABLE = """table 'y-Selector 1'
\tcolumn 'y-Selector 1'
\t\tsourceColumn: [Value1]

\tpartition 'p' = calculated
\t\tmode: import
\t\tsource = ```
\t\t\t\t{
\t\t\t\t\t-- m_attr_y
\t\t\t\t\t("Main Attribution (Resolved)", NAMEOF('_Report Attribution Resolved'[m_main_attribution_resolved]), -1000, "m_attr_y", "Main", "Cost"),
\t\t\t\t\t("Main Attribution", NAMEOF('_Report Attribution'[m_main_attribution]), -997, "m_attr_y", "Main", "Cost"),
\t\t\t\t\t-- ("Report SUB Attribution 9", NAMEOF('_Report Attribution'[m_sub_attribution_9]), -996, "m_attr_y", "Sub", "Cost"),
\t\t\t\t\t-- Attribution
\t\t\t\t\t("Main Attribution", NAMEOF('_Attribution LM'[lead_main]), -900, "Attribution", "Lead", "No Cost")
\t\t\t\t}
\t\t\t\t```
"""

_ROW = re.compile(r'^\s*\(\s*"([^"]+)"\s*,\s*NAMEOF\(.*?\)\s*,\s*-?\d+\s*,\s*"([^"]*)"', re.M)


def _entries(text):
    """Live rows as (display, category); disabled (commented) rows excluded."""
    return [(m.group(1), m.group(2)) for m in _ROW.finditer(text)]


def _write(tmp_path, text=_TABLE):
    tables = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    f = tables / "y-Selector 1.tmdl"
    f.write_text(text, encoding="utf-8")
    return f


def _retag(path, names, old, new):
    return run_cli("fieldparam", "retag", path, "--names", ",".join(names), "--from", old, "--to", new)


def test_retag_moves_only_the_named_entries_in_the_named_group(tmp_path):
    f = _write(tmp_path)
    code, out, err = _retag(f, ["Main Attribution"], "m_attr_y", "m_attr_sub_y")
    assert code == 0, err
    assert "Main Attribution" in out
    text = f.read_text(encoding="utf-8")
    entries = dict(_entries(text)[:2])
    assert entries["Main Attribution (Resolved)"] == "m_attr_y"
    assert '(\'_Attribution LM\'[lead_main]), -900, "Attribution"' in text
    assert text.count('"m_attr_sub_y"') == 1


def test_commented_out_row_is_never_reactivated(tmp_path):
    f = _write(tmp_path)
    code, out, err = _retag(f, ["Report SUB Attribution 9"], "m_attr_y", "m_attr_sub_y")
    assert code != 0
    assert "retag incomplete" in (out + err)
    assert f.read_text(encoding="utf-8") == _TABLE


def test_missing_entry_fails_loudly_rather_than_half_retagging(tmp_path):
    f = _write(tmp_path)
    code, out, err = _retag(f, ["Main Attribution", "Nope"], "m_attr_y", "m_attr_sub_y")
    assert code != 0
    assert "retag incomplete" in (out + err)
    assert f.read_text(encoding="utf-8") == _TABLE  # nothing written


def test_wrong_source_category_fails_loudly(tmp_path):
    f = _write(tmp_path)
    code, out, err = _retag(f, ["Main Attribution"], "m_geo_y", "m_attr_sub_y")
    assert code != 0
    assert "retag incomplete" in (out + err)


def test_entry_set_is_preserved_by_a_retag(tmp_path):
    f = _write(tmp_path)
    before = [n for n, _ in _entries(_TABLE)]
    code, _, err = _retag(f, ["Main Attribution"], "m_attr_y", "m_attr_sub_y")
    assert code == 0, err
    assert [n for n, _ in _entries(f.read_text(encoding="utf-8"))] == before
    code, payload = run_check(f.parent.parent.parent, "M002")
    assert violations(payload, "M002") == []  # validity guard


CURATED = {"rules": {"fieldparam-retag": {
    "families": ["y-Selector *"], "curated_categories": ["m_attr_y", "m_attr_sub_y"]}}}


def test_live_spinout_05_family_agrees_on_the_curated_groups(stand_in):
    model = stand_in(STANDIN) / "universal" / "Performance.SemanticModel"
    code, payload = run_check(model, "fieldparam-retag", config=CURATED)
    assert code == 0, payload
    assert violations(payload) == []


def test_half_retagged_family_fails_naming_both_tables(stand_in):
    model = stand_in(STANDIN) / "failing_db" / "Performance.SemanticModel"
    code, payload = run_check(model, "fieldparam-retag", config=CURATED)
    assert code == 1
    found = violations(payload)
    assert len(found) == 1
    assert "Main Attribution" in found[0]["message"]
    assert "y-Selector 1" in found[0]["message"] and "y-Selector 2" in found[0]["message"]
