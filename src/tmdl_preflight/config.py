"""Project configuration: ``[tool.tmdl-preflight]`` and friends.

A configuration is read from the first of these found in the checked path
or one of its ancestors (the search stops at the repository root, the first
folder holding ``.git``):

1. ``.tmdl-preflight.toml``
2. ``.tmdl-preflight.json``
3. ``pyproject.toml`` with a ``[tool.tmdl-preflight]`` table

``--config PATH`` names a file explicitly instead. TOML needs Python 3.11 or
newer (``tomllib``); the JSON form works on every supported version.

Every key is validated: an unknown key, an unknown rule id or a
wrongly-typed option is a :class:`ConfigError` (CLI exit code 2), never a
silent no-op.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .rules.base import RuleSet, Severity

CONFIG_FILENAMES = (".tmdl-preflight.toml", ".tmdl-preflight.json")
PYPROJECT = "pyproject.toml"
TOOL_KEY = "tmdl-preflight"

# Project-level sections some rules read as a whole (declared contracts,
# refresh-policy settings, live-check options, the advisory list for the
# pytest plugin). Their content is validated by the rules that use them.
SECTION_KEYS = {"contracts", "refresh_policy", "live", "advisory", "table_roles", "measure_classes",
                "bookmarks"}

_TOP_LEVEL_KEYS = {
    "select", "ignore", "strict", "severity_overrides", "exclude", "rules",
    "exemptions", "profiles",
} | SECTION_KEYS
_PROFILE_KEYS = _TOP_LEVEL_KEYS - {"profiles"}
_EXEMPTION_KEYS = {"rule", "reason", "path", "object", "until"}


class ConfigError(ValueError):
    """The configuration is invalid; the message says what and where."""


@dataclass
class Exemption:
    """A reviewed, documented exception to one rule."""

    rule: str
    reason: str
    path: Optional[str] = None
    obj: Optional[str] = None
    until: Optional[_dt.date] = None

    def expired(self, today: _dt.date) -> bool:
        return self.until is not None and today > self.until

    def matches(self, violation) -> bool:
        if violation.rule_id != self.rule:
            return False
        if self.path is not None and not glob_match(self.path, violation.path or ""):
            return False
        if self.obj is not None and (violation.obj or "") != self.obj:
            return False
        return True

    def describe(self) -> str:
        where = " ".join(
            part for part in (
                self.path and f"path={self.path}",
                self.obj and f"object={self.obj}",
                self.until and f"until={self.until.isoformat()}",
            ) if part
        )
        return f"{self.rule} {where}".strip()

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "reason": self.reason,
            "path": self.path,
            "object": self.obj,
            "until": self.until.isoformat() if self.until else None,
        }


@dataclass
class Config:
    source: Optional[Path] = None
    select: Optional[list[str]] = None
    ignore: list[str] = field(default_factory=list)
    strict: bool = False
    severity_overrides: dict[str, Severity] = field(default_factory=dict)
    exclude: list[str] = field(default_factory=list)
    rule_options: dict[str, dict[str, Any]] = field(default_factory=dict)
    exemptions: list[Exemption] = field(default_factory=list)
    sections: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Globs
# ---------------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> "re.Pattern[str]":
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(pattern: str, path: str) -> bool:
    """Match a project-relative POSIX path against a glob.

    ``*`` stays within one folder, ``**`` crosses folders, ``?`` is one
    character. A pattern without ``/`` matches the file name alone. The path
    is always project-relative (``Shop.SemanticModel/definition/...``), so a
    pattern can never match a folder above the project.
    """
    path = path.replace("\\", "/")
    if "/" not in pattern:
        return bool(_glob_to_regex(pattern).match(path.rsplit("/", 1)[-1]))
    return bool(_glob_to_regex(pattern).match(path))


# ---------------------------------------------------------------------------
# Discovery and loading
# ---------------------------------------------------------------------------


def _has_tomllib() -> bool:
    return sys.version_info >= (3, 11)


def _load_toml(path: Path) -> dict:
    if not _has_tomllib():
        raise ConfigError(
            f"{path}: TOML configuration needs Python 3.11 or newer. Use a "
            f".tmdl-preflight.json file with the same keys, or upgrade Python."
        )
    import tomllib

    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"{path}: cannot read TOML ({exc})") from exc


def _pyproject_section(path: Path) -> Optional[dict]:
    """The ``[tool.tmdl-preflight]`` table of a pyproject.toml, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if f"[tool.{TOOL_KEY}" not in text:
        return None
    data = _load_toml(path)
    section = (data.get("tool") or {}).get(TOOL_KEY)
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: [tool.{TOOL_KEY}] must be a table")
    return section


def read_config_file(path: Path) -> dict:
    """Raw configuration mapping from any supported file."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"{path}: configuration file not found")
    if path.name == PYPROJECT:
        section = _pyproject_section(path)
        if section is None:
            raise ConfigError(f"{path}: has no [tool.{TOOL_KEY}] table")
        return section
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"{path}: cannot read JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{path}: the top level must be an object")
        return data
    if path.suffix == ".toml":
        data = _load_toml(path)
        # a standalone file may also nest everything under [tool.tmdl-preflight]
        nested = (data.get("tool") or {}).get(TOOL_KEY)
        return nested if isinstance(nested, dict) else data
    raise ConfigError(f"{path}: unsupported configuration format (use .toml or .json)")


def find_config(start: Path) -> Optional[Path]:
    """The configuration file that applies to ``start``, if any."""
    start = Path(start).resolve()
    if start.is_file():
        start = start.parent
    for folder in (start, *start.parents):
        for name in CONFIG_FILENAMES:
            candidate = folder / name
            if candidate.is_file():
                return candidate
        pyproject = folder / PYPROJECT
        if pyproject.is_file() and _pyproject_section(pyproject) is not None:
            return pyproject
        if (folder / ".git").exists():
            break
    return None


def _deep_merge(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _rule_lookup(ruleset: RuleSet) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for r in ruleset.rules:
        lookup[r.id.lower()] = r.id
        lookup[r.name.lower()] = r.id
    return lookup


def _resolve_rule(lookup: dict[str, str], value: Any, where: str) -> str:
    if not isinstance(value, str) or value.lower() not in lookup:
        raise ConfigError(
            f"{where}: {value!r} is not a rule id or name. Run "
            f"'tmdl-preflight rules' to list the valid ones."
        )
    return lookup[value.lower()]


def _string_list(value: Any, where: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: expected a list of strings")
    return value


def _parse_date(value: Any, where: str) -> _dt.date:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise ConfigError(f"{where}: 'until' must be a date written YYYY-MM-DD")


def _option_type_ok(default: Any, value: Any) -> bool:
    if default is None:
        return True  # free-form option (a path, a table, a structured list)
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(v, type(default[0])) for v in value) if default else isinstance(value, list)
    return isinstance(value, type(default))


def build_config(raw: dict, ruleset: RuleSet, source: Optional[Path] = None,
                 profile: Optional[str] = None) -> Config:
    """Validate a raw mapping (and an optional profile) into a Config."""
    label = str(source) if source else "configuration"
    unknown = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(
            f"{label}: unknown key(s) {', '.join(unknown)}. Valid keys: "
            f"{', '.join(sorted(_TOP_LEVEL_KEYS))}."
        )
    profiles = raw.get("profiles") or {}
    if not isinstance(profiles, dict):
        raise ConfigError(f"{label}: 'profiles' must be a table of named profiles")
    data = {k: v for k, v in raw.items() if k != "profiles"}
    if profile is not None:
        if profile not in profiles:
            known = ", ".join(sorted(profiles)) or "none defined"
            raise ConfigError(f"{label}: profile {profile!r} does not exist ({known})")
        prof = profiles[profile]
        if not isinstance(prof, dict):
            raise ConfigError(f"{label}: profiles.{profile} must be a table")
        bad = sorted(set(prof) - _PROFILE_KEYS)
        if bad:
            raise ConfigError(f"{label}: profiles.{profile}: unknown key(s) {', '.join(bad)}")
        data = _deep_merge(data, prof)

    lookup = _rule_lookup(ruleset)
    rules_by_id = {r.id: r for r in ruleset.rules}
    cfg = Config(source=source)
    for key in SECTION_KEYS:
        if key in data:
            cfg.sections[key] = data[key]

    if "select" in data:
        cfg.select = [_resolve_rule(lookup, v, f"{label}: select")
                      for v in _string_list(data["select"], f"{label}: select")]
    if "ignore" in data:
        cfg.ignore = [_resolve_rule(lookup, v, f"{label}: ignore")
                      for v in _string_list(data["ignore"], f"{label}: ignore")]
    if "strict" in data:
        if not isinstance(data["strict"], bool):
            raise ConfigError(f"{label}: 'strict' must be true or false")
        cfg.strict = data["strict"]
    overrides = data.get("severity_overrides") or {}
    if not isinstance(overrides, dict):
        raise ConfigError(f"{label}: 'severity_overrides' must map rule ids to severities")
    for key, value in overrides.items():
        rid = _resolve_rule(lookup, key, f"{label}: severity_overrides")
        try:
            cfg.severity_overrides[rid] = Severity(str(value).lower())
        except ValueError:
            raise ConfigError(
                f"{label}: severity_overrides.{key} must be error, warning or info"
            ) from None
    if "exclude" in data:
        cfg.exclude = _string_list(data["exclude"], f"{label}: exclude")
        for pattern in cfg.exclude:
            if pattern.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", pattern) or ".." in pattern.split("/"):
                raise ConfigError(
                    f"{label}: exclude pattern {pattern!r} must be relative to the "
                    f"project (for example '**/tables/Legacy*.tmdl')"
                )
    rules_section = data.get("rules") or {}
    if not isinstance(rules_section, dict):
        raise ConfigError(f"{label}: 'rules' must map rule ids to option tables")
    for key, options in rules_section.items():
        rid = _resolve_rule(lookup, key, f"{label}: rules")
        if not isinstance(options, dict):
            raise ConfigError(f"{label}: rules.{key} must be a table of options")
        defaults = rules_by_id[rid].option_defaults
        for opt, value in options.items():
            if opt not in defaults:
                valid = ", ".join(sorted(defaults)) or "this rule has no options"
                raise ConfigError(f"{label}: rules.{key}: unknown option {opt!r} ({valid})")
            if not _option_type_ok(defaults[opt], value):
                raise ConfigError(
                    f"{label}: rules.{key}.{opt} must be of type "
                    f"{type(defaults[opt]).__name__}"
                )
        cfg.rule_options[rid] = dict(options)
    exemptions = data.get("exemptions") or []
    if not isinstance(exemptions, list):
        raise ConfigError(f"{label}: 'exemptions' must be a list of tables")
    for n, entry in enumerate(exemptions, start=1):
        where = f"{label}: exemptions[{n}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: must be a table")
        bad = sorted(set(entry) - _EXEMPTION_KEYS)
        if bad:
            raise ConfigError(f"{where}: unknown key(s) {', '.join(bad)}")
        if "rule" not in entry:
            raise ConfigError(f"{where}: 'rule' is required")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ConfigError(
                f"{where}: 'reason' is required; write down why this exception "
                f"is acceptable so the next reviewer can judge it"
            )
        for opt in ("path", "object"):
            if opt in entry and not isinstance(entry[opt], str):
                raise ConfigError(f"{where}: '{opt}' must be a string")
        cfg.exemptions.append(
            Exemption(
                rule=_resolve_rule(lookup, entry["rule"], where),
                reason=reason.strip(),
                path=entry.get("path"),
                obj=entry.get("object"),
                until=_parse_date(entry["until"], where) if "until" in entry else None,
            )
        )
    return cfg


def load_config(
    ruleset: RuleSet,
    start: Optional[Path] = None,
    explicit: Optional[Path] = None,
    profile: Optional[str] = None,
) -> Config:
    """Find (or read the explicit) configuration and validate it."""
    path = Path(explicit) if explicit is not None else (find_config(start) if start else None)
    if path is None:
        if profile is not None:
            raise ConfigError(f"--profile {profile} was given, but no configuration file was found")
        return Config()
    return build_config(read_config_file(path), ruleset, source=path, profile=profile)
