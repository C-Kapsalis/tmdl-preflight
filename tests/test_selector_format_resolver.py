"""The `z-Selector Format` resolver — and the rename-safety question it answers.

A measure's format is chosen by SUBSTRING-matching its name against an ordered
`SWITCH(TRUE(), …)` chain, so a rename can silently change how a number renders
with nothing in the model erroring. The format resolver is what makes that
answerable before the rename ships; these tests keep it honest.

The model-level assertion at the bottom is the one that matters: the rename
`CPA` -> `Cost/ Conversion` moved the name past the `"cost"` / `"cost/"` / `"/ "`
arms, and on `spinout-05_db/Growth` — where `"/ "` maps to whole euros for
Client-e's thousands-scale per-merchant amounts — the naive outcome was
`#,##0 €`, rendering a real €0.53 cost-per-conversion as "1 €".

Implementation: `selector_format_resolver.resolve_format` -> `tmdl_preflight.format_resolver.resolve`
(returns `(format, unresolved)`), `sfr.UNKNOWN` -> `format_resolver.UNKNOWN`,
`sfr.decimals` -> `format_resolver.decimals` (specs E-format-string-resolver,
E-format-min-decimals). The repository glob of the last test is replaced by the
stand-in tree `tests/fixtures/test_selector_format_resolver_tree` and rule
`format-min-decimals` (proposed id F010).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

TREE = "test_selector_format_resolver_tree"
UNKNOWN = object()  # stands for format_resolver.UNKNOWN in parametrization


class _LazyResolver:
    """`tmdl_preflight.format_resolver`, imported on first use so the file
    collects before the API ships."""

    def __getattr__(self, name):
        from tmdl_preflight import format_resolver
        return getattr(format_resolver, name)


sfr = _LazyResolver()
RULE = "format-min-decimals"
EXCLUDES = ["legacy/**", "DemoData.SemanticModel/**", "*_backup*/**", "*_b2*/**", "*_legacy*/**"]
CONFIG = {
    "exclude": EXCLUDES,
    "rules": {RULE: {"expectations": [{"name": "Cost/ Conversion", "min_decimals": 1}]}},
}


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "z-Selector Format.tmdl"
    f.write_text(
        "table 'z-Selector Format'\n"
        "\tcalculationGroup\n"
        "\t\tcalculationItem Format = selectedmeasure()\n\n"
        "\t\t\tformatStringDefinition =\n"
        + "\n".join("\t\t\t\t" + line for line in body.strip().split("\n"))
        + "\n",
        encoding="utf-8")
    return f


def test_first_match_wins_not_best_match(tmp_path):
    """The whole hazard in one assertion: an EARLIER arm beats a better one."""
    f = _write(tmp_path, '''
        SWITCH(
            TRUE(),
            CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"), "#,##0 EUR",
            CONTAINSSTRING(SELECTEDMEASURENAME(), "cost/ conversion"), "#,##0.00 EUR",
            "General"
        )
    ''')
    assert sfr.resolve(f, "Cost/ Conversion")[0] == "#,##0 EUR"
    assert sfr.resolve(f, "Clicks #")[0] == "General"


def test_nested_switch_and_currency_concatenation(tmp_path):
    f = _write(tmp_path, '''
        VAR _curSfx = " EUR"
        RETURN
        SWITCH(
            TRUE(),
            CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"),
                SWITCH(
                    TRUE(),
                    CONTAINSSTRING(SELECTEDMEASURENAME(), "%"), "P0",
                    CONTAINSSTRING(SELECTEDMEASURENAME(), "per ")
                        || CONTAINSSTRING(SELECTEDMEASURENAME(), "/ "), "#,##0.00 " & _curSfx,
                    "#,##0 " & _curSfx
                ),
            "General"
        )
    ''')
    assert sfr.resolve(f, "Cost/ Conversion")[0].startswith("#,##0.00 ")
    assert sfr.resolve(f, "Cost")[0].startswith("#,##0 ")
    assert sfr.resolve(f, "Cost %")[0] == "P0"


def test_axis_path_is_isolated_from_the_measurename_path(tmp_path):
    """ISINSCOPE picks the branch; only the named axis reports true."""
    f = _write(tmp_path, '''
        SWITCH(
            TRUE(),
            ISINSCOPE('x-Selector 1'[x-Selector 1 Selected Field]),
                SWITCH(TRUE(),
                    CONTAINSSTRING(SELECTEDVALUE('x-Selector 1'[x-Selector 1 Selected Field]), "cpa"), "AXIS",
                    "AXIS-DEFAULT"),
            CONTAINSSTRING(SELECTEDMEASURENAME(), "cpa"), "MEASURENAME",
            "General"
        )
    ''')
    assert sfr.resolve(f, "CPA", axis="x-Selector 1")[0] == "AXIS"
    assert sfr.resolve(f, "CPA", axis=None)[0] == "MEASURENAME"
    assert sfr.resolve(f, "CPA", axis="x-Selector 2")[0] == "MEASURENAME"


def test_a_label_may_differ_from_the_measure_name(tmp_path):
    """x-Selector position 1 is a LABEL; the axis path matches on that, not the name."""
    f = _write(tmp_path, '''
        SWITCH(TRUE(),
            ISINSCOPE('x-Selector 1'[x-Selector 1 Selected Field]),
                SWITCH(TRUE(),
                    CONTAINSSTRING(SELECTEDVALUE('x-Selector 1'[x-Selector 1 Selected Field]), "eom"), "SHORT",
                    "General"),
            "General")
    ''')
    got = sfr.resolve(f, "Total Expected Cost End of Month",
                      axis="x-Selector 1", label="Total Expected Cost EOM")[0]
    assert got == "SHORT"


def test_unreadable_arm_reports_unknown_rather_than_guessing(tmp_path):
    """An arm outside the grammar must not be silently treated as a miss."""
    f = _write(tmp_path, '''
        SWITCH(TRUE(),
            SOMEUNKNOWNFUNC('t'[c]), "X",
            CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"), "#,##0.00",
            "General")
    ''')
    fmt, unresolved = sfr.resolve(f, "Cost")
    assert fmt == sfr.UNKNOWN
    assert unresolved


@pytest.mark.parametrize("fmt,expected", [
    ("#,##0.00 €", 2), ("#,##0.0 €", 1), ("#,##0 €", 0),
    ("P1", 1), ("P0", 0), ("General", None), pytest.param(UNKNOWN, None, id="UNKNOWN-None"),
])
def test_decimals(fmt, expected):
    if fmt is UNKNOWN:
        fmt = sfr.UNKNOWN
    assert sfr.decimals(fmt) == expected


def _gate(model_dir: Path):
    """Anti-regression: the renamed measure must never render whole units, on the
    measure-name path or any axis the selector branches on."""
    code, payload = run_check(model_dir, RULE, config=CONFIG)
    assert code in (0, 1), f"preflight usage error: {payload}"
    found = violations(payload)
    assert not found, "\n".join(v["message"] for v in found)


@pytest.mark.parametrize("client,verdict", [
    ("client_compact", "fail"),
    ("client_expanded", "pass"),
    ("client_unreadable", "pass"),
])
def test_renamed_cost_per_conversion_keeps_its_decimals(stand_in, client, verdict):
    tree = stand_in(TREE)
    model_dir = tree / client / "Growth.SemanticModel"
    if verdict == "pass":
        _gate(model_dir)
    else:
        with pytest.raises(AssertionError):
            _gate(model_dir)


def test_scan_exclusions_skip_legacy_backup_and_demo_folders(stand_in):
    """The earlier check only visited live top-level folders; on the whole tree the
    exclude globs leave the compact selector of client_compact as the only finding
    source (the skipped folders hold the same failing selector)."""
    tree = stand_in(TREE)
    code, payload = run_check(tree, RULE, config=CONFIG)
    found = violations(payload)
    assert found
    assert all("client_compact" in (v.get("file") or "") for v in found)
