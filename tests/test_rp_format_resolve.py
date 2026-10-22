"""``format-resolve`` over a path of models, and the format grammar it reads.

The command answers one question per model: which format string does this
measure name get from the format calculation group? A rename moves a name
between the arms of an ordered ``SWITCH(TRUE(), ...)`` chain, so the answer
changes silently. The command therefore resolves the name in EVERY model under
the path, on the measure-name path and on every axis the group branches on,
and prints one row per (model, axis).

The grammar the resolver reads is wider than a plain chain: a parenthesised
condition, ``FALSE()``, a ``TRUE ()`` selector, a lower-case ``return``, a
fenced definition and a ``{...}`` list inside a condition are all read, not
guessed. An arm it cannot read makes the answer ``<unknown>`` and names the
unreadable condition.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations
from tmdl_preflight import format_resolver as fr

TREE = "rp_format_resolve"
UNKNOWN = fr.UNKNOWN


def _tree(stand_in) -> Path:
    return stand_in(TREE)


def _rows(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# RP-1: every model under the path, in sorted model-path order
# ---------------------------------------------------------------------------


def test_resolves_every_model_under_the_path(stand_in):
    tree = _tree(stand_in)
    code, out, _err = run_cli("format-resolve", str(tree), "--name", "Cost/ Conversion")
    assert code == 0
    lines = _rows(out)
    assert lines == [
        "  shop_a/Growth.SemanticModel                    "
        "axis=SELECTEDMEASURENAME      '#,##0 <cur>'",
        "  shop_a/Growth.SemanticModel                    "
        "axis=x-Selector 1             '#,##0.0 <cur>'",
        "  shop_b/Growth.SemanticModel                    "
        "axis=SELECTEDMEASURENAME      '<unknown>'",
        "       unresolved: ['ISFOO(1)', 'ISBAR(2)']",
        "  shop_b/Growth.SemanticModel                    "
        "axis=x-Selector 1             '#,##0.0 <cur>'",
    ]


def test_compare_appends_the_second_name_and_the_change_flag(stand_in):
    tree = _tree(stand_in)
    code, out, _err = run_cli("format-resolve", str(tree), "--name", "Cost/ Conversion",
                              "--compare", "CPA")
    assert code == 0
    lines = _rows(out)
    assert lines[0] == (
        "  shop_a/Growth.SemanticModel                    "
        "axis=SELECTEDMEASURENAME      '#,##0 <cur>'  ->  'General'   ⚠ CHANGES")
    assert lines[2] == (
        "  shop_b/Growth.SemanticModel                    "
        "axis=SELECTEDMEASURENAME      '<unknown>'  ->  '<unknown>'")
    assert "⚠ CHANGES" not in lines[2]


def test_a_model_without_the_calculation_group_is_skipped(tmp_path):
    root = tmp_path / "shop_a" / "Growth.SemanticModel" / "definition" / "tables"
    root.mkdir(parents=True)
    (root / "Sales.tmdl").write_text(
        "table 'Sales'\n\tlineageTag: 00000000-0000-0000-0000-000000000001\n\n"
        "\tcolumn amount\n\t\tdataType: double\n\t\tsourceColumn: amount\n",
        encoding="utf-8")
    code, out, _err = run_cli("format-resolve", str(tmp_path), "--name", "Cost/ Conversion")
    assert code == 0
    assert out.strip() == ""


# ---------------------------------------------------------------------------
# RP-2: an unquoted table in SELECTEDVALUE means "nothing selected"
# ---------------------------------------------------------------------------


def test_unquoted_table_in_selectedvalue_is_nothing_selected():
    body = ('SWITCH(TRUE(), '
            'CONTAINSSTRING(SELECTEDVALUE(Currency[Code]), "usd"), "$#,##0", '
            'CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"), "#,##0.00", '
            '"General")')
    fmt, unresolved = fr.evaluate_definition(body, "Cost/ Conversion")
    assert fmt == "#,##0.00"
    assert unresolved == []


def test_unreadable_condition_never_comes_back_without_a_note():
    body = 'SWITCH(TRUE(), ISFOO(1) && ISBAR(2), "$#,##0", "General")'
    fmt, unresolved = fr.evaluate_definition(body, "Cost/ Conversion")
    assert fmt == UNKNOWN
    assert unresolved == ["ISFOO(1)", "ISBAR(2)"]


# ---------------------------------------------------------------------------
# RP-11: the line format
# ---------------------------------------------------------------------------


def test_the_row_format_pads_the_model_and_the_axis(stand_in):
    tree = _tree(stand_in)
    _code, out, _err = run_cli("format-resolve", str(tree), "--name", "Cost/ Conversion")
    line = _rows(out)[0]
    assert line.startswith("  shop_a/Growth.SemanticModel" + " " * 20 + "axis=")
    axis_field = line[line.index("axis=") + 5:line.index("'")]
    assert axis_field == "SELECTEDMEASURENAME" + " " * 6


def test_the_format_string_is_quoted_python_style():
    body = 'SWITCH(TRUE(), TRUE(), "it\'s here", "General")'
    fmt, _unresolved = fr.evaluate_definition(body, "Cost")
    assert fmt == "it's here"
    assert repr(fmt) == '"it\'s here"'


# ---------------------------------------------------------------------------
# RP-13: the wider grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body,expected", [
    ('SWITCH(TRUE(), (CONTAINSSTRING(SELECTEDMEASURENAME(), "cost")), "#,##0.00", "General")',
     "#,##0.00"),
    ('SWITCH(TRUE(), FALSE(), "#,##0.00", "General")', "General"),
    ('SWITCH(TRUE (), CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"), "#,##0.00", "General")',
     "#,##0.00"),
    ("var _x = 1\nreturn\nSWITCH(TRUE(), CONTAINSSTRING(SELECTEDMEASURENAME(), \"cost\"), "
     '"#,##0.00", "General")', "#,##0.00"),
    ('SWITCH(TRUE(), CONTAINSSTRING(SELECTEDMEASURENAME(), "cost") && {"a","b"} = {"a","b"}, '
     '"#,##0.00", "General")', "#,##0.00"),
])
def test_the_grammar_reads_the_constructs_the_reference_gave_up_on(body, expected):
    fmt, _unresolved = fr.evaluate_definition(body, "Cost/ Conversion")
    assert fmt == expected


def test_a_fenced_definition_is_read(tmp_path):
    f = tmp_path / "z-Selector Format.tmdl"
    f.write_text(
        "table 'z-Selector Format'\n"
        "\tcalculationGroup\n"
        "\t\tcalculationItem Format = SELECTEDMEASURE()\n\n"
        "\t\t\tformatStringDefinition =\n"
        "\t\t\t\t```\n"
        '\t\t\t\tSWITCH(TRUE(), CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"), "#,##0.00", '
        '"General")\n'
        "\t\t\t\t```\n", encoding="utf-8")
    fmt, _unresolved = fr.resolve(f, "Cost/ Conversion")
    assert fmt == "#,##0.00"


# ---------------------------------------------------------------------------
# RP-23: the notes of the resolver
# ---------------------------------------------------------------------------


def test_every_unreadable_condition_of_a_chain_is_recorded():
    body = 'SWITCH(TRUE(), ISFOO(1) && ISBAR(2), "$#,##0", "General")'
    fmt, unresolved = fr.evaluate_definition(body, "Cost/ Conversion")
    assert fmt == UNKNOWN
    assert unresolved == ["ISFOO(1)", "ISBAR(2)"]


def test_a_non_literal_needle_gives_unknown_without_a_note():
    body = 'SWITCH(TRUE(), CONTAINSSTRING(SELECTEDMEASURENAME(), _needle), "#,##0.00", "General")'
    fmt, unresolved = fr.evaluate_definition(body, "Cost")
    assert fmt == UNKNOWN
    assert unresolved == []


def test_an_unquoted_table_in_isinscope_gives_unknown_without_a_note():
    body = 'SWITCH(TRUE(), ISINSCOPE(Foo[bar]), "X", "General")'
    fmt, unresolved = fr.evaluate_definition(body, "Cost")
    assert fmt == UNKNOWN
    assert unresolved == []


def test_a_non_true_selector_is_named_exactly():
    body = 'SWITCH(FALSE(), CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"), "#,##0.00", "General")'
    fmt, unresolved = fr.evaluate_definition(body, "Cost")
    assert fmt == UNKNOWN
    assert unresolved == ["SWITCH on a non-TRUE() selector"]


# ---------------------------------------------------------------------------
# RP-2 / RP-12: the S005 finding
# ---------------------------------------------------------------------------


def test_the_format_min_decimals_finding_names_the_file_and_the_axis(stand_in):
    tree = _tree(stand_in)
    code, payload = run_check(tree, "format-min-decimals", config={
        "rules": {"format-min-decimals": {
            "expectations": [{"name": "Cost/ Conversion", "min_decimals": 1}]}}})
    assert code == 1
    found = violations(payload)
    assert len(found) == 1
    assert found[0]["message"] == (
        "shop_a/Growth.SemanticModel/definition/tables/z-Selector Format.tmdl "
        "axis=SELECTEDMEASURENAME renders 'Cost/ Conversion' as '#,##0 <cur>' "
        "— 0 decimals")
