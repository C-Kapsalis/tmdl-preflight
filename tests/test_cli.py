"""CLI behaviour: subcommands, selection flags, JSON output, exit codes."""

from __future__ import annotations

import json
import re

from tmdl_preflight.cli import main


def _break_lineage(definition):
    products = (definition / "tables" / "Products.tmdl").read_text(encoding="utf-8")
    tag = re.search(r"lineageTag:\s*(\S+)", products).group(1)
    stores_file = definition / "tables" / "Stores.tmdl"
    stores = stores_file.read_text(encoding="utf-8")
    old = re.search(r"lineageTag:\s*(\S+)", stores).group(1)
    stores_file.write_text(stores.replace(old, tag, 1), encoding="utf-8")


class TestCheckCommand:
    def test_clean_project_exits_zero(self, project, capsys):
        assert main(["check", str(project)]) == 0
        out = capsys.readouterr().out
        assert "0 error(s)" in out

    def test_violation_exits_nonzero(self, project, definition, capsys):
        _break_lineage(definition)
        assert main(["check", str(project)]) == 1
        out = capsys.readouterr().out
        assert "M003" in out

    def test_json_output(self, project, definition, capsys):
        _break_lineage(definition)
        assert main(["check", str(project), "--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["errors"] == 1
        assert payload["violations"][0]["rule"] == "M003"
        assert payload["violations"][0]["fixable"] is True

    def test_select_and_ignore(self, project, definition, capsys):
        _break_lineage(definition)
        # only a rule that is clean -> exit 0
        assert main(["check", str(project), "--select", "D001"]) == 0
        capsys.readouterr()
        # ignore the broken rule -> exit 0
        assert main(["check", str(project), "--ignore", "M003"]) == 0
        capsys.readouterr()
        # select by name works too
        assert main(["check", str(project), "--select", "lineage-duplicates"]) == 1

    def test_missing_path_exits_two(self, tmp_path, capsys):
        assert main(["check", str(tmp_path / "nope")]) == 2
        err = capsys.readouterr().err
        assert "cannot find the path" in err

    def test_folder_without_model_exits_two(self, tmp_path, capsys):
        assert main(["check", str(tmp_path)]) == 2
        err = capsys.readouterr().err
        assert "no semantic model or report found" in err

    def test_unknown_rule_id_exits_two(self, project, capsys):
        assert main(["check", str(project), "--select", "Z999"]) == 2
        err = capsys.readouterr().err
        assert "Z999".lower() in err.lower()
        assert "tmdl-preflight rules" in err

    def test_unknown_ignore_id_exits_two(self, project, capsys):
        assert main(["check", str(project), "--ignore", "nonsense-rule"]) == 2
        assert "do not exist" in capsys.readouterr().err

    def test_non_ascii_object_names_do_not_crash_output(self, project, definition):
        # Regression: object names outside the console code page (Greek,
        # accented, emoji) must never crash the report with a
        # UnicodeEncodeError — unencodable characters are replaced instead.
        import subprocess
        import sys as _sys

        f = definition / "tables" / "Sales Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8")
            + "\n\tmeasure 'Πωλήσεις Test' = COUNTROWS(Sales)\n"
            "\t\tlineageTag: aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee\n",
            encoding="utf-8",
        )
        env = dict(**__import__("os").environ, PYTHONIOENCODING="ascii")
        result = subprocess.run(
            [
                _sys.executable,
                "-c",
                "import sys; from tmdl_preflight.cli import main; "
                "sys.exit(main(sys.argv[1:]))",
                "check",
                str(project),
                "--select",
                "S001",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert "UnicodeEncodeError" not in result.stderr
        assert result.returncode == 0  # S001 is info: advisory, never blocks
        assert "S001" in result.stdout


class TestFixCommand:
    def test_fix_repairs_and_exits_zero(self, project, definition, capsys):
        _break_lineage(definition)
        assert main(["fix", str(project)]) == 0
        out = capsys.readouterr().out
        assert "fixed  M003" in out
        # and the project is now genuinely clean
        assert main(["check", str(project)]) == 0

    def test_fix_json_reports_fixes(self, project, definition, capsys):
        _break_lineage(definition)
        assert main(["fix", str(project), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["fixes_applied"] == 1
        assert payload["violations"] == []


class TestRulesCommand:
    def test_rules_listing(self, capsys):
        assert main(["rules"]) == 0
        out = capsys.readouterr().out
        for rule_id in ("M001", "M003", "D001", "R001", "F001", "B001", "S001"):
            assert rule_id in out

    def test_rules_flag_alias(self, capsys):
        assert main(["--rules"]) == 0
        assert "M003" in capsys.readouterr().out

    def test_rules_json(self, capsys):
        assert main(["rules", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 21
        fixable = {r["id"] for r in payload if r["fixable"]}
        assert fixable == {"M003", "M004", "M006", "F001", "B001"}
