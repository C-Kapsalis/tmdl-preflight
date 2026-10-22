"""The helper-placement rule: the free hosts, the grouped strict report and
the lenient summary.

* PA24: the axis field-parameter tables are free hosts by default.
* PA25: the strict text output groups the findings by subcategory.
* PA26: the lenient profile prints a summary block per model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations, write_config

TAG = "11111111-1111-4111-8111-{:012d}"


def _table(name: str, measures: list[str], tag: int) -> str:
    body = f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    for i, m in enumerate(measures):
        body += (f"\tmeasure '{m}' = 1\n\t\tlineageTag: "
                 + TAG.format(tag + 100 + i) + "\n")
    body += f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource = 1\n"
    return body


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def _text(model: Path, *args: str) -> str:
    code, out, err = run_cli("check", str(model), "--select",
                             "helper-measure-placement", "--no-config", *args)
    assert code in (0, 1), err
    return out


def _lenient_text(model: Path) -> str:
    cfg = write_config(model.parent.parent, {
        "rules": {"helper-measure-placement": {"profile": "lenient"}}})
    code, out, err = run_cli("check", str(model), "--select",
                             "helper-measure-placement", "--config", str(cfg))
    assert code in (0, 1), err
    return out


def test_the_axis_tables_are_free_hosts(tmp_path):
    """PA24: a helper in an axis table is never a finding."""
    model = _model(tmp_path, {
        "x-Selector 1": _table("x-Selector 1", ["-helper X"], 1),
        "x-Plot Specific 1": _table("x-Plot Specific 1", ["-helper X"], 2),
        "#KPIs": _table("#KPIs", ["-helper X"], 3),
    })
    found = violations(run_check(model, "helper-measure-placement", strict=True)[1])
    objs = {v["object"] for v in found}
    assert objs == {"#KPIs[-helper X]"}, objs


def test_the_strict_output_groups_by_subcategory(tmp_path):
    """PA25: one block per subcategory, in sorted order."""
    model = _model(tmp_path, {
        "Ads Measures": _table("Ads Measures", ["-helper Basket"], 1),
        "Coffee Measures": _table("Coffee Measures", ["f-Espresso"], 2),
    })
    out = _text(model, "--strict")
    assert "Found 2 helper measure(s) in wrong table(s), grouped by subcategory:" \
        in out, out
    assert "  [measure_helper] - 1 violation(s)" in out, out
    assert "  [slicer_helper] - 1 violation(s)" in out, out
    assert out.index("[measure_helper]") < out.index("[slicer_helper]"), out
    assert "    Rule: " in out, out
    assert "      - Ads Measures[-helper Basket]" in out, out
    assert "      - Coffee Measures[f-Espresso]" in out, out


def test_the_strict_output_carries_the_guidance(tmp_path):
    """PA25: the guidance of each subcategory."""
    model = _model(tmp_path, {
        "Ads Measures": _table("Ads Measures", ["-helper Basket"], 1),
    })
    out = _text(model, "--strict")
    assert ("'-helper *' / '_*' measures must live in 'Helper Measures' with a "
            "displayFolder named after the analysis category they support") in out, out


def test_the_lenient_profile_prints_a_summary(tmp_path):
    """PA26: the four buckets and their expected texts."""
    model = _model(tmp_path, {
        "Ads Measures": _table("Ads Measures", [
            "-helper Basket", "f-Espresso", "-Visual Label", "i-Rows"], 1),
    })
    out = _lenient_text(model)
    assert "Measure Organization (Shop.SemanticModel):" in out, out
    assert "f- measures outside f-Filters / w-*:           1" in out, out
    assert "-helper * outside 'Helper Measures':           1" in out, out
    assert "-Visual * / w-* outside Helper Measures / w-*: 1" in out, out
    assert "i- measures outside Helper / Diagnostic:       1" in out, out
    assert "f- measures in wrong table (1):" in out, out
    assert "  - Ads Measures[f-Espresso]  (expected: 'f-Filters' or any 'w-*' table)" \
        in out, out
    assert ("-helper * measures in wrong table (1):" in out), out
    assert ("  - Ads Measures[-helper Basket]  (expected: 'Helper Measures' "
            "(with displayFolder named by analysis category))") in out, out
    assert ("-Visual * / w-* measures in wrong table (1):" in out), out
    assert ("  - Ads Measures[-Visual Label]  (expected: 'Helper Measures' or any "
            "'w-*' table)") in out, out
    assert ("i- measures in wrong table (1):" in out), out
    assert ("  - Ads Measures[i-Rows]  (expected: 'Helper Measures' or "
            "'Diagnostic Measures')") in out, out


def test_the_lenient_profile_says_so_when_everything_is_in_place(tmp_path):
    """PA26: the all-clear line."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Basket"], 1),
        "f-Filters": _table("f-Filters", ["f-Espresso"], 2),
    })
    out = _lenient_text(model)
    assert "All helper-family measures live in expected tables." in out, out


def test_the_lenient_finding_carries_the_expected_text(tmp_path):
    """PA26: every lenient finding names the table it belongs in."""
    model = _model(tmp_path, {
        "Ads Measures": _table("Ads Measures", ["f-Espresso"], 1),
    })
    cfg = {"rules": {"helper-measure-placement": {"profile": "lenient"}}}
    found = violations(run_check(model, "helper-measure-placement", config=cfg)[1])
    assert len(found) == 1
    assert found[0]["severity"] == "info"
    assert "expected: 'f-Filters' or any 'w-*' table" in found[0]["message"]
