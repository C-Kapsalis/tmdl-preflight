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


_SIBLING = """table '{name}'
\tcolumn '{name}'
\t\tsourceColumn: [Value1]

\tpartition 'p' = calculated
\t\tmode: import
\t\tsource = ```
\t\t\t\t{
{rows}
\t\t\t\t}
\t\t\t\t```
"""

_ROW_TEMPLATE = '\t\t\t\t\t("{label}", NAMEOF(\'_A\'[{field}]), {order}, "{cat}")'


def _write_sibling(tmp_path, name, rows):
    """A sibling field-parameter table holding ``rows`` (label, field, order, category)."""
    tables = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    body = "\n".join(_ROW_TEMPLATE.format(**r) for r in rows)
    f = tables / f"{name}.tmdl"
    f.write_text(_SIBLING.replace("{name}", name).replace("{rows}", body), encoding="utf-8")
    return f


def _retag_many(paths, names, old, new):
    argv = ["fieldparam", "retag", *[str(p) for p in paths],
            "--from", old, "--to", new]
    for name in names:
        argv += ["--names", name]
    return run_cli(*argv)


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
    assert "y-Selector 2.tmdl" in found[0]["message"]


def test_family_covers_the_plot_specific_tables(tmp_path):
    """The y family is the numbered tables AND the plot-specific ones."""
    one = _write_sibling(tmp_path, "y-Selector 1",
                         [{"label": "Main", "field": "m", "order": -997, "cat": "g_a"}])
    two = _write_sibling(tmp_path, "y-Plot Specific 1",
                         [{"label": "Main", "field": "m", "order": -997, "cat": "g_b"}])
    model = one.parent.parent.parent
    code, payload = run_check(model, "fieldparam-retag")
    assert code == 1, payload
    found = violations(payload)
    assert len(found) == 1
    assert found[0]["message"] == (
        "Main is g_b in y-Plot Specific 1.tmdl but g_a in a sibling table")


# ---------------------------------------------------------------------------
# The whole family is retagged, or none of it is
# ---------------------------------------------------------------------------


def test_retag_rewrites_every_file_it_is_given(tmp_path):
    one = _write_sibling(tmp_path, "y-Selector 1",
                         [{"label": "Main", "field": "m", "order": -997, "cat": "g_a"}])
    two = _write_sibling(tmp_path, "y-Selector 2",
                         [{"label": "Main", "field": "m", "order": -997, "cat": "g_a"}])
    code, out, err = _retag_many([one, two], ["Main"], "g_a", "g_b")
    assert code == 0, err
    for f in (one, two):
        assert '"g_b"' in f.read_text(encoding="utf-8")
        assert '"g_a"' not in f.read_text(encoding="utf-8")


def test_retag_writes_nothing_when_one_file_lacks_the_name(tmp_path):
    one = _write_sibling(tmp_path, "y-Selector 1",
                         [{"label": "Main", "field": "m", "order": -997, "cat": "g_a"}])
    two = _write_sibling(tmp_path, "y-Selector 2",
                         [{"label": "Other", "field": "m", "order": -996, "cat": "g_a"}])
    before_one = one.read_text(encoding="utf-8")
    before_two = two.read_text(encoding="utf-8")
    code, out, err = _retag_many([one, two], ["Main"], "g_a", "g_b")
    assert code == 1
    assert one.read_text(encoding="utf-8") == before_one
    assert two.read_text(encoding="utf-8") == before_two


def test_retag_error_names_the_missing_names_and_the_file(tmp_path):
    one = _write_sibling(tmp_path, "y-Selector 1",
                         [{"label": "Main", "field": "m", "order": -997, "cat": "g_a"}])
    two = _write_sibling(tmp_path, "y-Selector 2",
                         [{"label": "Other", "field": "m", "order": -996, "cat": "g_a"}])
    code, out, err = _retag_many([one, two], ["Main"], "g_a", "g_b")
    assert code == 1
    assert ("field-parameter retag incomplete: ['Main'] not found under category "
            "'g_a' in y-Selector 2.tmdl") in err


def test_retag_error_lists_the_missing_names_sorted(tmp_path):
    f = _write(tmp_path)
    code, out, err = _retag(f, ["Main Attribution", "Nope", "Another"], "m_attr_y",
                            "m_attr_sub_y")
    assert code == 1
    assert ("field-parameter retag incomplete: ['Another', 'Nope'] not found under "
            "category 'm_attr_y'") in err


def test_retag_success_lines_follow_the_row_order(tmp_path):
    f = _write_sibling(tmp_path, "y-Selector 1", [
        {"label": "Zebra", "field": "z", "order": -997, "cat": "g_a"},
        {"label": "Alpha", "field": "a", "order": -996, "cat": "g_a"},
    ])
    code, out, err = _retag(f, ["Alpha", "Zebra"], "g_a", "g_b")
    assert code == 0, err
    assert out.index("Zebra") < out.index("Alpha")


def test_retag_accepts_a_name_that_holds_a_comma(tmp_path):
    f = _write_sibling(tmp_path, "y-Selector 1", [
        {"label": "Sessions, Organic", "field": "s", "order": -997, "cat": "g_a"},
        {"label": "Plain", "field": "p", "order": -996, "cat": "g_a"},
    ])
    code, out, err = _retag_many([f], ["Sessions, Organic", "Plain"], "g_a", "g_b")
    assert code == 0, err
    text = f.read_text(encoding="utf-8")
    assert '("Sessions, Organic", NAMEOF(\'_A\'[s]), -997, "g_b")' in text

