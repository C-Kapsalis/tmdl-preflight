"""Advisory model validation notes: the things the file validator said
without failing on them. ID M023."""

from __future__ import annotations

import re

from .base import Context, Rule, Severity, Violation

#: The summarizeBy values the tabular engine understands.
SUMMARIZE_BY_VALUES = (
    "none", "sum", "min", "max", "count", "distinctCount", "average",
    "standardDeviation", "variance",
)

#: The model properties Desktop always writes.
RECOMMENDED_MODEL_PROPERTIES = ("culture", "defaultPowerBIDataSourceVersion")

_DATA_TYPE_RE = re.compile(r"^\s*dataType\s*:", re.MULTILINE)
_SUMMARIZE_BY_RE = re.compile(r"^\s*summarizeBy\s*:\s*(\S+)", re.MULTILINE)
_PRECEDENCE_RE = re.compile(r"^\s*precedence\s*:", re.MULTILINE)
_COLUMN_DECL_RE = re.compile(r"^\s*column\s+(?:'[^']*'|\"[^\"]*\"|\S+)", re.MULTILINE)


class ModelValidationNotesRule(Rule):
    id = "M023"
    name = "model-validation-notes"
    severity = Severity.INFO
    opt_in = True
    description = (
        "The notes the file validator raised without failing on them: a model "
        "without a culture or a data source version, a quoted column without "
        "a dataType or with an unknown summarizeBy, a calculation group "
        "without a precedence, and a calculation item that uses neither "
        "SELECTEDMEASURE nor ISSELECTEDMEASURE. They are advice, not "
        "defects: a run never fails because of one."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            out.extend(self._model_notes(model))
            for table in model.table_list:
                out.extend(self._table_notes(table))
        return out

    def _model_notes(self, model) -> list[Violation]:
        out: list[Violation] = []
        mf = model.info.file
        if mf is None or not mf.is_file():
            return out
        try:
            text = mf.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return out
        for prop in RECOMMENDED_MODEL_PROPERTIES:
            if not re.search(rf"^\s*{prop}\s*:", text, re.MULTILINE):
                out.append(self.violation(
                    f"Missing recommended model property: {prop}. Power BI "
                    f"Desktop writes it in every model it saves.",
                    file=mf, obj=prop,
                ))
        return out

    def _table_notes(self, table) -> list[Violation]:
        out: list[Violation] = []
        try:
            text = table.file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return out
        for name, block in self._column_blocks(text):
            if not _DATA_TYPE_RE.search(block):
                out.append(self.violation(
                    f"Column '{name}' missing dataType. A column without one "
                    f"is read as a string.",
                    file=table.file, obj=name,
                ))
            m = _SUMMARIZE_BY_RE.search(block)
            if m and m.group(1) not in SUMMARIZE_BY_VALUES:
                out.append(self.violation(
                    f"Column '{name}' has unknown summarizeBy: {m.group(1)} "
                    f"(valid: {', '.join(SUMMARIZE_BY_VALUES)})",
                    file=table.file, obj=name,
                ))
        if table.is_calculation_group and not _PRECEDENCE_RE.search(text):
            out.append(self.violation(
                "Calculation group has no explicit precedence (defaults to 0). "
                "Give it one when the model holds more than one group.",
                file=table.file, obj=table.name,
            ))
        for name, expr, line in table.calculation_items:
            if "SELECTEDMEASURE" in expr.upper():
                continue
            if "ISSELECTEDMEASURE" in expr.upper():
                continue
            out.append(self.violation(
                "Calculation item should typically use SELECTEDMEASURE or "
                "ISSELECTEDMEASURE; an item that reads nothing from the "
                "selected measure returns the same value for every measure.",
                file=table.file, line=line, obj=name,
            ))
        return out

    @staticmethod
    def _column_blocks(text: str) -> list[tuple[str, str]]:
        """The name and the text of every column declaration in a file."""
        out = []
        matches = list(_COLUMN_DECL_RE.finditer(text))
        for idx, m in enumerate(matches):
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            name = m.group(0).strip().split(None, 1)[1].strip()
            if name[:1] in "'\"" and name[-1:] == name[:1]:
                name = name[1:-1]
            out.append((name, text[m.end():end]))
        return out
