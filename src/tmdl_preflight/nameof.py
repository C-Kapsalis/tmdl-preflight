"""NAMEOF extraction and resolution.

Field parameters and many dynamic-label measures are built from ``NAMEOF()``
calls; a renamed or removed target makes the whole expression (for a field
parameter, the whole calculated table) fail at processing time. This module
extracts every call with enough context to report it, and resolves it
against a parsed model. Rule D002 and ``tmdl-preflight report nameof`` are
built on it.

Accepted argument shapes (whitespace allowed between all tokens, function
name case-insensitive): ``'Table'[Member]`` (``''`` escapes a quote),
``"Table"[Member]``, ``Table[Member]`` (letters, digits, ``_`` and ``.``),
and the bare ``[Member]``. A member wrapped in single quotes inside the
brackets (``Sales['Amount']``) is unquoted. Comments are removed first, so a
parked row (``-- ("Old", NAMEOF([Old]), 3)``) is never a reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .dax import strip_comments
from .model import SemanticModel
from .rules.base import Severity

_CALL_RE = re.compile(r"\bNAMEOF\s*\(", re.IGNORECASE)
_ARG_RE = re.compile(
    r"""^\s*(?:
        '(?P<sq>(?:[^'"]|'')+)'      # 'Table'
      | "(?P<dq>[^"]+)"              # "Table"
      | (?P<bare>[A-Za-z0-9_.]+)     # Table
    )?\s*\[\s*(?P<member>(?:[^\]]|\]\])+?)\s*\]\s*$""",
    re.VERBOSE,
)


@dataclass
class NameofReference:
    """One NAMEOF call: where it sits (owner table and object, line text)
    and what it points at (table or None for a bare measure, member, the
    canonical full reference)."""

    source_table: str
    source_measure: str
    line_context: str
    object_name: str
    full_reference: str
    is_measure_ref: bool
    table_name: str | None = None
    line_number: int = 0
    file: Optional[Path] = None
    source_kind: str = "measure"
    valid_syntax: bool = True
    raw_argument: str = ""


@dataclass
class BrokenReference:
    reference: NameofReference
    severity: Severity
    reason: str
    casing: bool = False


def _argument_end(text: str, start: int) -> int:
    level = 1
    for pos in range(start, len(text)):
        level += {"(": 1, ")": -1}.get(text[pos], 0)
        if level == 0:
            return pos
    return len(text)


def _unquote_member(member: str) -> str:
    member = member.replace("]]", "]").strip()
    if len(member) >= 2 and member[0] == member[-1] == "'":
        member = member[1:-1].replace("''", "'").strip()
    return member


def parse_argument(arg: str) -> Optional[tuple[Optional[str], str]]:
    """``(table or None, member)`` for a NAMEOF argument, or None when the
    argument matches no accepted shape."""
    m = _ARG_RE.match(arg)
    if not m:
        return None
    if m.group("sq") is not None:
        table: Optional[str] = m.group("sq").replace("''", "'").strip()
    elif m.group("dq") is not None:
        table = m.group("dq").strip()
    else:
        table = m.group("bare")
    return table, _unquote_member(m.group("member"))


def extract(text: str, source_measure: str = "", source_table: str = "",
            first_line: int = 1, file: Optional[Path] = None,
            source_kind: str = "measure") -> list[NameofReference]:
    """Every NAMEOF call in ``text`` (comments removed), parseable or not."""
    clean = strip_comments(text)
    lines = text.splitlines() or [""]
    refs: list[NameofReference] = []
    for call in _CALL_RE.finditer(clean):
        end = _argument_end(clean, call.end())
        arg = clean[call.end():end]
        rel_line = clean.count("\n", 0, call.start())
        context = lines[rel_line].strip() if rel_line < len(lines) else ""
        parsed = parse_argument(arg)
        if parsed is None:
            refs.append(NameofReference(
                source_table=source_table, source_measure=source_measure, line_context=context,
                object_name=arg.strip(), full_reference=arg.strip(), is_measure_ref=False,
                line_number=first_line + rel_line, file=file, source_kind=source_kind,
                valid_syntax=False, raw_argument=arg,
            ))
            continue
        table, member = parsed
        full = f"{table}[{member}]" if table else f"[{member}]"
        refs.append(NameofReference(
            source_table=source_table, source_measure=source_measure, line_context=context,
            object_name=member, full_reference=full, is_measure_ref=table is None,
            table_name=table, line_number=first_line + rel_line, file=file,
            source_kind=source_kind, raw_argument=arg,
        ))
    return refs


class NameofResolver:
    """Find and validate NAMEOF references of one parsed model."""

    def __init__(self, model: SemanticModel, excluded_tables: Iterable[str] = (),
                 field_parameter_tables: Optional[Iterable[str]] = None):
        self.model = model
        self.excluded_tables = {t.lower() for t in excluded_tables}
        if field_parameter_tables is None:
            from .roles import is_field_parameter_table

            field_parameter_tables = [t.name for t in model.table_list if is_field_parameter_table(t)]
        self.field_parameter_tables = set(field_parameter_tables)

    # -- extraction ---------------------------------------------------------
    def find_nameof_in_expression(self, expression: str, source_measure: str,
                                  source_table: str) -> list[NameofReference]:
        return [r for r in extract(expression, source_measure, source_table) if r.valid_syntax]

    def find_all_nameof_references(self, measures_only: bool = True) -> list[NameofReference]:
        """References in measure expressions (``measures_only``) or in every
        DAX container of the model."""
        out: list[NameofReference] = []
        for block in self.model.dax_blocks():
            if measures_only and block.kind != "measure":
                continue
            refs = extract(block.expression, block.name, block.table, block.first_line,
                           block.file, block.kind)
            if measures_only:
                refs = [r for r in refs if r.valid_syntax]
            out.extend(refs)
        return out

    # -- resolution ---------------------------------------------------------
    def validate_references(self, refs: Iterable[NameofReference]) -> list[BrokenReference]:
        out: list[BrokenReference] = []
        for ref in refs:
            out.extend(self.validate(ref))
        return out

    def _in_field_parameter(self, ref: NameofReference) -> bool:
        return ref.source_kind == "partition_source" and ref.source_table in self.field_parameter_tables

    def validate(self, ref: NameofReference) -> list[BrokenReference]:
        model = self.model
        if not ref.valid_syntax:
            if self._in_field_parameter(ref):
                return [BrokenReference(ref, Severity.ERROR,
                                        f"invalid NAMEOF syntax: '{ref.raw_argument.strip()}' is "
                                        f"not a column or measure reference; target not found")]
            if not ref.object_name.strip("[]'\" "):
                return [BrokenReference(ref, Severity.ERROR, "Invalid reference format")]
            return []
        member = ref.object_name
        if ref.table_name is None:
            matches = model.find_measures_ci(member)
            if not matches:
                return [BrokenReference(ref, Severity.ERROR,
                                        f"Measure '{member}' not found in any table")]
            if len({m.table.lower() for m in matches}) > 1:
                tables = [m.table for m in matches]
                return [BrokenReference(ref, Severity.WARNING,
                                        f"Ambiguous: measure '{member}' exists in multiple "
                                        f"tables: {tables}")]
            if not any(m.name == member for m in matches):
                return [BrokenReference(ref, Severity.ERROR,
                                        f"casing mismatch: [{member}] is declared as "
                                        f"[{matches[0].name}]", casing=True)]
            return []
        tname = ref.table_name
        if tname.lower() in self.excluded_tables:
            return [BrokenReference(ref, Severity.ERROR,
                                    f"table '{tname}' is excluded from NAMEOF references; "
                                    f"a reference to it counts as not found")]
        table = model.find_table(tname)
        if table is None:
            return [BrokenReference(ref, Severity.ERROR, f"Table '{tname}' not found")]
        col = table.find_column(member)
        meas = table.find_measure(member) if col is None else None
        if col is None and meas is None:
            return [BrokenReference(ref, Severity.ERROR,
                                    f"Column '{member}' not found in table '{table.name}'")]
        out: list[BrokenReference] = []
        target = col or meas
        if table.name != tname or target.name != member:
            out.append(BrokenReference(
                ref, Severity.ERROR,
                f"casing mismatch: {ref.full_reference} is declared as "
                f"'{table.name}'[{target.name}]", casing=True,
            ))
        if meas is not None and not self._in_field_parameter(ref):
            out.append(BrokenReference(
                ref, Severity.WARNING,
                f"'{member}' is a measure, not a column. Use NAMEOF([{member}]) instead",
            ))
        return out


# ---------------------------------------------------------------------------
# Inventory (report nameof)
# ---------------------------------------------------------------------------

#: The two families of field-parameter tables, and the prefixes that name
#: them.
FAMILIES = (("x", ("x-Selector", "x-Plot Specific")), ("y", ("y-Selector", "y-Plot Specific")))


def statistics(refs: list[NameofReference]) -> dict:
    return {
        "total_references": len(refs),
        "measure_references": sum(1 for r in refs if r.is_measure_ref),
        "column_references": sum(1 for r in refs if not r.is_measure_ref),
        "unique_tables": len({r.table_name for r in refs if r.table_name}),
        "unique_objects": len({r.full_reference for r in refs}),
    }


def _kind(ref: NameofReference) -> int:
    """The order the references of one measure are listed in: the quoted-table
    columns first, then the unquoted-table ones, then the bare measures."""
    if ref.table_name is None:
        return 2
    return 0 if ref.raw_argument.strip().startswith("'") else 1


def sort_references(refs: list[NameofReference]) -> list[NameofReference]:
    """The references of one measure, by kind and then by position."""
    return sorted(refs, key=lambda r: (_kind(r), r.line_number))


def build_report(model: SemanticModel, prefixes: Optional[list[str]] = None) -> dict:
    """The reference inventory of one model: the statistics, the broken
    references and the two families of field-parameter tables.

    ``prefixes`` names the table-name prefixes of the families instead of
    the default ones.
    """
    resolver = NameofResolver(model)
    refs = resolver.find_all_nameof_references(measures_only=False)
    broken = resolver.validate_references(refs)
    broken.sort(key=lambda b: (b.severity != Severity.ERROR, b.reference.source_table,
                               b.reference.source_measure, _kind(b.reference),
                               b.reference.line_number))
    families: dict[str, dict] = {}
    for name, family_prefixes in FAMILIES:
        wanted = tuple(prefixes) if prefixes and name == "x" else family_prefixes
        tables = sorted(
            (t for t in model.table_list if t.name.startswith(wanted)),
            key=lambda t: t.name)
        entry: dict[str, dict] = {}
        for t in tables:
            own = [r for r in refs if r.source_table == t.name]
            own_broken = [b for b in broken if b.reference.source_table == t.name]
            entry[t.name] = {
                "columns": len(t.column_list),
                "measures": len(t.measure_list),
                "nameof_refs": len(own),
                "broken_refs": len(own_broken),
                "errors": sum(1 for b in own_broken if b.severity == Severity.ERROR),
                "warnings": sum(1 for b in own_broken if b.severity == Severity.WARNING),
                "samples": [f"{r.full_reference} (in {r.source_measure})"
                            for r in sort_references(own)[:3]],
            }
        families[name] = entry
    return {
        "statistics": statistics(refs),
        "broken": [
            {"source_table": b.reference.source_table, "source_measure": b.reference.source_measure,
             "reference": b.reference.full_reference, "severity": b.severity.value.upper(),
             "reason": b.reason, "line_context": b.reference.line_context[:80]}
            for b in broken
        ],
        "families": families,
    }


def render_validation(data: dict) -> str:
    """The validation block: the counts, then every broken reference with
    the reason it broke."""
    s = data["statistics"]
    lines = [
        "=" * 80,
        "NAMEOF REFERENCE VALIDATION REPORT",
        "=" * 80,
        "",
        f"Total References: {s['total_references']}",
        f"  Measure References: {s['measure_references']}",
        f"  Column References: {s['column_references']}",
        f"  Unique Tables: {s['unique_tables']}",
        f"  Unique Objects: {s['unique_objects']}",
        "",
    ]
    broken = data["broken"]
    if not broken:
        lines.append("✅ All references are valid!")
        lines.append("")
        lines.append("=" * 80)
        return "\n".join(lines)
    errors = [b for b in broken if b["severity"] == "ERROR"]
    warnings = [b for b in broken if b["severity"] != "ERROR"]
    lines.append(f"❌ Found {len(broken)} issues:")
    lines.append(f"   Errors: {len(errors)}")
    lines.append(f"   Warnings: {len(warnings)}")
    lines.append("")
    for label, group in (("ERRORS:", errors), ("WARNINGS:", warnings)):
        if not group:
            continue
        lines.append(label)
        lines.append("-" * 80)
        for b in group:
            lines += [
                f"[{b['severity']}] Broken reference in {b['source_table']}[{b['source_measure']}]:",
                f"  Reference: {b['reference']}",
                f"  Reason: {b['reason']}",
                f"  Context: {b['line_context']}...",
                "",
            ]
    lines.append("=" * 80)
    return "\n".join(lines)


def render_report(data: dict) -> str:
    """The validation block, then the two families of field-parameter
    tables and the summary."""
    lines = render_validation(data).splitlines()
    lines += [
        "",
        "=" * 80,
        "REPORT TABLE ANALYSIS",
        "=" * 80,
        "",
        "🔍 Parsing model...",
        "✅ Model parsed successfully",
        "",
        "📊 REPORT TABLES FOUND",
        "-" * 80,
    ]
    for name, label in (("x", "x-Selector"), ("y", "y-Selector")):
        tables = data.get("families", {}).get(name, {})
        lines.append(f"{label} tables: {len(tables)}")
        lines += [f"  • {table}" for table in tables]
        lines.append("")
    for name, label in (("x", "X-SELECTOR"), ("y", "Y-SELECTOR")):
        tables = data.get("families", {}).get(name, {})
        if not tables:
            continue
        lines += [
            "=" * 80,
            f"{label} TABLE ANALYSIS",
            "=" * 80,
            "",
        ]
        for table, row in tables.items():
            lines += [
                f"📋 {table}",
                "-" * 80,
                f"  Columns: {row['columns']}",
                f"  Measures: {row['measures']}",
                f"  NAMEOF references: {row['nameof_refs']}",
            ]
            if row["samples"]:
                lines.append("  Sample NAMEOF references:")
                lines += [f"    • {sample}" for sample in row["samples"]]
            lines.append(
                f"  Broken references: {row['broken_refs']} "
                f"(Errors: {row['errors']}, Warnings: {row['warnings']})")
            lines.append("")
    lines += [
        "=" * 80,
        "SUMMARY",
        "=" * 80,
        "",
    ]
    for name, label in (("x", "x-Selector"), ("y", "y-Selector")):
        tables = data.get("families", {}).get(name, {})
        if not tables:
            continue
        refs = sum(row["nameof_refs"] for row in tables.values())
        broken = sum(row["broken_refs"] for row in tables.values())
        lines += [
            f"{label} Tables:",
            f"  Total NAMEOF references: {refs}",
            f"  Total broken: {broken}",
            "",
        ]
    x = data.get("families", {}).get("x", {})
    y = data.get("families", {}).get("y", {})
    total_refs = (sum(row["nameof_refs"] for row in x.values())
                  + sum(row["nameof_refs"] for row in y.values()))
    total_broken = (sum(row["broken_refs"] for row in x.values())
                    + sum(row["broken_refs"] for row in y.values()))
    lines += [
        "Combined:",
        f"  Total NAMEOF references: {total_refs}",
        f"  Total broken: {total_broken}",
        "",
        "=" * 80,
        "✅ ANALYSIS COMPLETE",
        "=" * 80,
    ]
    return "\n".join(lines)
