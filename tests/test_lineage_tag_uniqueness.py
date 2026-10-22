"""Lineage tags are unique and well-formed (spec H-duplicate-lineage-tags).

A repeated lineageTag makes Power BI reject the import ("An object with
lineage-tag already exists in the collection"). The earlier check scanned the
template's tables folder with a regex; the port runs M003 (uniqueness) and
M004 (canonical UUID format) through `tmdl-preflight check`.

Stand-ins (tests/fixtures/b3-a2/lineage_tag_uniqueness/<variant>, the template
``universal/Performance`` with Helper Measures, Beans and Roasts):
``clean`` all unique and canonical; ``dup_across`` a column tag copied into
another table file; ``dup_helper`` a tag repeated inside Helper Measures;
``placeholder`` a placeholder debug tag that is not a UUID.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

STAND_INS = "b3-a2/lineage_tag_uniqueness"
TABLES = Path("universal/Performance.SemanticModel/definition/tables")


def _tags(stand_in, variant):
    root = stand_in(f"{STAND_INS}/{variant}")
    assert (root / TABLES).exists(), f"TMDL directory not found: {root / TABLES}"
    assert list((root / TABLES).glob("*.tmdl")), "No TMDL files found"
    _code, payload = run_check(root, "M003", "M004")
    assert "summary" in payload, payload
    return root, payload


@pytest.mark.parametrize("variant,verdict", [
    ("clean", "pass"), ("dup_across", "fail"), ("dup_helper", "fail"), ("placeholder", "pass"),
])
def test_no_duplicate_lineage_tags_across_all_files(stand_in, variant, verdict):
    _root, payload = _tags(stand_in, variant)
    dups = violations(payload, "M003")
    if verdict == "pass":
        assert dups == []
    else:
        assert len(dups) == 1


@pytest.mark.parametrize("variant,verdict", [
    ("clean", "pass"), ("dup_across", "pass"), ("dup_helper", "pass"), ("placeholder", "fail"),
])
def test_lineage_tag_format_validity(stand_in, variant, verdict):
    """The earlier check was a non-strict xfail (known placeholder debug measure);
    the port expects a plain M004 finding, no xfail. DESKTOP: M004 stays a
    WARNING because Power BI Desktop opened a model whose only defect was a
    placeholder tag (project decision), so the finding is asserted as a warning."""
    _root, payload = _tags(stand_in, variant)
    bad = violations(payload, "M004")
    if verdict == "pass":
        assert bad == []
    else:
        assert len(bad) == 1
        assert bad[0]["severity"] == "warning"
        assert "b1c2d3e4-f5g6-7890-hijk-lmnopqrstuvw" in bad[0]["message"]


@pytest.mark.parametrize("variant,verdict", [
    ("clean", "pass"), ("dup_across", "pass"), ("dup_helper", "fail"), ("placeholder", "pass"),
])
def test_helper_measures_file_specific_uniqueness(stand_in, variant, verdict):
    root, payload = _tags(stand_in, variant)
    assert (root / TABLES / "Helper Measures.tmdl").exists(), "Helper Measures.tmdl file not found"
    in_helper = [v for v in violations(payload, "M003")
                 if (v.get("path") or "").endswith("Helper Measures.tmdl")]
    if verdict == "pass":
        assert in_helper == []
    else:
        assert len(in_helper) == 1
