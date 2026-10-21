"""PA27: the measure organisation summary is per model.

`stats --measures` prints one summary per model, never a sum across models:
a folder with two models prints two banners, each with its own totals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli

RULE = "=" * 70


def _model(root: Path, name: str, measures: list[str]) -> Path:
    definition = root / f"{name}.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        f"model Model\n\nref table 'Helper Measures'\n", encoding="utf-8")
    body = "table 'Helper Measures'\n\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    for i, m in enumerate(measures):
        body += (f"\tmeasure '{m}' = 1\n\t\tlineageTag: "
                 f"22222222-2222-4222-8222-22222222222{i:02d}\n")
    (definition / "tables" / "Helper Measures.tmdl").write_text(
        body, encoding="utf-8")
    return root / f"{name}.SemanticModel"


def test_two_models_print_two_banners(tmp_path):
    """PA27: one summary per model."""
    _model(tmp_path, "Cafe", ["Revenue", "Bags Sold"])
    _model(tmp_path, "Shop", ["Orders", "Revenue", "Returns"])
    code, out, err = run_cli("stats", tmp_path, "--measures")
    assert code == 0, err
    assert out.count("MEASURE ORGANIZATION SUMMARY") == 2, out
    assert out.count(RULE) >= 6, out
    # each model's own totals
    assert "Total measures: 2" in out, out
    assert "Total measures: 3" in out, out


def test_the_layout(tmp_path):
    """PA27: the exact lines."""
    _model(tmp_path, "Cafe", ["Revenue", "Bags Sold", "-helper Base"])
    code, out, err = run_cli("stats", tmp_path, "--measures")
    assert code == 0, err
    assert "Total measures: 3" in out, out
    assert "  User-facing names: 2 (66.7%)" in out, out
    assert "  Helper names:      1 (33.3%)" in out, out
    assert "Helper subcategories:" in out, out
    assert "Top 10 tables by measure count:" in out, out
    assert "Helper Measure Analysis:" in out, out
    assert "   Total helper measures (- prefix): 1" in out, out


def test_json_gives_the_numbers_per_model(tmp_path):
    """PA27: the JSON has the same numbers per model key."""
    _model(tmp_path, "Cafe", ["Revenue"])
    code, out, err = run_cli("stats", tmp_path, "--measures", "--json")
    assert code == 0, err
    payload = json.loads(out)["measures"]
    assert len(payload["per_model"]) == 1
    assert payload["per_model"][0]["model"] == "Cafe.SemanticModel"
    assert payload["per_model"][0]["total"] == 1


def test_a_model_with_no_measures(tmp_path):
    """PA27: the empty line."""
    definition = tmp_path / "Empty.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    code, out, err = run_cli("stats", tmp_path, "--measures")
    assert code == 0, err
    assert "No measures in model." in out, out
