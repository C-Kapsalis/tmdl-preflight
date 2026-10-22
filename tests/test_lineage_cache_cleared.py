"""PA4: a single-model lineage fix clears Desktop's cache.

Desktop keeps a model cache (`.pbi/cache.abf`) that remembers the lineage
tags. After a fix changed a tag, that cache is what makes Desktop reuse
the old ones, so a single-model run deletes it by default. A
whole-repository run never deletes a cache; it says that it exists.
`--keep-cache` opts out, `--clear-cache` forces the deletion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_cli, run_fix


def _model(root: Path, name: str = "Cafe") -> Path:
    definition = root / f"{name}.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    tag = "11111111-1111-4111-8111-111111111111"
    (definition / "tables" / "Beans.tmdl").write_text(
        "table Beans\n"
        f"\tlineageTag: {tag}\n\n"
        "\tcolumn kg\n"
        f"\t\tlineageTag: {tag}\n"
        "\t\tdataType: double\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
        "\t\tsourceColumn: kg\n",
        encoding="utf-8")
    return root / f"{name}.SemanticModel"


def _cache(model: Path) -> Path:
    cache = model / ".pbi" / "cache.abf"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"cache")
    return cache


def test_a_single_model_run_deletes_the_cache(tmp_path):
    """PA4: the cache goes, and the tool says so."""
    model = _model(tmp_path)
    cache = _cache(model)
    code, out, err = run_cli("fix", model, "--select", "M003", "--no-config")
    assert not cache.exists(), "the cache was kept"
    assert "Deleted cache file" in out, out


def test_keep_cache_opts_out(tmp_path):
    """PA4: `--keep-cache` keeps it."""
    model = _model(tmp_path)
    cache = _cache(model)
    code, out, err = run_cli("fix", model, "--select", "M003",
                             "--keep-cache", "--no-config")
    assert cache.exists(), "the cache was deleted"


def test_a_multi_model_run_keeps_the_cache(tmp_path):
    """PA4: a whole-repository run never deletes a cache."""
    model = _model(tmp_path, "Cafe")
    second = _model(tmp_path, "Shop")
    cache = _cache(model)
    cache2 = _cache(second)
    code, out, err = run_cli("fix", tmp_path, "--select", "M003", "--no-config")
    assert cache.exists() and cache2.exists(), "a cache was deleted"
    assert "--clear-cache" in err, err


def test_a_dry_run_deletes_nothing(tmp_path):
    """PA4: a dry run never deletes."""
    model = _model(tmp_path)
    cache = _cache(model)
    code, out, err = run_cli("fix", model, "--select", "M003", "--dry-run",
                             "--no-config")
    assert cache.exists(), "a dry run deleted the cache"
