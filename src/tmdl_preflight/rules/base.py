"""Rule framework: Violation, Severity, Rule and the Context they run on."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..model import SemanticModel
from ..parser import find_definition_dirs, find_report_dirs, parse_model


class Severity(enum.Enum):
    ERROR = "error"      # will break an import/deploy or silently corrupt results
    WARNING = "warning"  # suspicious; deserves a look before shipping
    INFO = "info"        # advisory signal, never blocks

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass
class Violation:
    rule_id: str
    severity: Severity
    message: str
    file: Optional[Path] = None
    line: Optional[int] = None
    obj: Optional[str] = None
    fixable: bool = False

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
        }


class Context:
    """Everything a rule may look at: parsed model(s) plus report folder(s).

    A Context is built from a user-supplied path (a PBIP project root, a
    ``*.SemanticModel`` folder, a ``definition`` folder or a ``*.Report``
    folder) and lazily parses each discovered model. ``reload()`` drops the
    parse cache — the engine calls it after fixers have rewritten files, so
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
