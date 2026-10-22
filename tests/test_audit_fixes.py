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


def test_any_refused_fixer_edit_is_reported_and_exits_2(definition):
    """The same swallow as R007's, in the field-parameter comma fixer: a
    refused edit is reported, never dropped."""
    f = definition / "tables" / "Metric Selector.tmdl"
    text = f.read_text(encoding="utf-8").replace(
        '\t\t\t\t    ( "Orders #", NAMEOF ( [Orders #] ), 1 ),', "\t\t\t\t    ,")
    mixed = text.replace("\n", "\r\n", 1).encode("utf-8")
    f.write_bytes(mixed)
    code, out, err = run_cli("fix", definition.parent, "--select", "F001",
                             "--no-config")
    assert f.read_bytes() == mixed
    assert code == 2, (code, out, err)
    assert "refused  F001: " in out and "Metric Selector.tmdl" in out, out
    assert "ERROR" in err, err


# ---------------------------------------------------------------------------
# 4. a targets file the tool cannot use is named, not ignored
# ---------------------------------------------------------------------------


def test_manifest_warns_about_a_missing_targets_file(tmp_path, project, monkeypatch):
    monkeypatch.chdir(project)
    code, out, err = run_cli("manifest", "BikeShop.SemanticModel", "--no-config",
                             "--out", str(tmp_path / "m.json"),
                             "--targets", str(tmp_path / "nope.yml"))
    assert code == 0, (out, err)
    assert "nope.yml" in err and "does not exist" in err, err


def test_refs_warns_about_an_unparseable_targets_file(tmp_path, project):
    bad = tmp_path / "targets.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out, err = run_cli("refs", "Revenue", str(project), "--targets", str(bad))
    assert code == 0, (out, err)
    assert "targets.json" in err and "not valid JSON" in err, err


def test_a_yaml_targets_file_without_pyyaml_is_named(tmp_path, project, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "yaml", None)  # import yaml -> ImportError
    t = tmp_path / "targets.yml"
    t.write_text("clients:\n  one:\n    model_path: X.SemanticModel\n", encoding="utf-8")
    code, out, err = run_cli("refs", "Revenue", str(project), "--targets", str(t))
    assert code == 0, (out, err)
    assert "targets.yml" in err and "PyYAML" in err, err


def test_a_usable_targets_file_prints_no_warning(tmp_path, project):
    t = tmp_path / "targets.json"
    t.write_text('{"one": {"model_path": "BikeShop.SemanticModel"}}', encoding="utf-8")
    code, out, err = run_cli("refs", "Revenue", str(project), "--targets", str(t))
    assert "WARNING" not in err, err


# ---------------------------------------------------------------------------
# 5. every file the tool writes ends its lines with LF, on every OS
# ---------------------------------------------------------------------------

import json  # noqa: E402
import pathlib  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def windows_text_mode(monkeypatch):
    """Write text files the way Windows does in text mode: a ``\\n`` becomes
    ``\\r\\n`` unless the caller asked for ``newline="\\n"`` or ``""``.
    CI runs the real thing on windows-latest; this makes the same writes
    show on every OS."""
    real = pathlib.Path.write_text

    def write_text(self, data, encoding=None, errors=None, newline=None):
        if newline is None:
            data = data.replace("\n", "\r\n")
            newline = ""
        return real(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(pathlib.Path, "write_text", write_text)


def _lf_only(path: Path) -> None:
    raw = path.read_bytes()
    assert raw.endswith(b"\n"), raw[-20:]
    assert b"\r" not in raw, raw[:200]


def test_check_capture_floor_writes_lf(windows_text_mode, project, tmp_path):
    out_file = tmp_path / "floor.json"
    code, out, err = run_cli("check", project, "--select", "R016",
                             "--capture-floor", str(out_file), "--no-config")
    assert code == 0, (out, err)
    _lf_only(out_file)


def test_the_baseline_file_is_lf(windows_text_mode, project, tmp_path):
    out_file = tmp_path / "baseline.json"
    code, out, err = run_cli("baseline", project, "--output", str(out_file),
                             "--no-config")
    assert code == 0, (out, err)
    _lf_only(out_file)


def test_clear_ready_rewrites_the_entries_file_with_lf(windows_text_mode, tmp_path):
    from tmdl_preflight.sqlviews import clear_ready

    path = tmp_path / "entries.json"
    data = {"entries": [{"client": "one"}, {"client": "two"}]}
    path.write_bytes(json.dumps(data).encode("utf-8"))
    assert clear_ready(path, data, ["one"]) == 1
    _lf_only(path)


def test_the_holdbacks_file_is_lf(windows_text_mode, tmp_path):
    entries = tmp_path / "entries.json"
    entries.write_bytes(b'{"schema_version": 1, "entries": []}')
    sql = tmp_path / "sql"
    sql.mkdir()
    hb = tmp_path / "deploy_holdbacks.yml"
    code, out, err = run_cli("schema-check", "--sql-dir", sql, "--entries", entries,
                             "--holdbacks", hb, "--write-holdbacks")
    assert code == 0, (out, err)
    _lf_only(hb)


def test_live_recordings_are_lf(windows_text_mode, tmp_path):
    from tmdl_preflight.live import RecordingClient

    client = RecordingClient(None, tmp_path / "rec")
    client._write("answer.json", {"rows": [1, 2]})
    _lf_only(tmp_path / "rec" / "answer.json")


def test_every_write_text_in_the_tool_names_its_newline():
    """A text-mode write without ``newline=`` writes CRLF on Windows."""
    import ast

    src = Path(__file__).resolve().parent.parent / "src" / "tmdl_preflight"
    missing = []
    for file in sorted(src.rglob("*.py"), key=lambda p: p.as_posix()):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "write_text"
                    and not any(k.arg == "newline" for k in node.keywords)):
                missing.append(f"{file.name}:{node.lineno}")
    assert missing == [], missing


# ---------------------------------------------------------------------------
# 6. smaller findings
# ---------------------------------------------------------------------------


def test_r007_finding_is_one_line(tmp_path):
    model = _autodetected(tmp_path)
    code, out, err = run_cli("check", model, "--select", "R007", "--no-config")
    lines = [ln for ln in out.splitlines() if " R007 " in ln]
    assert len(lines) == 1, out
    assert "AutoDetected_5c1d2e3f-4a5b-4c6d-8e7f-901234567890" in lines[0], out


def test_r007_json_message_has_no_newline(tmp_path):
    import json as _json

    model = _autodetected(tmp_path)
    code, out, err = run_cli("check", model, "--select", "R007", "--json", "--no-config")
    found = [v for v in _json.loads(out)["violations"] if v["rule"] == "R007"]
    assert found and "\n" not in found[0]["message"], found


def test_r003_names_an_autodetected_relationship_readably(tmp_path):
    dup = (
        "relationship 1f6f2b3a-8c1d-4e5f-9a70-1b2c3d4e5f60\n"
        "\tfromColumn: Beans.kg\n"
        "\ttoColumn: Beans.id\n\n"
        + AUTODETECTED
    )
    model = _autodetected(tmp_path, dup.encode())
    code, out, err = run_cli("check", model, "--select", "R003", "--no-config")
    assert "[relationship AutoDetected_5c1d2e3f]" in out, out
    assert "duplicate of relationship 1f6f2b3a:" in out, out
    assert "AutoDete]" not in out, out


def test_format_resolve_names_a_missing_calculation_group(project):
    code, out, err = run_cli("format-resolve", project, "--name", "Revenue")
    assert code == 2, (code, out, err)
    assert "z-Selector Format" in err and "--table" in err, err


def test_grain_check_without_guard_table_is_a_usage_error(project):
    code, out, err = run_cli("grain", project, "--check")
    assert code == 2, (code, out, err)
    assert "--check needs --guard-table" in err, err


def test_the_text_report_names_excluded_files(tmp_path):
    _model(tmp_path / "live", BEANS, "Cafe")
    _model(tmp_path / "old_legacy", BEANS, "Old")
    code, out, err = run_cli("check", tmp_path, "--no-config")
    assert "excluded: 2 file(s) in excluded paths" in out, out


def test_no_exclusion_note_when_nothing_was_excluded(tmp_path):
    _model(tmp_path, BEANS)
    code, out, err = run_cli("check", tmp_path, "--no-config")
    assert "excluded:" not in out, out
