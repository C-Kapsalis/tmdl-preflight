"""P0 TMDL guardian: pre-import sanity of a semantic model.

Three checks:
  1. the helper-measures table file: validator errors, root-level comment
     indented under a tab, unpaired DAX fences;
  2. every .tmdl parses cleanly, has no NUL bytes, and the core files have no
     Windows line endings;
  3. the folder structure is intact (definition/, tables/, model.tmdl,
     database.tmdl, the required helper-measures table file).

Rule (new, selected by name): tmdl-file-sanity, configured with the earlier check
required table; lineage-tag format is the existing M004.
Stand-ins: ``universal`` (clean) and ``spinout_02_db`` (CRLF model.tmdl, no
database.tmdl, an indented root comment in the helper-measures file).
"""

from __future__ import annotations

from conftest import run_check, violations

FLEET = "measure_organization_fleet"
CLEAN = "universal/Performance.SemanticModel"
BROKEN = "spinout_02_db/Performance.SemanticModel"
RULE = "tmdl-file-sanity"
# The line-ending check is opt-in in the tool (Windows checkouts are often
# CRLF); the test turns it on to reproduce the earlier check's verdicts.
CONFIG = {"rules": {RULE: {"required_tables": ["Helper Measures"], "check_line_endings": True}}}


def _helper_findings(payload):
    return [v for v in violations(payload) if (v.get("path") or "").endswith("Helper Measures.tmdl")]


class TestP0TmdlGuardian:
    def test_p0_helper_measures_syntax_validation_clean(self, stand_in):
        # earlier verdict: XPASS (xfail strict=False; the stand-in has valid tags)
        code, payload = run_check(stand_in(FLEET) / CLEAN, RULE, "M004", config=CONFIG)
        assert code == 0
        assert _helper_findings(payload) == []

    def test_p0_helper_measures_syntax_validation_broken(self, stand_in):
        # earlier verdict: XFAIL (fails on the indented root comment)
        code, payload = run_check(stand_in(FLEET) / BROKEN, RULE, "M004", config=CONFIG)
        found = _helper_findings(payload)
        assert len(found) == 1
        assert "root-level comment" in found[0]["message"]
        assert code == 1

    def test_p0_all_tmdl_files_parseable_clean(self, stand_in):
        code, payload = run_check(stand_in(FLEET) / CLEAN, RULE, config=CONFIG)
        assert code == 0
        assert violations(payload) == []

    def test_p0_all_tmdl_files_parseable_broken(self, stand_in):
        # BUGFIX: the earlier check read files with universal newlines, so its CRLF
        # check could never fire (verdict pass); the tool reports the CRLF.
        code, payload = run_check(stand_in(FLEET) / BROKEN, RULE, config=CONFIG)
        assert code == 1
        crlf = [v for v in violations(payload) if "Windows line endings" in v["message"]]
        assert len(crlf) == 1
        assert crlf[0]["path"].endswith("model.tmdl")

    def test_p0_null_byte_is_reported(self, stand_in):
        model = stand_in(FLEET) / CLEAN
        f = model / "definition" / "tables" / "Ads Measures.tmdl"
        f.write_bytes(f.read_bytes() + b"\x00\n")
        code, payload = run_check(model, RULE, config=CONFIG)
        assert code == 1
        assert any("null byte" in v["message"].lower() for v in violations(payload))

    def test_p0_model_structure_integrity_clean(self, stand_in):
        code, payload = run_check(stand_in(FLEET) / CLEAN, RULE, config=CONFIG)
        assert code == 0
        assert not [v for v in violations(payload) if "missing" in v["message"]]

    def test_p0_model_structure_integrity_broken(self, stand_in):
        # earlier check: "required files missing: ['database.tmdl']"
        code, payload = run_check(stand_in(FLEET) / BROKEN, RULE, config=CONFIG)
        assert code == 1
        missing = [v for v in violations(payload) if "missing" in v["message"]]
        assert len(missing) == 1
        assert "database.tmdl" in missing[0]["message"]

    def test_p0_missing_helper_measures_table(self, stand_in):
        model = stand_in(FLEET) / CLEAN
        (model / "definition" / "tables" / "Helper Measures.tmdl").unlink()
        code, payload = run_check(model, RULE, config=CONFIG)
        assert code == 1
        assert any("Helper Measures" in v["message"] for v in violations(payload))
