"""Structural rules: model layout, TMDL well-formedness, lineage tags,
column data types. IDs M0xx."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from .base import Context, Rule, Severity, Violation

_CANONICAL_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_LINEAGE_LINE_RE = re.compile(r"^(\s*lineageTag:\s*)(\S+)(\s*)$")

VALID_DATA_TYPES = {
    "string",
    "int64",
    "double",
    "decimal",
    "dateTime",
    "boolean",
    "binary",
    "variant",
    "currency",
    "rowNumber",
}


class ModelStructureRule(Rule):
    id = "M001"
    name = "model-structure"
    severity = Severity.ERROR
    description = (
        "The definition folder must contain model.tmdl and a tables/ folder "
        "with at least one table file."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for d in ctx.definition_dirs:
            if not (d / "model.tmdl").is_file():
                out.append(
                    self.violation(
                        "model.tmdl is missing from this definition folder, so "
                        "the model cannot be opened or deployed. This usually "
                        "means a truncated export or a bad merge; restore the "
                        "file from source control or save the project again "
                        "from Power BI Desktop.",
                        file=d,
                    )
                )
            tables = d / "tables"
            if not tables.is_dir():
                out.append(
                    self.violation(
                        "the tables/ folder is missing, so the model defines "
                        "no tables. This usually means a truncated export or a "
                        "bad merge; restore the folder from source control or "
                        "save the project again from Power BI Desktop.",
                        file=d,
                    )
                )
            elif not any(tables.glob("*.tmdl")):
                out.append(
                    self.violation(
                        "the tables/ folder contains no .tmdl files, so the "
                        "model defines no tables. Restore the table files from "
                        "source control or save the project again from "
                        "Power BI Desktop.",
                        file=tables,
                    )
                )
        return out


class TmdlWellFormedRule(Rule):
    id = "M002"
    name = "tmdl-well-formed"
    severity = Severity.ERROR
    description = (
        "Every .tmdl file must be readable UTF-8, contain no null bytes, "
        "have paired ``` expression fences, and (for table files) declare a table."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for f in model.tmdl_files:
                try:
                    text = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError) as exc:
                    out.append(
                        self.violation(
                            f"cannot be read as UTF-8 ({exc}). TMDL files must "
                            f"be UTF-8 text; save the file again with UTF-8 "
                            f"encoding, or restore it from source control if "
                            f"it was corrupted.",
                            file=f,
                        )
                    )
                    continue
                if "\x00" in text:
                    line = text[: text.index("\x00")].count("\n") + 1
                    out.append(
                        self.violation(
                            "contains null bytes, which usually means the file "
                            "was truncated or corrupted during a merge or "
                            "copy. Restore the file from source control.",
                            file=f,
                            line=line,
                        )
                    )
                fences = text.count("```")
                if fences % 2 != 0:
                    out.append(
                        self.violation(
                            f"has unpaired expression fences ({fences} ``` "
                            f"markers; the count must be even). Everything "
                            f"after the unpaired fence is read as one "
                            f"expression; add or remove a fence so they pair up.",
                            file=f,
                        )
                    )
            for err in model.parse_errors:
                out.append(self.violation(err.message, file=err.file, line=err.line))
        return out


class _LineageRuleBase(Rule):
    """Shared machinery for the two lineage-tag rules: targeted, line-level
    rewriting that regenerates a tag without touching anything else."""

    @staticmethod
    def _rewrite_tag(file: Path, line_no: int) -> str | None:
        """Replace the lineageTag value on ``line_no`` (1-based) with a fresh
        UUID. Returns the new tag, or None if the line no longer matches."""
        text = file.read_text(encoding="utf-8")
        # Preserve the file's newline style.
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.split(newline) if newline in text else text.split("\n")
        if line_no - 1 >= len(lines):
            return None
        m = _LINEAGE_LINE_RE.match(lines[line_no - 1])
        if not m:
            return None
        new_tag = str(uuid.uuid4())
        lines[line_no - 1] = f"{m.group(1)}{new_tag}{m.group(3)}"
        file.write_text(newline.join(lines), encoding="utf-8", newline="")
        return new_tag


class LineageTagUniquenessRule(_LineageRuleBase):
    id = "M003"
    name = "lineage-duplicates"
    severity = Severity.ERROR
    fixable = True
    description = (
        "Every lineageTag in a model must be unique. Duplicates make the "
        "deployment target reject the model ('an object with that lineage "
        "tag already exists'). Auto-fix keeps the first occurrence and "
        "regenerates the rest."
    )

    def _duplicates(self, model) -> dict[str, list]:
        seen: dict[str, list] = {}
        for occ in model.lineage_tags:
            seen.setdefault(occ.tag, []).append(occ)
        return {t: occs for t, occs in seen.items() if len(occs) > 1}

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for tag, occs in self._duplicates(model).items():
                first = occs[0]
                for dup in occs[1:]:
                    out.append(
                        self.violation(
                            f"lineageTag '{tag}' duplicates the one on "
                            f"{first.context} ({first.file.name}:{first.line})",
                            file=dup.file,
                            line=dup.line,
                            obj=dup.context,
                        )
                    )
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for tag, occs in self._duplicates(model).items():
                # Keep the first (usually the original object); regenerate
                # each later occurrence.
                for dup in occs[1:]:
                    new_tag = self._rewrite_tag(dup.file, dup.line)
                    if new_tag:
                        applied.append(
                            f"{dup.file.name}:{dup.line} ({dup.context}): "
                            f"'{tag}' -> '{new_tag}'"
                        )
        return applied


class LineageTagFormatRule(_LineageRuleBase):
    id = "M004"
    name = "lineage-format"
    severity = Severity.WARNING
    fixable = True
    description = (
        "Every lineageTag must be a canonical hyphenated UUID "
        "(8-4-4-4-12 hex). Placeholder or hand-typed tags are replaced with "
        "fresh UUIDs by the auto-fix."
    )

    def _malformed(self, model):
        return [occ for occ in model.lineage_tags if not _CANONICAL_UUID_RE.match(occ.tag)]

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for occ in self._malformed(model):
                out.append(
                    self.violation(
                        f"lineageTag '{occ.tag}' is not a canonical UUID",
                        file=occ.file,
                        line=occ.line,
                        obj=occ.context,
                    )
                )
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for occ in self._malformed(model):
                new_tag = self._rewrite_tag(occ.file, occ.line)
                if new_tag:
                    applied.append(
                        f"{occ.file.name}:{occ.line} ({occ.context}): "
                        f"'{occ.tag}' -> '{new_tag}'"
                    )
        return applied


class ColumnDataTypeRule(Rule):
    id = "M005"
    name = "column-data-types"
    severity = Severity.WARNING
    description = (
        "Declared column dataType values must be one of the types the "
        "tabular engine understands (string, int64, double, decimal, "
        "dateTime, boolean, binary, variant, currency, rowNumber)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for table in model.tables.values():
                for col in table.columns.values():
                    if col.data_type and col.data_type not in VALID_DATA_TYPES:
                        out.append(
                            self.violation(
                                f"column dataType '{col.data_type}' is not a "
                                f"type the tabular engine accepts, so the "
                                f"model may fail to deploy. Change it to one "
                                f"of: string, int64, double, decimal, "
                                f"dateTime, boolean, binary, variant, "
                                f"currency, rowNumber.",
                                file=col.file,
                                line=col.line,
                                obj=col.full_name,
                            )
                        )
        return out
