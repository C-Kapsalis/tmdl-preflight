"""DAX-side rules: delimiter balance, NAMEOF resolution, duplicate measure
names, reference resolution, duplicate variables. IDs D0xx."""

from __future__ import annotations

import re

from ..dax import (
    DAX_KEYWORDS,
    check_balanced_delimiters,
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
    option_defaults = {"min_success_rate": 0.90}
    description = (
        "Every DAX expression in the model (measures, calculated columns, "
        "calculated-partition sources, calculation items, dynamic format "
        "strings) must have balanced parentheses, braces, brackets and "
        "quotes, with comments and string contents excluded. Each unbalanced "
        "expression is an error, and the message names the delimiter kind "
        "and the character position of the problem. The share of clean "
        "measure and calculated-column expressions is reported; below "
        "min_success_rate (default 0.90) one extra error says so. A model "
        "with no measures is an error: the model was probably not parsed."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        threshold = float(self.options.get("min_success_rate", 0.90))
        for model in ctx.models:
            counted = clean = 0
            for block in model.dax_blocks():
                errors = check_balanced_delimiters(block.expression)
                if block.kind in ("measure", "calculated_column") and block.expression:
                    counted += 1
                    clean += 0 if errors else 1
                for err in errors:
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
            share = clean / counted if counted else 1.0
            key = ctx.model_key(model)
            if counted:
                ctx.notes.append(
                    "DAX Validation Summary:\n"
                    f"   Total expressions: {counted}\n"
                    f"   Valid: {clean} ({share * 100:.1f}%)\n"
                    f"   Invalid: {counted - clean} "
                    f"({(counted - clean) / counted * 100:.1f}%)"
                )
            if clean < counted:
                ctx.notes.append(
                    f"D001: {key}: {clean} of {counted} measure/calculated-column "
                    f"expressions are balanced ({share:.1%})"
                )
            if share < threshold:
                out.append(self.violation(
                    f"parse success rate below threshold: {share:.1%} of measure and "
                    f"calculated-column expressions are balanced, under the configured "
                    f"{threshold:.0%}.",
                    file=model.definition_path, obj=key,
                ))
            if not any(True for _ in model.all_measures()):
                out.append(self.violation(
                    f"{key}: no measures found (suspicious)",
                    file=model.definition_path, obj=key,
                ))
        return out


class NameofResolutionRule(Rule):
    id = "D002"
    name = "nameof-resolution"
    severity = Severity.ERROR
    option_defaults = {"excluded_tables": []}
    description = (
        "Every NAMEOF() reference must resolve: NAMEOF('Table'[Member]) to a "
        "column or measure on that table, NAMEOF([Measure]) to an existing, "
        "unambiguous measure. Field parameters are built from NAMEOF tuples, "
        "so a broken reference invalidates the whole parameter table. An "
        "unparseable NAMEOF in a field-parameter row and a name that only "
        "matches with different casing are errors too; a table-qualified "
        "measure outside a field parameter and an ambiguous bare measure are "
        "warnings. Commented-out rows are never checked. 'excluded_tables' "
        "lists tables a reference must not point at."
    )

    def check(self, ctx: Context) -> list[Violation]:
        from ..nameof import NameofResolver

        out: list[Violation] = []
        for model in ctx.models:
            resolver = NameofResolver(model, self.options.get("excluded_tables") or [])
            refs = resolver.find_all_nameof_references(measures_only=False)
            for broken in resolver.validate_references(refs):
                ref = broken.reference
                label = f"{ref.source_table}[{ref.source_measure}] ({ref.source_kind})"
                call = f"NAMEOF({ref.raw_argument.strip()})"
                if broken.casing:
                    hint = "Spell the name exactly as it is declared."
                elif broken.severity == Severity.ERROR:
                    hint = ("The target was probably renamed or removed; update or park the "
                            "reference, because a broken NAMEOF invalidates the whole "
                            "expression it feeds.")
                else:
                    hint = ""
                out.append(self.violation(
                    f"{call}: {broken.reason}. {hint}".strip(),
                    file=ref.file, line=ref.line_number or None, obj=label,
                    severity=broken.severity,
                ))
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


_PROPERTY_LINE_RE = re.compile(
    r"^\s*(?:annotation|changedProperty|dataType|description|displayFolder|formatString|"
    r"isHidden|lineageTag|sortByColumn|summarizeBy)\b"
)
_ENUMERATION_LINE_RE = re.compile(r"^\s*ISFILTERED\(\s*'(?P<table>(?:[^']|'')+)'\s*\)\s*\|\|.*$")


def _drop_property_lines(expr: str) -> str:
    """Blank expression lines that are really TMDL property lines (a merge
    accident M010 reports); they never hold references."""
    return "\n".join("" if _PROPERTY_LINE_RE.match(ln) else ln for ln in expr.split("\n"))


class DaxReferenceResolutionRule(Rule):
    id = "D004"
    name = "dax-reference-resolution"
    severity = Severity.ERROR
    fixable = True
    safe = False
    option_defaults = {"check_bare_references": True, "fix_enumeration_lines": True}
    description = (
        "Every table and column a DAX expression names must exist: 'T'[c], "
        "T[c] and a bare 'T' must resolve to a table (and a column or "
        "measure on it). TMDL import does not check DAX names, so a renamed "
        "or deleted table imports cleanly and then fails on every visual that "
        "evaluates it ('Cannot find table'). A missing table or qualified "
        "column is an error, and so is a name spelled with different casing "
        "from its declaration. An unqualified [X] that matches no measure, no "
        "column and no name the expression itself introduces is a warning, "
        "as is one that names a measure declared in several tables. Auto "
        "date/time tables are always legal. The fixer (unsafe: it runs only "
        "when D004 is selected explicitly) deletes whole generated "
        "'ISFILTERED('<missing table>') || ...' lines and nothing else."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        check_bare = bool(self.options.get("check_bare_references", True))
        for model in ctx.models:
            measures_exact = {m.name for m in model.all_measures()}
            columns_exact = {c.name for c in model.all_columns()}
            measure_names = {m.name.lower() for m in model.all_measures()}
            measure_tables: dict[str, set] = {}
            for m in model.all_measures():
                measure_tables.setdefault(m.name.lower(), set()).add(m.table)
            column_names = {c.name.lower() for c in model.all_columns()}
            for block in model.dax_blocks():
                expr = _drop_property_lines(block.expression)
                refs = extract_references(expr)
                if not refs:
                    continue
                variables = variable_names(expr)
                introduced = {x.lower() for x in string_literals(expr)}
                seen: set[tuple] = set()

                def report(key, message, line, severity=None):
                    if key in seen:
                        return
                    seen.add(key)
                    out.append(self.violation(message, file=block.file, line=line,
                                              obj=block.label, severity=severity))

                for ref in refs:
                    line = block.first_line + ref.line - 1
                    if ref.kind == "bare" and ref.prev_word:
                        word = ref.prev_word
                        if word.upper() not in DAX_KEYWORDS and model.find_table(word) is not None:
                            ref.kind, ref.table = "column", word
                    if ref.kind in ("table", "column"):
                        name = ref.table or ""
                        if _is_virtual(name) or name.lower() in variables:
                            continue
                        table = model.find_table(name)
                        if table is None:
                            report(("table", name.lower()),
                                   f"DAX references table '{name}', which does not exist in "
                                   f"the model. The table was probably renamed or removed; the "
                                   f"model still imports, but every visual that evaluates this "
                                   f"expression fails. Update the reference or restore the table.",
                                   line)
                            continue
                        if table.name != name:
                            report(("table-case", name),
                                   f"casing mismatch: DAX writes table '{name}' but it is "
                                   f"declared as '{table.name}'. Spell the name exactly as "
                                   f"declared.", line)
                        if ref.kind == "table":
                            continue
                        member = ref.member or ""
                        target = table.find_column(member) or table.find_measure(member)
                        if target is not None:
                            if target.name != member:
                                report(("member-case", table.name.lower(), member),
                                       f"casing mismatch: DAX writes '{table.name}'[{member}] "
                                       f"but it is declared as [{target.name}]. Spell the name "
                                       f"exactly as declared.", line)
                            continue
                        if not table.column_list and any(
                            p.kind == "calculated" for p in table.partitions
                        ):
                            continue  # calculated table without declared columns
                        report(("column", name.lower(), member.lower()),
                               f"DAX references '{table.name}'[{member}], but table "
                               f"'{table.name}' has no column or measure named '{member}'. "
                               f"The field was probably renamed or removed; update the "
                               f"reference to the current name.", line)
                        continue
                    # bare [X]
                    if not check_bare:
                        continue
                    member = ref.member or ""
                    low = member.lower()
                    if low in variables or low in introduced:
                        continue
                    homes = measure_tables.get(low, set())
                    if len(homes) > 1:
                        report(("ambiguous", low),
                               f"[{member}] is ambiguous: a measure with that name is "
                               f"declared in {len(homes)} tables ({', '.join(sorted(homes))}). "
                               f"Rename the duplicates (D003 reports them) so the reference "
                               f"has one target.", line, Severity.WARNING)
                        continue
                    if low in measure_names and member not in measures_exact and \
                            member not in columns_exact and low not in column_names:
                        actual = next(m.name for m in model.all_measures() if m.name.lower() == low)
                        report(("bare-case", member),
                               f"casing mismatch: DAX writes [{member}] but the measure is "
                               f"declared as [{actual}]. Spell the name exactly as declared.",
                               line)
                        continue
                    if low in measure_names or low in column_names or _IMPLICIT_COLUMN_RE.match(low):
                        continue
                    report(("bare", low),
                           f"[{member}] matches no measure, no column and no column this "
                           f"expression introduces. It was probably renamed or removed; "
                           f"update the reference. If it names a column created inside the "
                           f"expression in a way the checker cannot follow, ignore this "
                           f"warning.", line, Severity.WARNING)
        return out

    def _missing_tables(self, ctx: Context) -> set[str]:
        prefix = "DAX references table '"
        names = set()
        for v in self.check(ctx):
            if v.message.startswith(prefix):
                names.add(v.message[len(prefix):].split("'", 1)[0])
        return names

    def fix(self, ctx: Context) -> list[str]:
        from ..edits import EditRefused, read_text_file, verified_write

        if not self.options.get("fix_enumeration_lines", True):
            return []
        missing = self._missing_tables(ctx)
        if not missing:
            return []
        applied: list[str] = []
        for model in ctx.models:
            for f in sorted((model.definition_path / "tables").glob("*.tmdl")):
                try:
                    original = read_text_file(f)
                except (OSError, UnicodeDecodeError):
                    continue
                lines = original.lines()
                kept, dropped = [], []
                for ln in lines:
                    m = _ENUMERATION_LINE_RE.match(ln)
                    if m and m.group("table").replace("''", "'") in missing:
                        dropped.append(ln)
                    else:
                        kept.append(ln)
                if not dropped:
                    continue

                def verify(old: str, new: str, _n=len(dropped)) -> None:
                    if len(old.split(original.newline)) - len(new.split(original.newline)) != _n:
                        raise EditRefused("enumeration-line repair changed more than whole lines")

                try:
                    if verified_write(original, original.join(kept), verify):
                        applied.append(
                            f"{f.name}: removed {len(dropped)} generated ISFILTERED line(s) "
                            f"naming a missing table"
                        )
                except EditRefused:
                    continue
        return applied


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
