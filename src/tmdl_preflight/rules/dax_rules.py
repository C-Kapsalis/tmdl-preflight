"""DAX-side rules: delimiter balance, NAMEOF resolution, duplicate measure
names. IDs D0xx."""

from __future__ import annotations

from ..dax import check_balanced_delimiters, extract_nameof_references
from .base import Context, Rule, Severity, Violation


class DaxDelimiterBalanceRule(Rule):
    id = "D001"
    name = "dax-delimiters"
    severity = Severity.ERROR
    description = (
        "Every DAX expression in the model (measures, calculated columns, "
        "calculated-partition sources, calculation items, dynamic format "
        "strings) must have balanced parentheses, braces, brackets and "
        "quotes, with comments and string contents excluded."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for block in model.dax_blocks():
                for err in check_balanced_delimiters(block.expression):
                    out.append(
                        self.violation(
                            f"{err} in {block.kind} expression; the expression "
                            f"cannot be parsed until the delimiter is balanced. "
                            f"Add or remove the matching delimiter.",
                            file=block.file,
                            line=block.line,
                            obj=block.label,
                        )
                    )
        return out


class NameofResolutionRule(Rule):
    id = "D002"
    name = "nameof-resolution"
    severity = Severity.ERROR
    description = (
        "Every NAMEOF() reference must resolve: NAMEOF('Table'[Member]) to a "
        "column or measure on that table, NAMEOF([Measure]) to an existing, "
        "unambiguous measure. Field parameters are built from NAMEOF tuples, "
        "so a broken reference silently invalidates the whole parameter table."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for block in model.dax_blocks():
                for table, member, rel_line in extract_nameof_references(block.expression):
                    line = block.line + rel_line - 1
                    if table is None:
                        matches = model.find_measures(member)
                        if not matches:
                            out.append(
                                self.violation(
                                    f"NAMEOF([{member}]) does not resolve: the "
                                    f"model has no measure named '{member}'. "
                                    f"The measure was probably renamed or "
                                    f"removed; update or remove this reference, "
                                    f"because a broken NAMEOF invalidates the "
                                    f"whole expression it feeds.",
                                    file=block.file,
                                    line=line,
                                    obj=block.label,
                                )
                            )
                        elif len(matches) > 1:
                            tables = sorted(m.table for m in matches)
                            out.append(
                                self.violation(
                                    f"NAMEOF([{member}]) is ambiguous: a measure "
                                    f"named '{member}' is declared in more than "
                                    f"one table ({tables}). Resolve the "
                                    f"duplicate measure names (rule D003 reports "
                                    f"them) so the reference has a single target.",
                                    file=block.file,
                                    line=line,
                                    obj=block.label,
                                    severity=Severity.WARNING,
                                )
                            )
                        continue

                    t = model.get_table(table)
                    if t is None:
                        out.append(
                            self.violation(
                                f"NAMEOF('{table}'[{member}]) does not resolve: "
                                f"the model has no table named '{table}'. The "
                                f"table was probably renamed or removed; update "
                                f"this reference to the current table name.",
                                file=block.file,
                                line=line,
                                obj=block.label,
                            )
                        )
                        continue
                    if member in t.columns or member in t.measures:
                        # Fully-qualified references to measures are valid DAX;
                        # Power BI Desktop itself writes NAMEOF('T'[Measure])
                        # when building field parameters.
                        continue
                    out.append(
                        self.violation(
                            f"NAMEOF('{table}'[{member}]) does not resolve: "
                            f"table '{table}' has no column or measure named "
                            f"'{member}'. The field was probably renamed or "
                            f"removed; update this reference to the current name.",
                            file=block.file,
                            line=line,
                            obj=block.label,
                        )
                    )
        return out


class DuplicateMeasureNamesRule(Rule):
    id = "D003"
    name = "duplicate-measure-names"
    severity = Severity.ERROR
    description = (
        "Measure names must be unique across the whole model — the tabular "
        "engine enforces model-wide uniqueness, so two tables declaring the "
        "same measure name cannot deploy."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            by_name: dict[str, list] = {}
            for measure in model.all_measures():
                by_name.setdefault(measure.name, []).append(measure)
            for name, measures in sorted(by_name.items()):
                if len(measures) < 2:
                    continue
                first = measures[0]
                for dup in measures[1:]:
                    out.append(
                        self.violation(
                            f"measure '{name}' is also declared in table "
                            f"'{first.table}' ({first.file.name}:{first.line}). "
                            f"The tabular engine requires measure names to be "
                            f"unique across the whole model, so this model "
                            f"cannot deploy. Rename or remove one of the two.",
                            file=dup.file,
                            line=dup.line,
                            obj=dup.full_name,
                        )
                    )
        return out
