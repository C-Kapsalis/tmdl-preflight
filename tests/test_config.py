"""Configuration files: discovery, validation, profiles, excludes, exemptions."""

from __future__ import annotations

import datetime as dt
import json
import sys

import pytest

from tmdl_preflight.cli import main
from tmdl_preflight.config import ConfigError, build_config, find_config, glob_match, load_config
from tmdl_preflight.rules import default_ruleset

needs_toml = pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib needs 3.11+")


def _strip_units_format(definition):
    f = definition / "tables" / "Sales Measures.tmdl"
    f.write_text(
        f.read_text(encoding="utf-8").replace(
            "\tmeasure 'Units Sold' = SUM(Sales[quantity])\n\t\tformatString: #,0\n",
            "\tmeasure 'Units Sold' = SUM(Sales[quantity])\n",
        ),
        encoding="utf-8",
    )


def _write_json(project, data):
    (project / ".tmdl-preflight.json").write_text(json.dumps(data), encoding="utf-8")


class TestGlobs:
    def test_double_star_and_single_star(self):
        path = "Shop.SemanticModel/definition/tables/Legacy Sales.tmdl"
        assert glob_match("**/tables/Legacy*.tmdl", path)
        assert glob_match("*.SemanticModel/definition/tables/*.tmdl", path)
        assert not glob_match("*/tables/*.tmdl", path)
        assert glob_match("Legacy*.tmdl", path)  # no slash: file name only

    def test_never_matches_above_the_project(self):
        # the identity path never contains the checkout location
        assert not glob_match("Users/**", "Shop.SemanticModel/definition/model.tmdl")


class TestDiscovery:
    def test_json_found_from_nested_path(self, project, definition):
        _write_json(project, {"ignore": ["S002"]})
        assert find_config(definition) == project / ".tmdl-preflight.json"

    def test_search_stops_at_repository_root(self, tmp_path):
        (tmp_path / ".tmdl-preflight.json").write_text("{}", encoding="utf-8")
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        assert find_config(repo) is None

    @needs_toml
    def test_pyproject_section(self, project):
        (project / "pyproject.toml").write_text(
            '[project]\nname = "x"\n\n[tool.tmdl-preflight]\nignore = ["S002"]\n',
            encoding="utf-8",
        )
        cfg = load_config(default_ruleset(), start=project)
        assert cfg.ignore == ["S002"]

    def test_pyproject_without_section_is_skipped(self, project):
        (project / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        assert find_config(project) is None

    @needs_toml
    def test_toml_file_wins_over_json(self, project):
        _write_json(project, {"ignore": ["S001"]})
        (project / ".tmdl-preflight.toml").write_text('ignore = ["S002"]\n', encoding="utf-8")
        assert load_config(default_ruleset(), start=project).ignore == ["S002"]

    def test_toml_on_old_python_fails_loudly(self, project, monkeypatch):
        import tmdl_preflight.config as config

        monkeypatch.setattr(config, "_has_tomllib", lambda: False)
        (project / ".tmdl-preflight.toml").write_text('ignore = ["S002"]\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="Python 3.11"):
            load_config(default_ruleset(), start=project)


class TestValidation:
    def test_unknown_key(self):
        with pytest.raises(ConfigError, match="unknown key"):
            build_config({"selct": ["M001"]}, default_ruleset())

    def test_unknown_rule(self):
        with pytest.raises(ConfigError, match="Z999"):
            build_config({"ignore": ["Z999"]}, default_ruleset())

    def test_rule_names_resolve_to_ids(self):
        cfg = build_config({"ignore": ["measure-descriptions"]}, default_ruleset())
        assert cfg.ignore == ["S002"]

    def test_bad_severity(self):
        with pytest.raises(ConfigError, match="error, warning or info"):
            build_config({"severity_overrides": {"R007": "fatal"}}, default_ruleset())

    def test_unknown_rule_option(self):
        with pytest.raises(ConfigError, match="unknown option"):
            build_config({"rules": {"S002": {"min_len": 3}}}, default_ruleset())

    def test_wrong_option_type(self):
        with pytest.raises(ConfigError, match="type int"):
            build_config({"rules": {"S002": {"min_length": "3"}}}, default_ruleset())

    def test_exemption_needs_reason(self):
        with pytest.raises(ConfigError, match="'reason' is required"):
            build_config({"exemptions": [{"rule": "S002", "reason": " "}]}, default_ruleset())

    def test_exemption_date(self):
        with pytest.raises(ConfigError, match="YYYY-MM-DD"):
            build_config(
                {"exemptions": [{"rule": "S002", "reason": "r", "until": "next week"}]},
                default_ruleset(),
            )

    def test_absolute_exclude_rejected(self):
        with pytest.raises(ConfigError, match="relative to the project"):
            build_config({"exclude": ["/Users/me/model/**"]}, default_ruleset())

    def test_profiles_deep_merge(self):
        raw = {
            "ignore": ["S002"],
            "rules": {"S002": {"min_length": 5, "placeholder_words": ["todo"]}},
            "profiles": {"ci": {"strict": True, "rules": {"S002": {"min_length": 20}}}},
        }
        cfg = build_config(raw, default_ruleset(), profile="ci")
        assert cfg.strict is True and cfg.ignore == ["S002"]
        assert cfg.rule_options["S002"] == {"min_length": 20, "placeholder_words": ["todo"]}

    def test_unknown_profile(self):
        with pytest.raises(ConfigError, match="profile 'nightly' does not exist"):
            build_config({"profiles": {"ci": {}}}, default_ruleset(), profile="nightly")


class TestCliWithConfig:
    def test_ignore_from_config(self, project, definition, capsys):
        _strip_units_format(definition)
        _write_json(project, {"ignore": ["S001"]})
        assert main(["check", str(project), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["violations"] == []

    def test_no_config_flag(self, project, definition, capsys):
        _strip_units_format(definition)
        _write_json(project, {"ignore": ["S001"]})
        main(["check", str(project), "--json", "--no-config"])
        assert json.loads(capsys.readouterr().out)["summary"]["infos"] == 1

    def test_explicit_config_path(self, project, definition, tmp_path, capsys):
        _strip_units_format(definition)
        cfg = tmp_path / "elsewhere.json"
        cfg.write_text(json.dumps({"severity_overrides": {"S001": "error"}}), encoding="utf-8")
        assert main(["check", str(project), "--config", str(cfg)]) == 1
        assert "S001 error" in capsys.readouterr().out

    def test_invalid_config_exits_two(self, project, capsys):
        _write_json(project, {"nonsense": 1})
        assert main(["check", str(project)]) == 2
        assert "configuration error" in capsys.readouterr().err

    def test_profile_strict(self, project, definition, capsys):
        f = definition / "tables" / "__Calendar.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "lineageTag: 7f22e2f3-e273-44b5-8ad6-d1e2f3041526", "lineageTag: oops"
            ),
            encoding="utf-8",
        )
        _write_json(project, {"profiles": {"ci": {"strict": True}}})
        assert main(["check", str(project)]) == 0
        assert main(["check", str(project), "--profile", "ci"]) == 1

    def test_exclude_glob(self, project, definition, capsys):
        _strip_units_format(definition)
        _write_json(project, {"exclude": ["**/Sales Measures.tmdl"]})
        main(["check", str(project), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["violations"] == [] and payload["summary"]["excluded"] == 1

    def test_exemption_applies_and_expires(self, project, definition, capsys):
        _strip_units_format(definition)
        future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
        _write_json(project, {"exemptions": [{
            "rule": "S001", "object": "Sales Measures[Units Sold]",
            "reason": "formatted in the report layer", "until": future,
        }]})
        main(["check", str(project), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["violations"] == [] and payload["summary"]["exempted"] == 1

        past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        _write_json(project, {"exemptions": [{
            "rule": "S001", "path": "**/Sales Measures.tmdl",
            "reason": "formatted in the report layer", "until": past,
        }]})
        main(["check", str(project), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert [v["rule"] for v in payload["violations"]] == ["S001"]
        assert payload["exemptions"]["expired"][0]["until"] == past
        main(["check", str(project)])
        assert "expired on" in capsys.readouterr().out

    def test_rule_options_from_config(self, project, definition, capsys):
        f = definition / "tables" / "Sales Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "/// Number of distinct orders placed.", "/// Orders"
            ),
            encoding="utf-8",
        )
        main(["check", str(project), "--json", "--select", "S002"])
        assert json.loads(capsys.readouterr().out)["summary"]["infos"] == 1
        _write_json(project, {"rules": {"S002": {"min_length": 4}}})
        main(["check", str(project), "--json", "--select", "S002"])
        assert json.loads(capsys.readouterr().out)["summary"]["infos"] == 0


@needs_toml
def test_shipped_example_config_is_valid():
    from pathlib import Path

    example = Path(__file__).parent.parent / "examples" / "ci" / "tmdl-preflight.toml"
    cfg = load_config(default_ruleset(), explicit=example, profile="ci")
    assert cfg.strict and cfg.ignore == ["S002"] and cfg.exemptions
