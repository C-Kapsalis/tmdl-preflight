"""The unused-helper report and the inline-row detection.

* PA38: the O010 report, with the files it scanned and the most used
  helpers.
* PA40: an inline-row table is recognised only in the case M spells it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations

TAG = "11111111-1111-4111-8111-{:012d}"
RULE = "unused-helper-measures"


def _measure(name: str, expression: str = "1", tag: int = 0) -> str:
    return (f"\tmeasure '{name}' = {expression}\n\t\tlineageTag: "
            + TAG.format(tag) + "\n")


def _table(name: str, measures: list[str], tag: int, source: str = "x",
           column: bool = False) -> str:
    body = f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
    if column:
        body += ("\tcolumn amount\n\t\tdataType: double\n\t\tlineageTag: "
                 + TAG.format(tag + 50) + "\n\t\tsourceColumn: amount\n")
    for i, m in enumerate(measures):
        body += _measure(m, tag=tag + 100 + i)
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = {source}\n"
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


def test_the_report_names_the_files_it_scanned(tmp_path):
    """PA38: the counts and the scanned files."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Base"], 1),
    })
    code, out, err = run_cli("check", str(model), "--select", RULE, "--no-config")
    assert code == 0, err
    assert "Scanned 2 TMDL + 0 JSON/PBIR files in the active model + adjacent .Report dirs" \
        in out, out
    assert "Total helper measures: 1" in out, out
    assert "Used in active model:  0 (0.0%)" in out, out
    assert "Unused in active model:1" in out, out


def test_a_frequent_helper_is_listed_with_its_counts(tmp_path):
    """PA38: the most used helpers, with the TMDL and JSON counts."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Base"], 1),
    })
    refs = "".join(f"[-helper Base]" + "\n" for _ in range(3))
    path = model / "tables" / "Helper Measures.tmdl"
    path.write_text(path.read_text(encoding="utf-8") + refs, encoding="utf-8")
    report = tmp_path / "Shop.Report" / "definition"
    report.mkdir(parents=True)
    (report / "visual.json").write_text(
        json.dumps({"measure": "-helper Base", "other": "-helper Base"}),
        encoding="utf-8")
    code, out, err = run_cli("check", str(model), "--select", RULE, "--no-config")
    assert code == 0, err
    assert "Most frequently referenced (>=5 refs):" in out, out
    assert "  - Helper Measures[-helper Base]: 5 (3 TMDL + 2 JSON)" in out, out


def test_an_unused_helper_is_listed(tmp_path):
    """PA38: the unused list."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Base"], 1),
    })
    code, out, err = run_cli("check", str(model), "--select", RULE, "--no-config")
    assert code == 0, err
    assert ("Unused in active model (1) — candidates for deletion FROM THIS MODEL "
            "(rerun with other models to confirm they're unused there too before "
            "deleting from the template):") in out, out
    assert "  - Helper Measures[-helper Base]" in out, out


def test_a_used_helper_says_so(tmp_path):
    """PA38: the all-clear line."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Base"], 1),
    })
    path = model / "tables" / "Helper Measures.tmdl"
    path.write_text(path.read_text(encoding="utf-8") + "[-helper Base]\n",
                    encoding="utf-8")
    code, out, err = run_cli("check", str(model), "--select", RULE, "--no-config")
    assert code == 0, err
    assert "Every helper in the active model is referenced somewhere." in out, out


def test_a_report_file_with_an_upper_case_extension_counts(tmp_path):
    """PA38: the report files are matched by extension, case or not."""
    model = _model(tmp_path, {
        "Helper Measures": _table("Helper Measures", ["-helper Base"], 1),
    })
    report = tmp_path / "Shop.Report" / "definition"
    report.mkdir(parents=True)
    (report / "visual.JSON").write_text(
        json.dumps({"measure": "-helper Base"}), encoding="utf-8")
    code, out, err = run_cli("check", str(model), "--select", RULE, "--no-config")
    assert code == 0, err
    assert "1 JSON/PBIR files" in out, out
    assert "Unused in active model:0" in out, out


def test_an_inline_row_table_is_a_fact_only_in_the_case_m_spells_it(tmp_path):
    """PA40: `table.fromrows(` is not a row constructor."""
    lower = _table("Sales", ["Revenue"], 1,
                   source="let Source = table.fromrows({{1}}) in Source",
                   column=True)
    upper = _table("Orders", ["Total"], 2,
                   source="let Source = Table.FromRows({{1}}) in Source",
                   column=True)
    model = _model(tmp_path, {"Sales": lower, "Orders": upper})
    code, payload = run_check(model, "dead-fact-tables")
    found = violations(payload, "O007")
    # the fact table with the lower-case spelling is still a fact: it is
    # read by no measure, so it is dead
    assert [v["object"] for v in found] == ["Sales"], found
