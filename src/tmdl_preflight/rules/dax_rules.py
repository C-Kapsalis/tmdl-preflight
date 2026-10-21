"""DAX-side rules: delimiter balance, NAMEOF resolution, duplicate measure
names, reference resolution, duplicate variables. IDs D0xx."""

from __future__ import annotations

import re
from typing import Optional

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
                if ref.row_label:
                    label = f"{ref.source_table}['{ref.row_label}']"
                else:
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
    r"^\s*(?:annotation|changedProperty|contentType|dataCategory|dataType|description|"
    r"displayFolder|encodingHint|extendedProperty|formatString|isAvailableInMdx|"
    r"isDataTypeInferred|isHidden|isKey|isNullable|isUnique|lineageTag|mode|"
    r"queryGroup|relatedColumnDetails|sortByColumn|sourceColumn|sourceLineageTag|"
    r"summarizeBy)\b"
)
_ENUMERATION_LINE_RE = re.compile(r"^\s*ISFILTERED\(\s*'(?P<table>(?:[^']|'')+)'\s*\)\s*\|\|.*$")


def _drop_property_lines(expr: str) -> str:
    """Blank expression lines that are really TMDL property lines (a merge
    accident M010 reports); they never hold references."""
    return "\n".join("" if _PROPERTY_LINE_RE.match(ln) else ln for ln in expr.split("\n"))


#: The word each kind of DAX block is named by in a finding.
_BLOCK_KINDS = {
    "measure": "measure",
    "calculated_column": "column",
    "partition_source": "partition source",
    "calculation_item": "calculationItem",
    "format_string_definition": "formatStringDefinition",
}


def _block_kind(block) -> str:
    """The word a DAX block is named by in a finding."""
    return _BLOCK_KINDS.get(block.kind, block.kind)


def _block_object(block) -> str:
    """The object a DAX block is named by in a finding."""
    if block.kind in ("measure", "calculated_column", "calculation_item"):
        return f"{block.table}[{block.name}]"
    return block.table


def _split_declaration(head: str) -> tuple[str, str]:
    """``(the declaration up to and including '=', the inline expression)``."""
    quote: Optional[str] = None
    for i, ch in enumerate(head):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            continue
        if ch == "=":
            return head[: i + 1], head[i + 1:].strip()
    return head, ""


def _write_measure_expression(measure, expression: str) -> bool:
    """Write a new expression body into a measure's file.

    The declaration line keeps its name and its ``=``; the body follows on
    the next lines, indented like the rest of the file. The file's own
    newline style and byte-order mark are kept.
    """
    from ..edits import EditRefused, read_text_file, verified_write
    from ..recognizers import _expression_end

    tf = read_text_file(measure.file)
    lines = tf.lines()
    decl = measure.line - 1
    if decl < 0 or decl >= len(lines):
        return False
    head = lines[decl]
    prefix, _inline = _split_declaration(head)
    indent = head[: len(head) - len(head.lstrip())]
    end = _expression_end(lines, decl)
    body = [indent + "\t\t" + ln for ln in expression.split("\n")]
    new_lines = lines[:decl] + [prefix] + body + lines[end + 1:]

    def verify(old: str, new: str) -> None:
        if check_balanced_delimiters(expression):
            raise EditRefused("the regenerated expression is not balanced")
        old_parts = old.split(tf.newline)
        new_parts = new.split(tf.newline)
        tail = old_parts[end + 1:]
        if old_parts[:decl] != new_parts[:decl]:
            raise EditRefused("the repair changed the lines before the measure")
        if tail != new_parts[len(new_parts) - len(tail):]:
            raise EditRefused("the repair changed the lines after the measure")

    return verified_write(tf, tf.join(new_lines), verify)


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
        "evaluates it ('Cannot find table'). A missing table is one finding "
        "per object, naming every missing table that object uses; a missing "
        "qualified column is an error, and so is a name spelled with "
        "different casing from its declaration. An unqualified [X] that "
        "matches no measure, no column and no name the expression itself "
        "introduces is a warning, as is one that names a measure declared in "
        "several tables. Auto date/time tables are always legal. The fixer "
        "(unsafe: it runs only when D004 is selected explicitly) rebuilds "
        "the generated applied-filters measure, deletes whole generated "
        "'ISFILTERED('<missing table>') || ...' lines and nothing else."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        check_bare = bool(self.options.get("check_bare_references", True))
        dangling_models = 0
        for model in ctx.models:
            measures_exact = {m.name for m in model.all_measures()}
            columns_exact = {c.name for c in model.all_columns()}
            measure_names = {m.name.lower() for m in model.all_measures()}
            measure_tables: dict[str, set] = {}
            for m in model.all_measures():
                measure_tables.setdefault(m.name.lower(), set()).add(m.table)
            column_names = {c.name.lower() for c in model.all_columns()}
            objects = 0
            refs = 0
            for block in model.dax_blocks():
                expr = _drop_property_lines(block.expression)
                found = extract_references(expr)
                if not found:
                    continue
                variables = variable_names(expr)
                introduced = {x.lower() for x in string_literals(expr)}
                seen: set[tuple] = set()
                missing: dict[str, int] = {}

                def report(key, message, line, severity=None):
                    if key in seen:
                        return
                    seen.add(key)
                    out.append(self.violation(message, file=block.file, line=line,
                                              obj=block.label, severity=severity))

                for ref in found:
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
                            missing.setdefault(name, line)
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
                if missing:
                    objects += 1
                    refs += len(missing)
                    names = sorted(missing)
                    out.append(self.violation(
                        f"{_block_kind(block)} {_block_object(block)} -> missing "
                        f"{', '.join(repr(n) for n in names)}. The table was probably renamed "
                        f"or removed; the model still imports, but every visual that "
                        f"evaluates this expression fails. Update the reference or restore "
                        f"the table.",
                        file=block.file, line=missing[min(missing, key=missing.get)],
                        obj=block.label))
            if objects:
                dangling_models += 1
                ctx.notes.append(
                    f"DANGLING TABLE REFS ({objects} object(s), {refs} ref(s)): "
                    f"{ctx.scan_relative(model.definition_path) or model.definition_path}"
                )
        if dangling_models:
            ctx.notes.append(
                f"{dangling_models} model(s) with dangling DAX table references."
            )
        return out

    def _dangling(self, model) -> list:
        """``[(block, missing table names)]`` for one model.

        A block that names a table the model does not have is one object
        with one finding; the missing tables are sorted.
        """
        out: list = []
        for block in model.dax_blocks():
            expr = _drop_property_lines(block.expression)
            missing = []
            for ref in extract_references(expr):
                if ref.kind not in ("table", "column"):
                    continue
                name = ref.table or ""
                if _is_virtual(name):
                    continue
                if model.find_table(name) is None and name not in missing:
                    missing.append(name)
            if missing:
                out.append((block, sorted(missing)))
        return out

    def _rebuild_summary_measure(self, model) -> tuple[str, str]:
        """Rebuild the applied-filters summary measure from the y-axis tables.

        Returns ``("repaired", "")``, ``("failed", reason)`` or
        ``("error", reason)``.
        """
        from .. import ifilters
        from ..edits import EditRefused

        measure = next(
            (m for m in model.all_measures() if m.name == ifilters.SUMMARY_MEASURE), None
        )
        if measure is None:
            return "failed", f"{ifilters.SUMMARY_MEASURE} (regen failed)"
        dims = ifilters.dimensions(model)
        if not dims:
            return "failed", f"{ifilters.SUMMARY_MEASURE} (regen failed)"
        try:
            written = _write_measure_expression(measure, ifilters.generate_measure(dims))
        except EditRefused:
            return "failed", f"{ifilters.SUMMARY_MEASURE} (regen failed)"
        except Exception as exc:  # noqa: BLE001 - the reason goes in the report
            return "error", f"{ifilters.SUMMARY_MEASURE} (regen error: {exc})"
        if not written:
            return "failed", f"{ifilters.SUMMARY_MEASURE} (regen failed)"
        return "repaired", ""

    def fix(self, ctx: Context) -> list[str]:
        from ..edits import EditRefused, read_text_file, verified_write
        from ..parser import parse_model

        if not self.options.get("fix_enumeration_lines", True):
            return []
        applied: list[str] = []
        for model in ctx.models:
            dangling = self._dangling(model)
            if not dangling:
                continue
            dead = {name for _block, names in dangling for name in names}
            groups = 0
            unfixable: list[str] = []
            if any(
                block.kind == "measure" and block.name == "i-Applied Filters"
                for block, _names in dangling
            ):
                status, reason = self._rebuild_summary_measure(model)
                if status == "repaired":
                    groups += 1
                else:
                    unfixable.append(reason)
            for f in sorted((model.definition_path / "tables").glob("*.tmdl")):
                try:
                    original = read_text_file(f)
                except (OSError, UnicodeDecodeError):
                    continue
                lines = original.lines()
                kept, dropped = [], []
                for ln in lines:
                    m = _ENUMERATION_LINE_RE.match(ln)
                    if m and m.group("table").replace("''", "'") in dead:
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
                        groups += 1
                        applied.append(
                            f"{f.name}: removed {len(dropped)} generated ISFILTERED line(s) "
                            f"naming a missing table"
                        )
                except EditRefused:
                    continue
            applied.append(f"repaired {groups} site-group(s)")
            fresh = parse_model(model.definition_path)
            for block, names in self._dangling(fresh):
                if block.kind == "measure" and block.name == "i-Applied Filters":
                    continue
                unfixable.append(
                    f"NOT auto-fixable: {_block_object(block)} -> {', '.join(names)}"
                )
            applied.extend(unfixable)
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
