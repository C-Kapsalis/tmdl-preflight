"""The fixes of the post-1.2.1 audit, one section per finding.

Each test reproduces the defect on a small fictional model first; the fix
followed the failing test.
"""

from __future__ import annotations

from pathlib import Path

from conftest import run_cli, write_config

RULE = "=" * 80

#: Words a check run must never print: it changes no file.
REPAIR_WORDS = ("Mode: LIVE", "Fixing occurrence", "New tag:", "Fixed ",
                "fixed ", "Would fix", "would fix", "DRY RUN", "Removed ",
                "Files fixed", "fixes applied")


def _model(root: Path, body: str, name: str = "Cafe") -> Path:
    definition = root / f"{name}.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\nref table Beans\n", encoding="utf-8",
        newline="\n")
    (definition / "tables" / "Beans.tmdl").write_text(body, encoding="utf-8",
                                                      newline="\n")
    return root / f"{name}.SemanticModel"


def _no_repair_language(out: str) -> None:
    for word in REPAIR_WORDS:
        assert word not in out, f"check printed {word!r}:\n{out}"


# ---------------------------------------------------------------------------
# 1. check never prints repair language
# ---------------------------------------------------------------------------

DUPLICATE = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tcolumn kg\n"
    "\t\tlineageTag: 11111111-1111-4111-8111-111111111111\n"
    "\t\tdataType: double\n"
)

MISORDERED = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tmeasure Kg = SUM(Beans[kg])\n"
    "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n\n"
    "\t\tannotation note = a\n"
    "\n"
    "\t\tisHidden\n"
)


def test_check_select_m003_reports_without_repairing(tmp_path):
    model = _model(tmp_path, DUPLICATE)
    before = (model / "definition" / "tables" / "Beans.tmdl").read_bytes()
    code, out, err = run_cli("check", model, "--select", "M003", "--no-config")
    assert code == 1, out
    _no_repair_language(out)
    assert "Mode: CHECK" in out, out
    assert "❌ Found 1 duplicate lineage tag(s)" in out, out
    assert "      Line 5: column:column kg" in out, out
    assert (model / "definition" / "tables" / "Beans.tmdl").read_bytes() == before


def test_check_with_m003_among_several_rules(tmp_path):
    model = _model(tmp_path, DUPLICATE)
    code, out, err = run_cli("check", model, "--select", "M003,D004,M011",
                             "--no-config")
    assert code == 1, out
    _no_repair_language(out)


def test_check_multi_model_m003_summary_counts_no_fixes(tmp_path):
    _model(tmp_path / "one", DUPLICATE, "One")
    _model(tmp_path / "two", DUPLICATE, "Two")
    code, out, err = run_cli("check", tmp_path, "--select", "M003", "--no-config")
    _no_repair_language(out)
    assert "Total models checked: 2" in out, out
    assert "Total duplicate occurrences: 2" in out, out


def test_check_select_m011_reports_found_not_fixed(tmp_path):
    model = _model(tmp_path, MISORDERED)
    code, out, err = run_cli("check", model, "--select", "M011", "--no-config")
    _no_repair_language(out)
    assert "found " in out and "Beans.tmdl (1):" in out, out
    assert "Found 1 issue(s) across 1 file(s)." in out, out


def test_check_select_m011_on_a_clean_model(tmp_path):
    model = _model(tmp_path, DUPLICATE.replace("11111111-1111-4111-8111-111111111111\n\t\t",
                                               "33333333-3333-4333-8333-333333333333\n\t\t"))
    code, out, err = run_cli("check", model, "--select", "M011", "--no-config")
    _no_repair_language(out)
    assert "Found 0 issue(s) across 0 file(s)." in out, out


def test_check_m013_attach_mode_reports_without_repairing(tmp_path):
    body = "table Beans\n\t/// Kilograms sold\n\n\n\tmeasure Kg = SUM(Beans[kg])\n"
    model = _model(tmp_path, body)
    d = model / "definition"
    cfg = write_config(d, {"rules": {"M013": {"fix_mode": "attach"}}})
    code, out, err = run_cli("check", d, "--select", "M013", "--config", str(cfg))
    _no_repair_language(out)
    assert "CLEANUP TMDL COMMENT SPACING" in out, out
    assert "No issues found" not in out, out
    assert "  - Beans.tmdl: 1 occurrence(s)" in out, out



# ---------------------------------------------------------------------------
# 2-3. R007: a refused deletion is reported; a blanket dry run skips it
# ---------------------------------------------------------------------------

BEANS = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tcolumn kg\n"
    "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
    "\t\tdataType: double\n\n"
    "\tcolumn id\n"
    "\t\tlineageTag: 33333333-3333-4333-8333-333333333333\n"
    "\t\tdataType: int64\n"
)

AUTODETECTED = (
    "relationship AutoDetected_5c1d2e3f-4a5b-4c6d-8e7f-901234567890\n"
    "\tfromColumn: Beans.kg\n"
    "\ttoColumn: Beans.id\n"
)


def _autodetected(tmp_path: Path, relationships: bytes = AUTODETECTED.encode()) -> Path:
    model = _model(tmp_path, BEANS)
    (model / "definition" / "relationships.tmdl").write_bytes(relationships)
    return model


def test_r007_refused_deletion_is_reported_and_exits_2(tmp_path):
    mixed = AUTODETECTED.replace("Beans.kg\n", "Beans.kg\r\n").encode()
    model = _autodetected(tmp_path, mixed)
    rel = model / "definition" / "relationships.tmdl"
    code, out, err = run_cli("fix", model, "--select", "R007", "--no-config")
    assert rel.read_bytes() == mixed
    assert code == 2, (code, out, err)
    assert "refused  R007: " in out, out
    assert "relationships.tmdl" in err and "ERROR" in err, err
    assert "Deleted 1 autodetected" not in out, out


def test_r007_dry_run_says_the_mixed_file_would_be_refused(tmp_path):
    mixed = AUTODETECTED.replace("Beans.kg\n", "Beans.kg\r\n").encode()
    model = _autodetected(tmp_path, mixed)
    code, out, err = run_cli("fix", model, "--select", "R007", "--dry-run",
                             "--no-config")
    assert "Would delete" not in out, out
    assert "mixes its line endings" in out, out


def test_r007_explicit_fix_still_deletes(tmp_path):
    model = _autodetected(tmp_path)
    code, out, err = run_cli("fix", model, "--select", "R007", "--no-config")
    assert code == 0, out
    assert (model / "definition" / "relationships.tmdl").read_text(encoding="utf-8") == ""


def test_blanket_dry_run_matches_the_blanket_fix_for_r007(tmp_path):
    model = _autodetected(tmp_path)
    rel = model / "definition" / "relationships.tmdl"
    code, dry, err = run_cli("fix", model, "--dry-run", "--no-config")
    assert "Would delete" not in dry, dry
    assert "not fixed  R007:" in dry, dry
    code, real, err = run_cli("fix", model, "--no-config")
    assert "not fixed  R007:" in real, real
    assert rel.read_text(encoding="utf-8") == AUTODETECTED
