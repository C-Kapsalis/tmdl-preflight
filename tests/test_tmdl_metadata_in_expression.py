"""No TMDL metadata leaked INTO a DAX expression; no simple property after the
annotation / child-block section.

Ported from the layer-1 suite. A property line (isHidden, displayFolder,
lineageTag, detailRows, kpi, ...) inside an expression region makes Power BI
reject the model ("UnknownKeyword ... neither a property nor an object in the
current context"); a simple property after an annotation / changedProperty /
formatStringDefinition / kpi / detailRows / relatedColumnDetails block fails the
same way.

The original parametrised over every tables/*.tmdl of the fleet; here over the
stand-in files in ``tests/fixtures/tmdl_metadata_in_expression`` (the same files
were placed under ``sample_db/Sample.SemanticModel`` for the original run).
Kernel recognizers -> ``check --select M010`` / ``--select M011``, filtered by file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations

pytestmark = [pytest.mark.p0]

FIX = "tmdl_metadata_in_expression"
FILES_DIR = Path(__file__).parent / "fixtures" / FIX / "Sample.SemanticModel" / "definition" / "tables"
FILES = sorted(p.name for p in FILES_DIR.glob("*.tmdl"))

M010_FAIL = {
    "M010 a isHidden after equals.tmdl", "M010 b buried flag.tmdl",
    "M010 c lineage in fence.tmdl", "M010 d buried detailRows.tmdl",
    "M010 e buried kpi and relatedColumnDetails.tmdl",
    "M010 f buried displayFolder no colon.tmdl",
}
M011_FAIL = {
    "M010 d buried detailRows.tmdl", "M010 e buried kpi and relatedColumnDetails.tmdl",
    "M011 a flag after annotation.tmdl", "M011 b property after changedProperty.tmdl",
    "M011 d wider block set.tmdl",
}


def _for_file(payload, rule, name):
    return [v for v in violations(payload, rule) if (v.get("path") or "").endswith("/" + name)]


@pytest.mark.parametrize("name", FILES)
def test_no_tmdl_metadata_inside_dax_expression(stand_in, name):
    model = stand_in(FIX) / "Sample.SemanticModel"
    code, payload = run_check(model, "M010")
    bad = _for_file(payload, "M010", name)
    if name in M010_FAIL:
        assert bad, f"{name}: TMDL metadata leaked into a DAX expression"
        assert all(v["severity"] == "error" for v in bad)
        if name.startswith("M010 e"):
            assert len(bad) == 2  # one finding each for kpi and relatedColumnDetails
    else:
        # includes 'M010 h': a property word inside a DAX comment is not a leak
        assert bad == [], "\n  ".join(v["message"] for v in bad)


@pytest.mark.parametrize("name", FILES)
def test_no_simple_property_after_block_section(stand_in, name):
    model = stand_in(FIX) / "Sample.SemanticModel"
    code, payload = run_check(model, "M011")
    bad = _for_file(payload, "M011", name)
    if name in M011_FAIL:
        assert bad, f"{name}: simple property placed after the block section"
        assert all(v["severity"] == "error" for v in bad)  # STRICTER: M011 -> error
        if name.startswith("M011 d"):
            assert len(bad) == 4
    else:
        assert bad == [], "\n  ".join(v["message"] for v in bad)


# --- M011 fixer (spec B-property-after-child-block cases 2, 5, 6, 8) ---


def _one_table_model(tmp_path, body, newline="\n"):
    tables = tmp_path / "Brew.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    text = ("table Brews\n\tlineageTag: 0b0b0b0b-0000-4000-8000-000000000001\n\n" + body
            + "\tpartition Brews = m\n\t\tmode: import\n\t\tsource = #table({\"Column1\"}, {{1}})\n")
    f = tables / "Brews.tmdl"
    f.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return tmp_path / "Brew.SemanticModel", f


FLAG_AFTER = ("\tmeasure 'Cups Sold' = SUM(Brews[cups])\n"
              "\t\tlineageTag: 0b0b0b0b-0000-4000-8000-000000000002\n\n"
              "\t\tannotation Owner = bar\n\n\t\tisHidden\n\n")


def test_fix_moves_flag_to_first_property_slot(tmp_path):
    model, f = _one_table_model(tmp_path, FLAG_AFTER)
    run_fix(model, "M011")
    text = f.read_text(encoding="utf-8")
    assert "\tmeasure 'Cups Sold' = SUM(Brews[cups])\n\t\tisHidden\n\t\tlineageTag:" in text
    assert text.index("isHidden") < text.index("annotation Owner")
    assert violations(run_check(model, "M011")[1]) == []


def test_fix_moves_valued_property(tmp_path):
    body = FLAG_AFTER.replace("\t\tisHidden\n", "\t\tdisplayFolder: Beans\n")
    model, f = _one_table_model(tmp_path, body)
    code, payload = run_fix(model, "M011")
    text = f.read_text(encoding="utf-8")
    assert text.index("displayFolder: Beans") < text.index("annotation Owner")
    assert violations(payload) == []


def test_fix_keeps_crlf(tmp_path):
    model, f = _one_table_model(tmp_path, FLAG_AFTER, newline="\r\n")
    run_fix(model, "M011")
    raw = f.read_bytes()
    assert b"\t\tisHidden\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_second_fix_run_moves_nothing(tmp_path):
    model, f = _one_table_model(tmp_path, FLAG_AFTER)
    run_fix(model, "M011")
    once = f.read_bytes()
    code, payload = run_fix(model, "M011")
    assert f.read_bytes() == once
    assert payload["fixes"] == []
