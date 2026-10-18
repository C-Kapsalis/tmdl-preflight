"""DAX-side rules: delimiter balance, NAMEOF resolution, duplicate measure
names, reference resolution, duplicate variables. IDs D0xx."""

from __future__ import annotations

import re

from ..dax import (
    DAX_KEYWORDS,
    check_balanced_delimiters,
    extract_nameof_references,
    extract_references,
    find_outer_scope_duplicate_vars,
    string_literals,
    variable_names,
)
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
                    line = block.first_line + rel_line - 1
                    if table is None:
                        matches = model.find_measures_ci(member)
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

                    t = model.find_table(table)
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
                    if t.find_column(member) or t.find_measure(member):
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
        "Measure names must be unique across the whole model: the tabular "
        "engine enforces model-wide uniqueness (case-insensitively), so two "
        "tables declaring the same measure name cannot deploy. Duplicates "
        "inside one table are reported by M012."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            by_name: dict[str, list] = {}
            for measure in model.all_measures():
                by_name.setdefault(measure.name.lower(), []).append(measure)
            for _key, measures in sorted(by_name.items()):
                if len(measures) < 2:
                    continue
                first = measures[0]
                for dup in measures[1:]:
                    if dup.table.lower() == first.table.lower():
                        continue  # same table: M012 reports it
                    name = dup.name
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


# Virtual tables the engine materializes for auto date/time; DAX may name
# them even though no tables/*.tmdl file declares them.
_VIRTUAL_TABLE_PREFIXES = ("DateTableTemplate_", "LocalDateTable_")
# Columns every table constructor, GENERATESERIES and CALENDAR produce.
_IMPLICIT_COLUMN_RE = re.compile(r"^(?:Value\d*|Date)$", re.IGNORECASE)


def _is_virtual(name: str) -> bool:
    return name.startswith(_VIRTUAL_TABLE_PREFIXES)


class DaxReferenceResolutionRule(Rule):
    id = "D004"
    name = "dax-reference-resolution"
    severity = Severity.ERROR
    option_defaults = {"check_bare_references": True}
    description = (
        "Every table and column a DAX expression names must exist: 'T'[c], "
        "T[c] and a bare 'T' must resolve to a table (and a column or "
        "measure on it), case-insensitively. TMDL import does not check DAX "
        "names, so a renamed or deleted table imports cleanly and then fails "
        "on every visual that evaluates it ('Cannot find table'). A missing "
        "table or qualified column is an error. An unqualified [X] that "
        "matches no measure, no column and no name the expression itself "
        "introduces (ADDCOLUMNS, SELECTCOLUMNS, SUMMARIZECOLUMNS and similar "
        "name new columns with string literals) is a warning. Auto date/time "
        "tables (DateTableTemplate_*, LocalDateTable_*) are always legal."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        check_bare = bool(self.options.get("check_bare_references", True))
        for model in ctx.models:
            measure_names = {m.name.lower() for m in model.all_measures()}
            measure_tables: dict[str, set] = {}
            for m in model.all_measures():
                measure_tables.setdefault(m.name.lower(), set()).add(m.table)
            column_names = {c.name.lower() for c in model.all_columns()}
            for block in model.dax_blocks():
                expr = block.expression
                refs = extract_references(expr)
                if not refs:
                    continue
                variables = variable_names(expr)
                introduced = {s.lower() for s in string_literals(expr)}
                seen: set[tuple] = set()
                for ref in refs:
                    line = block.first_line + ref.line - 1
                    if ref.kind == "bare" and ref.prev_word:
                        word = ref.prev_word
                        if (
                            word.upper() not in DAX_KEYWORDS
                            and model.find_table(word) is not None
                        ):
                            ref.kind, ref.table = "column", word
                    if ref.kind in ("table", "column"):
                        name = ref.table or ""
                        if _is_virtual(name) or name.lower() in variables:
                            continue
                        table = model.find_table(name)
                        if table is None:
                            key = ("table", name.lower())
                            if key in seen:
                                continue
                            seen.add(key)
                            out.append(
                                self.violation(
                                    f"DAX references table '{name}', which does "
                                    f"not exist in the model. The table was "
                                    f"probably renamed or removed; the model "
                                    f"still imports, but every visual that "
                                    f"evaluates this expression fails. Update "
                                    f"the reference or restore the table.",
                                    file=block.file,
                                    line=line,
                                    obj=block.label,
                                )
                            )
                            continue
                        if ref.kind == "table":
                            continue
                        member = ref.member or ""
                        if table.find_column(member) or table.find_measure(member):
                            continue
                        if not table.column_list and any(
                            p.kind == "calculated" for p in table.partitions
                        ):
                            continue  # calculated table without declared columns
                        key = ("column", name.lower(), member.lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(
                            self.violation(
                                f"DAX references '{table.name}'[{member}], but "
                                f"table '{table.name}' has no column or measure "
                                f"named '{member}'. The field was probably "
                                f"renamed or removed; update the reference to "
                                f"the current name.",
                                file=block.file,
                                line=line,
                                obj=block.label,
                            )
                        )
                        continue
                    # bare [X]
                    if not check_bare:
                        continue
                    low = (ref.member or "").lower()
                    homes = measure_tables.get(low, set())
                    if len(homes) > 1 and low not in variables and low not in introduced:
                        key = ("ambiguous", low)
                        if key not in seen:
                            seen.add(key)
                            out.append(
                                self.violation(
                                    f"[{ref.member}] is ambiguous: a measure with "
                                    f"that name is declared in {len(homes)} tables "
                                    f"({', '.join(sorted(homes))}). Rename the "
                                    f"duplicates (D003 reports them) so the "
                                    f"reference has one target.",
                                    file=block.file,
                                    line=line,
                                    obj=block.label,
                                    severity=Severity.WARNING,
                                )
                            )
                        continue
                    if (
                        low in measure_names
                        or low in column_names
                        or low in introduced
                        or low in variables
                        or _IMPLICIT_COLUMN_RE.match(low)
                    ):
                        continue
                    key = ("bare", low)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        self.violation(
                            f"[{ref.member}] matches no measure, no column and "
                            f"no column this expression introduces. It was "
                            f"probably renamed or removed; update the "
                            f"reference. If it names a column created inside "
                            f"the expression in a way the checker cannot "
                            f"follow, ignore this warning.",
                            file=block.file,
                            line=line,
                            obj=block.label,
                            severity=Severity.WARNING,
                        )
                    )
        return out


class DuplicateVariableRule(Rule):
    id = "D005"
    name = "duplicate-var-in-scope"
    severity = Severity.ERROR
    description = (
        "A DAX variable name must be unique within its scope. Declaring the "
        "same VAR twice at the outer level of an expression (a common merge "
        "accident) makes it fail on evaluation ('a table or variable with "
        "the same name already exists'). The same name inside separate "
        "nested sub-expressions is legal and is not reported."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for block in model.dax_blocks():
                for name, rel_line in find_outer_scope_duplicate_vars(block.expression):
                    out.append(
                        self.violation(
                            f"VAR '{name}' is declared twice in the same scope, "
                            f"so the expression fails on evaluation. Rename "
                            f"or remove one of the declarations.",
                            file=block.file,
                            line=block.first_line + rel_line - 1,
                            obj=block.label,
                        )
                    )
        return out
