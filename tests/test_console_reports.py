"""PA3, PA5, PA7, PA12: the console reports the reference scripts printed.

The rules that came from scripts with a report of their own print that
report when they are the one rule the run selected: the dangling-description
sweep (M013), the lineage repair (M003), the misordered-property repair
(M011) and the TMDL file validation (M017).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import run_cli

RULE = "=" * 80


def _model(root: Path, name: str = "Cafe", body: str | None = None) -> Path:
    definition = root / f"{name}.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\nref table Beans\n", encoding="utf-8", newline="\n")
    (definition / "tables" / "Beans.tmdl").write_text(
        body if body is not None else
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tcolumn kg\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
        "\t\tdataType: double\n",
        encoding="utf-8", newline="\n")
    return root / f"{name}.SemanticModel"


# ---------------------------------------------------------------------------
# PA3: the dangling-description report
# ---------------------------------------------------------------------------


def _dangling(root: Path, text: str) -> Path:
    definition = root / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    (definition / "tables" / "Beans.tmdl").write_text(text, encoding="utf-8")
    return definition


def test_the_check_reports_the_dangling_runs(tmp_path):
    """PA3: the DANGLING blocks and the count line."""
    d = _dangling(tmp_path, "table Beans\n\n\t/// An orphan note.\n\n")
    code, out, err = run_cli("check", d, "--select", "M013", "--no-config")
    assert code == 1, out
    assert "DANGLING /// (1): " in out, out
    assert "    line 3: /// An orphan note." in out, out
    assert "1 file(s) with dangling `///` descriptions." in out, out


def test_the_fix_reports_what_it_removed(tmp_path):
    """PA3: the removal line and the fix footer."""
    d = _dangling(tmp_path, "table Beans\n\n\t/// An orphan note.\n\n")
    code, out, err = run_cli("fix", d, "--select", "M013", "--no-config")
    assert "DANGLING /// (1): " in out, out
    assert "    -> removed 1 dangling run(s)" in out, out
    assert "Fixed 1 file(s); 1 had dangling descriptions." in out, out


def test_two_files_are_reported_in_path_order(tmp_path):
    """PA3: two DANGLING blocks and the count."""
    d = _dangling(tmp_path, "table Beans\n\n\t/// One.\n\n")
    (d / "tables" / "Apples.tmdl").write_text(
        "table Apples\n\n\t/// Two.\n\n", encoding="utf-8")
    code, out, err = run_cli("check", d, "--select", "M013", "--no-config")
    assert out.index("Apples.tmdl") < out.index("Beans.tmdl"), out
    assert out.count("DANGLING ///") == 2, out
    assert "2 file(s) with dangling `///` descriptions." in out, out
    code, out, err = run_cli("fix", d, "--select", "M013", "--no-config")
    assert "Fixed 2 file(s); 2 had dangling descriptions." in out, out


# ---------------------------------------------------------------------------
# PA5: the lineage repair report
# ---------------------------------------------------------------------------


DUPLICATE = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tcolumn kg\n"
    "\t\tlineageTag: 11111111-1111-4111-8111-111111111111\n"
    "\t\tdataType: double\n"
)


def test_the_live_lineage_report(tmp_path):
    """PA5: the report of one model with one duplicate tag."""
    model = _model(tmp_path, body=DUPLICATE)
    code, out, err = run_cli("fix", model, "--select", "M003", "--no-config")
    assert RULE in out, out
    assert "FIX DUPLICATE LINEAGE TAGS" in out, out
    assert f"Model: {model / 'definition'}" in out, out
    assert "Mode: LIVE" in out, out
    assert "❌ Found 1 duplicate lineage tag(s)" in out, out
    assert "Duplicate tag: 11111111-1111-4111-8111-111111111111" in out, out
    assert "  Found in 2 locations:" in out, out
    assert "    Beans.tmdl:" in out, out
    assert "      Line 2: table:table Beans" in out, out
    assert "      Line 5: column:column kg" in out, out
    assert "  → Fixing occurrence 2: Beans.tmdl" in out, out
    assert "    Old tag: 11111111-1111-4111-8111-111111111111" in out, out
    assert re.search(r"    New tag: [0-9a-f-]{36}", out), out
    assert "✅ Fixed 1 duplicate lineage tag occurrence(s)" in out, out
    assert "   Affected 1 unique lineage tags" in out, out


def test_the_dry_run_lineage_report(tmp_path):
    """PA5: the dry run says what it would do and writes nothing."""
    model = _model(tmp_path, body=DUPLICATE)
    before = (model / "definition" / "tables" / "Beans.tmdl").read_bytes()
    code, out, err = run_cli("fix", model, "--select", "M003", "--dry-run",
                             "--no-config")
    assert "Mode: DRY RUN" in out, out
    assert "DRY RUN: Would fix 1 duplicate lineage tag(s)" in out, out
    assert (model / "definition" / "tables" / "Beans.tmdl").read_bytes() == before


def test_a_model_without_duplicates(tmp_path):
    """PA5: the clean verdict."""
    model = _model(tmp_path)
    code, out, err = run_cli("fix", model, "--select", "M003", "--no-config")
    assert "✅ No duplicate lineage tags found!" in out, out


def test_a_multi_model_run_prints_the_summary(tmp_path):
    """PA5: the repository scan and its summary."""
    _model(tmp_path / "one", "One", DUPLICATE)
    _model(tmp_path / "two", "Two", DUPLICATE)
    code, out, err = run_cli("fix", tmp_path, "--select", "M003", "--no-config")
    assert "SCANNING ALL MODELS FOR DUPLICATE LINEAGE TAGS" in out, out
    assert "Found 2 model(s)" in out, out
    assert "Checking: One" in out, out
    assert "Checking: Two" in out, out
    assert "SUMMARY" in out, out
    assert "Total models checked: 2" in out, out
    assert "Total fixes applied: 2" in out, out


# ---------------------------------------------------------------------------
# PA7: the misordered-property report
# ---------------------------------------------------------------------------


MISORDERED = (
    "table Beans\n"
    "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
    "\tmeasure Kg = SUM(Beans[kg])\n"
    "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n\n"
    "\t\tannotation note = a\n"
    "\n"
    "\t\tisHidden\n"
)


def test_the_misordered_property_report(tmp_path):
    """PA7: the per-file block and the footer."""
    model = _model(tmp_path, body=MISORDERED)
    code, out, err = run_cli("fix", model, "--select", "M011", "--no-config")
    assert "fixed " in out and "Beans.tmdl (1):" in out, out
    assert "    [isHidden] in Kg" in out, out
    assert "Fixed 1 issue(s) across 1 file(s)." in out, out


def test_the_misordered_property_dry_run(tmp_path):
    """PA7: the dry run says 'would fix'."""
    model = _model(tmp_path, body=MISORDERED)
    code, out, err = run_cli("fix", model, "--select", "M011", "--dry-run",
                             "--no-config")
    assert "would fix " in out and "Beans.tmdl (1):" in out, out
    assert "    [isHidden] in Kg" in out, out
    assert "Would fix 1 issue(s) across 1 file(s)." in out, out


def test_a_refused_repair_is_reported_on_stderr(tmp_path):
    """PA7: a repair the tool cannot prove says so and exits 2."""
    model = _model(tmp_path, body=MISORDERED)
    f = model / "definition" / "tables" / "Beans.tmdl"
    # a file that mixes its line endings cannot be rewritten safely
    f.write_bytes(f.read_bytes().replace(b"\n\n\t\tannotation", b"\r\n\t\tannotation"))
    code, out, err = run_cli("fix", model, "--select", "M011", "--no-config")
    assert code == 2, out
    assert "ERROR" in err and "Beans.tmdl" in err, err


# ---------------------------------------------------------------------------
# PA12: the file validation report
# ---------------------------------------------------------------------------


def test_the_validation_report(tmp_path):
    """PA12: the report of a file with seven space-indented lines."""
    body = "table Beans\n" + "".join(
        f"    column c{i}\n" for i in range(7))
    model = _model(tmp_path, body=body)
    code, out, err = run_cli("check", model, "--select", "M017", "--no-config")
    assert f"{RULE}\nVALIDATING TMDL FILES: Cafe.SemanticModel\n{RULE}" in out, out
    assert "Found 1 TMDL files to validate" in out, out
    assert "❌ Beans.tmdl:" in out, out
    assert out.count("   - Line ") == 5, out
    assert "   ... and 2 more errors" in out, out
    assert f"{RULE}\nVALIDATION SUMMARY\n{RULE}" in out, out
    assert "❌ Found 7 errors in 1 files:" in out, out
    assert "   - Beans.tmdl" in out, out
    assert "These errors will cause Power BI Desktop to fail opening the file." in out, out
    assert "Please fix the errors before opening in Power BI." in out, out


def test_the_validation_report_of_a_clean_model(tmp_path):
    """PA12: the clean verdict."""
    model = _model(tmp_path)
    code, out, err = run_cli("check", model, "--select", "M017", "--no-config")
    assert "✅ All 1 files passed validation" in out, out


def test_the_validation_report_counts_the_notes(tmp_path):
    """PA12: the notes are counted but never fail."""
    body = (
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tmeasure 'Kg' =\n"
        "\t\t\tSUM(Beans[kg])\n"
    )
    model = _model(tmp_path, body=body)
    code, out, err = run_cli("check", model, "--select", "M017", "--no-config")
    assert "✅ All 1 files passed validation" in out, out
    assert "⚠️  1 warnings found (not critical)" in out, out


def test_the_validation_report_lists_ten_files(tmp_path):
    """PA12: the file list stops at ten and says how many are left."""
    model = _model(tmp_path)
    for i in range(12):
        (model / "definition" / "tables" / f"T{i}.tmdl").write_text(
            f"table T{i}\n\n    column c{i}\n", encoding="utf-8")
    code, out, err = run_cli("check", model, "--select", "M017", "--no-config")
    assert "❌ Found 12 errors in 12 files:" in out, out
    assert out.count("   - T") == 10, out
    assert "   ... and 2 more" in out, out


def test_the_validation_report_counts_the_model(tmp_path):
    """PA12: the model's own counts, as the reference's summary printed them."""
    model = _model(tmp_path, body=(
        "table Beans\n"
        "\tlineageTag: 11111111-1111-4111-8111-111111111111\n\n"
        "\tmeasure Kg = SUM(Beans[kg])\n"
        "\t\tlineageTag: 22222222-2222-4222-8222-222222222222\n"
    ))
    code, out, err = run_cli("check", model, "--select", "M017", "--no-config")
    assert "📊 Model Validation Summary:" in out, out
    assert "   📁 Total files: 1" in out, out
    assert "   ✅ Valid files: 1" in out, out
    assert "   ❌ Invalid files: 0" in out, out
    assert "   📊 Total measures: 1" in out, out
    assert "   📋 Total tables: 1" in out, out
    assert "   🏷️  Total lineageTags: 2" in out, out
    assert "   🔄 Duplicate lineageTags: 0" in out, out
    assert "   📈 Success rate: 100.0%" in out, out
