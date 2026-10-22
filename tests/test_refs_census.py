"""The reference census: how many places name an object before it is
renamed or deleted.

The count is the blast radius of a rename, so it is read on both layers
(model expressions and report bindings) and split into the live set and
the archived copies.
"""
from __future__ import annotations

import json

from conftest import run_cli


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _model(root):
    _write(root / "Shop.SemanticModel" / "definition" / "tables" / "M.tmdl",
           "measure 'Margin' = [Margin] + [Big Margin]\n")
    _write(root / "Shop.Report" / "definition" / "visual.json",
           '{"a": "Margin", "b": "Sales.Margin", "c": "Margin Trend"}')
    _write(root / "old_backup" / "Old.SemanticModel" / "x.tmdl", "[Margin]\n")


def test_the_census_reports_the_blast_radius(tmp_path):
    _model(tmp_path)
    code, out, err = run_cli("refs", "Margin", tmp_path)
    assert code == 0 and err == ""
    assert out == (
        "\n"
        'References to "Margin"  (matched as `[Margin]`, `"Margin"` or `"Table.Margin"`)\n'
        "\n"
        "  LIVE      model     1   report     2   total     3   files 2\n"
        "  non-live  model     1   report     0   total     1   files 1\n"
        "\n"
        "  Live blast radius: 3 reference(s). ⚠ 2 are report bindings no model-side test checks.\n"
        "\n"
    )


def test_a_dotted_prefix_counts(tmp_path):
    _write(tmp_path / "Shop.Report" / "definition" / "visual.json",
           '{"a": "a.b.Margin", "b": ".Margin"}')
    code, out, _err = run_cli("refs", "Margin", tmp_path)
    assert code == 0
    assert "  LIVE      model     0   report     2   total     2   files 1" in out


def test_a_name_that_is_nowhere_is_said_so(tmp_path):
    _model(tmp_path)
    code, out, _err = run_cli("refs", "Nothing", tmp_path)
    assert code == 0
    assert "  (no references found — check the exact name, including case)" in out


def test_the_loose_shape_says_what_it_counts(tmp_path):
    _model(tmp_path)
    code, out, _err = run_cli("refs", "Margin", tmp_path, "--loose")
    assert code == 0
    assert ('References to "Margin"  (matched as `Margin]` / `Margin"` — LOOSE, also counts '
            "measures whose name ENDS with this one)") in out


def test_the_file_list_hides_the_non_live_files(tmp_path):
    _model(tmp_path)
    code, out, _err = run_cli("refs", "Margin", tmp_path, "--files")
    assert code == 0
    lines = out.splitlines()
    assert lines[7] == ""
    assert lines[8] == "     2  live     report Shop.Report/definition/visual.json"
    assert lines[9] == "     1  live     model  Shop.SemanticModel/definition/tables/M.tmdl"
    assert lines[10] == ""
    assert lines[11] == "  (1 non-live file(s) hidden — --include-nonlive to show)"
    assert out.endswith("\n\n")


def test_the_non_live_files_can_be_shown(tmp_path):
    _model(tmp_path)
    code, out, _err = run_cli("refs", "Margin", tmp_path, "--files", "--include-nonlive")
    assert code == 0
    assert "     1  non-live model  old_backup/Old.SemanticModel/x.tmdl" in out
    assert "non-live file(s) hidden" not in out


def test_a_targets_file_defines_the_live_set(tmp_path):
    _write(tmp_path / "live" / "Shop.SemanticModel" / "definition" / "M.tmdl",
           "measure 'Margin' = [Margin]\n")
    _write(tmp_path / "old_backup" / "Old.SemanticModel" / "x.tmdl", "[Margin]\n")
    targets = tmp_path / "targets.yml"
    targets.write_text("clients:\n  spinout-05:\n    model_path: live/Shop.SemanticModel\n",
                       encoding="utf-8")
    code, out, _err = run_cli("refs", "Margin", tmp_path, "--targets", targets)
    assert code == 0
    assert "  LIVE      model     1   report     0   total     1   files 1" in out
    assert "  non-live  model     1   report     0   total     1   files 1" in out


def test_a_targets_file_names_the_live_set_by_its_secondary_paths(tmp_path):
    _write(tmp_path / "live" / "Shop.SemanticModel" / "definition" / "M.tmdl",
           "measure 'Margin' = [Margin]\n")
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"clients": {"spinout-05": {
        "model_path": "other/Primary.SemanticModel",
        "secondary_models": [{"path": "live/Shop.SemanticModel"}]}}}), encoding="utf-8")
    code, out, _err = run_cli("refs", "Margin", tmp_path, "--targets", targets)
    assert code == 0
    assert "  LIVE      model     1   report     0   total     1   files 1" in out
    assert "  non-live  model     0   report     0   total     0   files 0" in out
