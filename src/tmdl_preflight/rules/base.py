"""Rule framework: Violation, Severity, Rule and the Context they run on."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from ..model import SemanticModel
from ..parser import find_definition_dirs, find_report_dirs, parse_model


class Severity(enum.Enum):
    ERROR = "error"      # will break an import/deploy or silently corrupt results
    WARNING = "warning"  # suspicious; deserves a look before shipping
    INFO = "info"        # advisory signal, never blocks

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


def item_relative_path(file: Optional[Path]) -> Optional[str]:
    """A stable, project-relative identity for a file.

    The path is taken relative to the folder that holds the file's
    ``*.SemanticModel`` or ``*.Report`` item, so it never includes absolute
    or ancestor directories: ``BikeShop.SemanticModel/definition/tables/
    Sales.tmdl`` no matter where the project is checked out. Files outside
    any item folder fall back to their name.
    """
    if file is None:
        return None
    p = Path(file)
    parts = p.parts
    for idx in range(len(parts) - 1, -1, -1):
        if parts[idx].endswith((".SemanticModel", ".Report")):
            return PurePosixPath(*parts[idx:]).as_posix()
    return p.name


@dataclass
class Violation:
    rule_id: str
    severity: Severity
    message: str
    file: Optional[Path] = None
    line: Optional[int] = None
    obj: Optional[str] = None
    fixable: bool = False

    @property
    def path(self) -> Optional[str]:
        """Project-relative path of ``file`` (see ``item_relative_path``)."""
        return item_relative_path(self.file)

    def identity(self) -> tuple[str, str, str]:
        """Line-independent identity used by baselines and exemptions."""
        return (self.rule_id, self.path or "", self.obj or "")

    def location(self) -> str:
        if self.file is None:
            return ""
        loc = str(self.file)
        if self.line is not None:
            loc += f":{self.line}"
        return loc

    def to_dict(self) -> dict:
        return {
            "rule": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
            "file": str(self.file) if self.file else None,
            "line": self.line,
            "object": self.obj,
            "fixable": self.fixable,
            "path": self.path,
        }


class Context:
    """Everything a rule may look at: parsed model(s) plus report folder(s).

    A Context is built from a user-supplied path (a PBIP project root, a
    ``*.SemanticModel`` folder, a ``definition`` folder or a ``*.Report``
    folder) and lazily parses each discovered model. ``reload()`` drops the
    parse cache; the engine calls it after fixers have rewritten files, so
    the re-check always runs against what is actually on disk.
    """

    def __init__(self, root: Path, exclude: Optional[list[str]] = None):
        self.root = Path(root)
        self.exclude: list[str] = list(exclude or [])
        # files under models/reports that were skipped entirely because every
        # file they hold matches an ``exclude`` glob
        self.excluded_files: int = 0
        self.definition_dirs: list[Path] = self._keep(find_definition_dirs(self.root))
        self.report_dirs: list[Path] = self._keep(find_report_dirs(self.root))
        self._models: Optional[list[SemanticModel]] = None
        # project-level sections of the configuration (for example
        # ``contracts``), set by the CLI after the config is loaded
        self.options: dict[str, Any] = {}
        # free-text notes rules want shown with the report (tighten hints)
        self.notes: list[str] = []

    def model_key(self, model: SemanticModel) -> str:
        """The model's ``*.SemanticModel`` folder relative to the scan root
        (POSIX), or the folder name when the scan root is inside it."""
        folder = model.definition_path.parent
        rel = self.scan_relative(folder)
        if rel in (None, "", "."):
            return folder.name
        return rel

    def model_matches(self, wanted: Optional[str], model: SemanticModel) -> bool:
        """True when a configured model key names this model. Keys compare
        with or without the ``.SemanticModel`` suffix; no key matches all."""
        if not wanted:
            return True
        def norm(key: str) -> str:
            key = key.replace("\\", "/").strip("/")
            return key[: -len(".SemanticModel")] if key.endswith(".SemanticModel") else key
        have = norm(self.model_key(model))
        want = norm(wanted)
        return have == want or have.endswith("/" + want)

    # -- exclusions --------------------------------------------------------
    def scan_relative(self, file: Path) -> Optional[str]:
        """``file`` relative to the scan root (POSIX), or None if outside it."""
        try:
            return Path(file).resolve().relative_to(self.root.resolve()).as_posix()
        except (ValueError, OSError):
            return None

    def is_excluded(self, file: Path) -> bool:
        """True when an ``exclude`` glob matches the file's path relative to
        the scan root or to its PBIP item. Folders above the scan root never
        take part, so a checkout under ``~/legacy/`` is still scanned."""
        if not self.exclude:
            return False
        from ..config import glob_match  # local import: config imports rules

        candidates = [c for c in (self.scan_relative(file), item_relative_path(file)) if c]
        return any(glob_match(p, c) for p in self.exclude for c in candidates)

    def _keep(self, folders: list[Path]) -> list[Path]:
        if not self.exclude:
            return folders
        kept = []
        for folder in folders:
            files = [f for f in folder.rglob("*") if f.is_file()]
            if files and all(self.is_excluded(f) for f in files):
                self.excluded_files += len(files)
                continue
            kept.append(folder)
        return kept

    def files_scanned(self) -> int:
        """TMDL and report JSON files the run looked at (excluded ones not
        counted)."""
        n = 0
        for d in self.definition_dirs:
            n += sum(1 for f in d.rglob("*.tmdl") if not self.is_excluded(f))
        for r in self.report_dirs:
            n += sum(
                1 for f in r.rglob("*")
                if f.is_file() and f.suffix in (".json", ".pbir") and not self.is_excluded(f)
            )
        return n

    @property
    def models(self) -> list[SemanticModel]:
        if self._models is None:
            self._models = [parse_model(d) for d in self.definition_dirs]
        return self._models

    def reload(self) -> None:
        self._models = None

    def is_empty(self) -> bool:
        return not self.definition_dirs and not self.report_dirs


class Rule:
    """Base class for a preflight rule.

    Subclasses set the class attributes and implement ``check``. Rules that
    can repair their own violation class also implement ``fix``; the repair
    contract is: *only touch what the check's failure mode describes, be
    idempotent, and never overwrite human-authored semantics.*
    """

    id: str = ""
    name: str = ""
    severity: Severity = Severity.ERROR
    description: str = ""
    fixable: bool = False
    # False for fixers that change data or regenerate content (for example a
    # partition's M source). They never run as part of a blanket ``fix``;
    # only when the rule is selected explicitly by id or name.
    safe: bool = True
    # True for rules that encode one team's conventions (naming, placement).
    # They run only when selected by id or name (--select or config select).
    opt_in: bool = False
    # False for defects that must never be accepted into a baseline (they
    # stop the model from opening or deploying at all)
    baselinable: bool = True
    # per-rule options and their defaults; config files may override them
    option_defaults: dict[str, Any] = {}

    def __init__(self) -> None:
        self.options: dict[str, Any] = dict(self.option_defaults)

    def configure(self, options: dict[str, Any]) -> None:
        """Apply per-rule options (already validated by the config loader)."""
        self.options.update(options)

    def check(self, ctx: Context) -> list[Violation]:  # pragma: no cover
        raise NotImplementedError

    def fix(self, ctx: Context) -> list[str]:
        """Apply the auto-repair; return human-readable descriptions of each
        change made. Only called when ``fixable`` is True."""
        return []

    # convenience for subclasses -------------------------------------------------
    def violation(
        self,
        message: str,
        file: Optional[Path] = None,
        line: Optional[int] = None,
        obj: Optional[str] = None,
        severity: Optional[Severity] = None,
    ) -> Violation:
        return Violation(
            rule_id=self.id,
            severity=severity or self.severity,
            message=message,
            file=file,
            line=line,
            obj=obj,
            fixable=self.fixable,
        )


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)

    def select(self, select: Optional[set[str]] = None, ignore: Optional[set[str]] = None) -> "RuleSet":
        chosen = []
        for r in self.rules:
            keys = {r.id.lower(), r.name.lower()}
            if select is not None and not (keys & select):
                continue
            if select is None and r.opt_in:
                continue  # conventions rules run only when named
            if ignore is not None and (keys & ignore):
                continue
            chosen.append(r)
        return RuleSet(chosen)
