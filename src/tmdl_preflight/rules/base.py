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

    def __init__(self, root: Path):
        self.root = Path(root)
        self.definition_dirs: list[Path] = find_definition_dirs(self.root)
        self.report_dirs: list[Path] = find_report_dirs(self.root)
        self._models: Optional[list[SemanticModel]] = None

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
            if ignore is not None and (keys & ignore):
                continue
            chosen.append(r)
        return RuleSet(chosen)
