"""Structural rules: model layout, TMDL well-formedness, lineage tags,
column data types. IDs M0xx."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from .base import Context, Rule, Severity, Violation
from ..dax import CODE, classify
from ..edits import EditRefused, read_text_file, verified_write
from ..parser import indent_level, parse_object_name
from ..recognizers import (
    find_dangling_descriptions,
    find_properties_after_child_blocks,
    leaked_property,
    move_properties_before_child_blocks,
    remove_dangling_descriptions,
)

_REF_TABLE_RE = re.compile(r"^\s*ref\s+table\s+(?P<rest>.+?)\s*$")

# An inline ``#table(type table [...], {...})`` M source is an *entity-typed*
# query source. Combined with any calculated table, Power BI classifies the
# model as composite and refuses to open it ("A composite model cannot be used
# with entity based query sources"). The entered-data pattern
# (``Table.FromRows(Json.Document(Binary.Decompress(...)))``) or a calculated
# table are the safe alternatives.
_ENTITY_TABLE_RE = re.compile(r"#table\s*\(\s*type\s+table", re.IGNORECASE)


def _render_table_ref(name: str) -> str:
    """Render a table name for a ``ref table`` line, quoting when needed."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return "'" + name.replace("'", "''") + "'"

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
        "Every .tmdl file must be readable UTF-8 (a byte-order mark is fine), "
        "contain no null bytes, have paired ``` expression fences, and (for "
        "table files) declare a table. Every column, measure and relationship "
        "declaration line must also be attached to the model; a mis-indented "
        "declaration the parser cannot place is reported here instead of "
        "being dropped silently."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for f in model.tmdl_files:
                try:
                    text = f.read_text(encoding="utf-8-sig")
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
        original = read_text_file(file)
        lines = original.lines()
        if line_no - 1 >= len(lines):
            return None
        m = _LINEAGE_LINE_RE.match(lines[line_no - 1])
        if not m:
            return None
        new_tag = str(uuid.uuid4())
        lines[line_no - 1] = f"{m.group(1)}{new_tag}{m.group(3)}"

        def verify(old: str, new: str) -> None:
            old_l, new_l = old.split(original.newline), new.split(original.newline)
            changed = [k for k, (a, b) in enumerate(zip(old_l, new_l)) if a != b]
            if len(old_l) != len(new_l) or changed != [line_no - 1]:
                raise EditRefused("lineage tag rewrite touched other lines")

        try:
            verified_write(original, original.join(lines), verify)
        except EditRefused:
            return None
        return new_tag


class LineageTagUniquenessRule(_LineageRuleBase):
    id = "M003"
    name = "lineage-duplicates"
    severity = Severity.ERROR
    fixable = True
    baselinable = False
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


def _model_file(model) -> Path:
    return model.definition_path / "model.tmdl"


def _referenced_tables(model_file: Path) -> set[str] | None:
    """Names declared with ``ref table`` in model.tmdl, or None if unreadable."""
    try:
        text = model_file.read_text(encoding="utf-8-sig")
    except (UnicodeDecodeError, OSError):
        return None
    refs: set[str] = set()
    for line in text.splitlines():
        m = _REF_TABLE_RE.match(line)
        if m:
            name, _ = parse_object_name(m.group("rest"))
            refs.add(name)
    return refs


class ModelTableReferencesRule(Rule):
    id = "M006"
    name = "model-table-refs"
    severity = Severity.ERROR
    fixable = True
    baselinable = False
    description = (
        "Every table defined under tables/ must be linked to the model with a "
        "'ref table <name>' line in model.tmdl. A table file with no matching "
        "ref is not attached to the model, so Power BI Desktop refuses to open "
        "the project (the report never loads). This happens when a table is "
        "added by hand or a merge drops the ref line. Auto-fix appends the "
        "missing 'ref table' lines to model.tmdl."
    )

    def _missing(self, model) -> list[str]:
        mf = _model_file(model)
        if not mf.is_file():
            return []  # M001 reports a missing model.tmdl
        refs = _referenced_tables(mf)
        if refs is None:
            return []
        return [name for name in model.tables if name not in refs]

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for name in self._missing(model):
                table = model.tables[name]
                out.append(
                    self.violation(
                        f"table '{name}' is defined in tables/ but has no "
                        f"'ref table' line in model.tmdl, so it is not part of "
                        f"the model and Power BI will not open the project. "
                        f"Add: ref table {_render_table_ref(name)}",
                        file=table.file,
                        obj=name,
                    )
                )
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            missing = self._missing(model)
            if not missing:
                continue
            mf = _model_file(model)
            original = read_text_file(mf)
            newline = original.newline
            body = original.text.rstrip("\r\n")
            additions = newline.join(
                f"ref table {_render_table_ref(name)}" for name in missing
            )
            try:
                verified_write(original, body + newline + newline + additions + newline)
            except EditRefused:
                continue
            applied.extend(f"model.tmdl: + ref table {_render_table_ref(n)}" for n in missing)
        return applied


class TablePartitionPresenceRule(Rule):
    id = "M007"
    name = "table-partitions"
    severity = Severity.ERROR
    baselinable = False
    description = (
        "Every table must declare at least one partition. A measures-only "
        "table ('measures table') still needs one: without a partition Power "
        "BI Desktop cannot map the table to a query and crashes on open "
        "('Sequence contains no elements' in GetLinkedQuery). Give it a "
        "calculated partition or a dummy entered-data partition "
        "(Table.FromRows(...) then Table.RemoveColumns)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in model.tables.values():
                if not t.partitions:
                    out.append(
                        self.violation(
                            f"table '{t.name}' has no partition, so Power BI "
                            f"cannot map it to a query and crashes on open. "
                            f"Measures-only tables still need a partition (a "
                            f"calculated one, or a dummy entered-data partition).",
                            file=t.file,
                            obj=t.name,
                        )
                    )
        return out


class EntityQuerySourceRule(Rule):
    id = "M008"
    name = "entity-query-source"
    severity = Severity.ERROR
    description = (
        "An M partition whose source is an inline '#table(type table [...])' is "
        "an entity-typed query source. Combined with any calculated table, "
        "Power BI treats the model as composite and refuses to open it "
        "('A composite model cannot be used with entity based query sources'). "
        "Re-encode manual data as entered data "
        "(Table.FromRows(Json.Document(Binary.Decompress(...)))) or use a "
        "calculated table."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in model.tables.values():
                for p in t.partitions:
                    if p.kind == "m" and p.source and _ENTITY_TABLE_RE.search(p.source):
                        out.append(
                            self.violation(
                                f"table '{t.name}' uses an inline "
                                f"'#table(type table ...)' entity source, which "
                                f"forces a composite model and blocks open. "
                                f"Re-encode as entered data "
                                f"(Table.FromRows(Json.Document(...))) or make it "
                                f"a calculated table.",
                                file=p.file,
                                line=p.source_start_line or p.line,
                                obj=t.name,
                            )
                        )
        return out


# Table names Power BI rejects outright ("Unsupported Table name '<n>' has
# been found in data model schema"). "Measures" collides with the implicit
# measures container. Compared case-insensitively.
_RESERVED_TABLE_NAMES = {"measures"}


class ReservedTableNameRule(Rule):
    id = "M009"
    name = "reserved-table-name"
    severity = Severity.ERROR
    description = (
        "Power BI reserves certain table names and refuses to open a model "
        "that uses one, most notably a table literally named 'Measures', "
        "which collides with the implicit measures container ('Unsupported "
        "Table name ... found in data model schema'). Rename the table, for "
        "example to 'Key Measures' or '<Domain> Measures'."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in model.tables.values():
                if t.name.strip().lower() in _RESERVED_TABLE_NAMES:
                    out.append(
                        self.violation(
                            f"table '{t.name}' uses a name Power BI reserves, "
                            f"so Power BI Desktop refuses to open the project "
                            f"('Unsupported Table name'). Rename it, for example "
                            f"to 'Key Measures' or '<Domain> Measures'.",
                            file=t.file,
                            obj=t.name,
                        )
                    )
        return out



# ---------------------------------------------------------------------------
# M010-M015
# ---------------------------------------------------------------------------


def _file_lines(cache: dict, path: Path) -> list[str]:
    if path not in cache:
        try:
            cache[path] = path.read_text(encoding="utf-8-sig").splitlines()
        except (UnicodeDecodeError, OSError):
            cache[path] = []
    return cache[path]


def _expression_owners(model):
    """(label, obj, file, decl_line, expression, start_line) for every object
    that carries an expression, DAX or M."""
    for t in model.table_list:
        for m in t.measure_list:
            yield f"{t.name}[{m.name}] (measure)", m, m.file, m.line, m.expression, m.expression_line
        for c in t.column_list:
            if c.expression is not None:
                yield (
                    f"{t.name}[{c.name}] (calculated_column)", c, c.file, c.line,
                    c.expression, c.expression_line,
                )
        for p in t.partitions:
            if p.source:
                yield (
                    f"{t.name} (partition {p.name})", p, p.file, p.line, p.source,
                    p.source_start_line,
                )
        for k, (name, expr, line) in enumerate(t.calculation_items):
            start = t.calculation_item_starts[k] if k < len(t.calculation_item_starts) else None
            yield f"{t.name}[{name}] (calculation_item)", None, t.file, line, expr, start


class MetadataInExpressionRule(Rule):
    id = "M010"
    name = "metadata-in-expression"
    severity = Severity.ERROR
    baselinable = False
    description = (
        "A TMDL property line (lineageTag:, formatString:, displayFolder:, "
        "isHidden, annotation ...) must never sit inside an expression body. "
        "It happens when a script or a merge inserts a property at the wrong "
        "indentation, or inside a ``` fence: the property becomes part of the "
        "DAX or M text and Power BI rejects the file ('... is neither a "
        "property nor an object in the current context'). Move the line out "
        "of the expression, one level under the object's declaration."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        cache: dict = {}
        for model in ctx.models:
            for label, obj, file, decl_line, expr, start in _expression_owners(model):
                if expr:
                    tags = classify(expr)
                    offset = 0
                    for rel, ln in enumerate(expr.split("\n")):
                        body = ln.lstrip()
                        first = offset + (len(ln) - len(body))
                        offset += len(ln) + 1
                        if not body or body.startswith("```"):
                            continue
                        if first < len(tags) and tags[first] != CODE:
                            continue  # inside a string or comment
                        token = leaked_property(body)
                        if token:
                            out.append(
                                self.violation(
                                    f"TMDL property '{token}' is inside the "
                                    f"expression body, so it is read as part "
                                    f"of the expression and Power BI rejects "
                                    f"the file. Move it out of the expression, "
                                    f"one level under the declaration.",
                                    file=file,
                                    line=(start or decl_line) + rel,
                                    obj=label,
                                )
                            )
                    continue
                # empty expression after '=': is a property sitting where the
                # expression should be?
                lines = _file_lines(cache, file)
                if not lines or decl_line - 1 >= len(lines):
                    continue
                decl = lines[decl_line - 1]
                if not decl.rstrip().endswith("="):
                    continue
                for j in range(decl_line, len(lines)):
                    nxt = lines[j]
                    if not nxt.strip():
                        continue
                    token = leaked_property(nxt)
                    if token and indent_level(nxt) <= indent_level(decl) + 1:
                        out.append(
                            self.violation(
                                f"the expression after '=' is missing and the "
                                f"TMDL property '{token}' sits where it should "
                                f"be, so Power BI rejects the file. Put the "
                                f"expression back right after '=' and keep "
                                f"properties below it.",
                                file=file,
                                line=j + 1,
                                obj=label,
                            )
                        )
                    break
        return out


class PropertyAfterChildBlockRule(Rule):
    id = "M011"
    name = "property-after-child-block"
    severity = Severity.WARNING
    fixable = True
    description = (
        "An object's simple properties (isHidden, displayFolder, "
        "formatString, lineageTag ...) must come before its child blocks "
        "(annotation, changedProperty, extendedProperty). Power BI Desktop "
        "always writes them in that order; a property appended after an "
        "annotation, usually by a script, is at best ignored and at worst "
        "rejected when the file is opened. Auto-fix moves the line up into "
        "the object's property section."
    )

    def _files(self, ctx: Context):
        for model in ctx.models:
            yield from model.tmdl_files

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for f in self._files(ctx):
            try:
                lines = f.read_text(encoding="utf-8-sig").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for finding in find_properties_after_child_blocks(lines):
                out.append(
                    self.violation(
                        f"property '{finding.token}' comes after a child block "
                        f"(annotation, changedProperty or extendedProperty) of "
                        f"'{finding.owner}'. Properties must precede child "
                        f"blocks; move the line up (the auto-fix does this).",
                        file=f,
                        line=finding.line + 1,
                        obj=finding.owner,
                    )
                )
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for f in self._files(ctx):
            try:
                original = read_text_file(f)
            except (UnicodeDecodeError, OSError):
                continue
            lines = original.lines()
            new_lines, moved = move_properties_before_child_blocks(lines)
            if not moved:
                continue

            def verify(old: str, new: str) -> None:
                old_l = [ln for ln in old.split(original.newline) if ln.strip()]
                new_l = [ln for ln in new.split(original.newline) if ln.strip()]
                if sorted(old_l) != sorted(new_l):
                    raise EditRefused("moving properties changed other lines")
                if find_properties_after_child_blocks(new.split(original.newline)):
                    raise EditRefused("properties are still out of order")

            try:
                if verified_write(original, original.join(new_lines), verify):
                    applied.append(f"{f.name}: moved {moved} property line(s) above child blocks")
            except EditRefused:
                continue
        return applied


class DuplicateObjectNamesRule(Rule):
    id = "M012"
    name = "duplicate-object-names"
    severity = Severity.ERROR
    description = (
        "Object names are compared case-insensitively by the tabular engine. "
        "Two tables whose names differ only by case, two columns or two "
        "measures with the same name in one table, or a measure named like a "
        "column of its own table all make the model fail to load. Rename one "
        "of the pair."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            seen_tables: dict[str, object] = {}
            for t in model.table_list:
                key = t.name.lower()
                if key in seen_tables:
                    first = seen_tables[key]
                    out.append(
                        self.violation(
                            f"table '{t.name}' duplicates table '{first.name}' "
                            f"({first.file.name}); table names are "
                            f"case-insensitive, so the model cannot load. "
                            f"Rename or remove one of the two files.",
                            file=t.file,
                            line=t.line,
                            obj=t.name,
                        )
                    )
                else:
                    seen_tables[key] = t
            for t in model.table_list:
                for kind, items in (("column", t.column_list), ("measure", t.measure_list)):
                    seen: dict[str, object] = {}
                    for item in items:
                        key = item.name.lower()
                        if key in seen:
                            first = seen[key]
                            out.append(
                                self.violation(
                                    f"{kind} '{item.name}' is declared twice in "
                                    f"table '{t.name}' (first at line "
                                    f"{first.line}); names are case-insensitive, "
                                    f"so the model cannot load. Rename or remove "
                                    f"one of the two.",
                                    file=item.file,
                                    line=item.line,
                                    obj=item.full_name,
                                )
                            )
                        else:
                            seen[key] = item
                columns = {c.name.lower(): c for c in t.column_list}
                for meas in t.measure_list:
                    col = columns.get(meas.name.lower())
                    if col is not None:
                        out.append(
                            self.violation(
                                f"measure '{meas.name}' has the same name as "
                                f"column '{col.name}' of its own table (line "
                                f"{col.line}), so references to it are "
                                f"ambiguous and the model cannot load. Rename "
                                f"the measure or the column.",
                                file=meas.file,
                                line=meas.line,
                                obj=meas.full_name,
                            )
                        )
        return out


class DanglingDescriptionRule(Rule):
    id = "M013"
    name = "dangling-description"
    severity = Severity.ERROR
    fixable = True
    description = (
        "A /// description must sit directly on top of the declaration it "
        "describes. A /// run followed by a blank line documents nothing, and "
        "Power BI rejects the file once any declaration follows it "
        "('Unexpected line type: Empty'). At the end of a file it is harmless "
        "until something is appended, so it is reported as a warning there. "
        "Auto-fix deletes the orphaned run and the blank line next to it."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for f in model.tmdl_files:
                try:
                    lines = f.read_text(encoding="utf-8-sig").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue
                for d in find_dangling_descriptions(lines):
                    if d.at_eof:
                        out.append(
                            self.violation(
                                "/// description at the end of the file "
                                "describes nothing. It is harmless today, but "
                                "anything appended after it turns it into an "
                                "import error; delete it (the auto-fix does).",
                                file=f,
                                line=d.end + 1,
                                severity=Severity.WARNING,
                            )
                        )
                    else:
                        out.append(
                            self.violation(
                                "/// description is followed by a blank line "
                                "instead of the declaration it describes, so "
                                "Power BI rejects the file ('Unexpected line "
                                "type: Empty'). Remove the blank line to "
                                "attach it, or delete the description.",
                                file=f,
                                line=d.end + 1,
                            )
                        )
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for f in model.tmdl_files:
                try:
                    original = read_text_file(f)
                except (UnicodeDecodeError, OSError):
                    continue
                lines = original.lines()
                new_lines, removed = remove_dangling_descriptions(lines)
                if not removed:
                    continue

                def verify(old: str, new: str) -> None:
                    old_l = old.split(original.newline)
                    new_l = new.split(original.newline)
                    if find_dangling_descriptions(new_l):
                        raise EditRefused("dangling descriptions remain")
                    # every surviving line must come from the original, in order
                    it = iter(old_l)
                    if not all(any(ln == o for o in it) for ln in new_l):
                        raise EditRefused("edit changed lines it should only delete")
                    gone = [ln for ln in old_l if ln.strip() and ln not in new_l]
                    if any(not ln.lstrip().startswith("///") for ln in gone):
                        raise EditRefused("edit deleted a non-description line")

                try:
                    if verified_write(original, original.join(new_lines), verify):
                        applied.append(
                            f"{f.name}: removed {removed} dangling /// description run(s)"
                        )
                except EditRefused:
                    continue
        return applied


class CalcGroupImplicitMeasuresRule(Rule):
    id = "M014"
    name = "calc-group-implicit-measures"
    severity = Severity.ERROR
    description = (
        "A model with a calculation group must set discourageImplicitMeasures "
        "in model.tmdl. Calculation groups only apply to explicit measures, "
        "so Power BI refuses to save or deploy a model that has both a "
        "calculation group and implicit measures enabled. Add a "
        "'discourageImplicitMeasures' line under 'model Model'."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            groups = [t for t in model.table_list if t.is_calculation_group]
            if not groups or model.info.discourage_implicit_measures:
                continue
            mf = _model_file(model)
            if not mf.is_file():
                continue  # M001 reports it
            names = ", ".join(sorted(t.name for t in groups))
            out.append(
                self.violation(
                    f"the model has calculation group(s) ({names}) but "
                    f"model.tmdl does not set discourageImplicitMeasures, so "
                    f"the model cannot be saved or deployed. Add a "
                    f"'discourageImplicitMeasures' line under 'model'.",
                    file=mf,
                    obj=names,
                )
            )
        return out


class RefTableTargetRule(Rule):
    id = "M015"
    name = "ref-table-target-missing"
    severity = Severity.ERROR
    baselinable = False
    description = (
        "Every 'ref table <name>' line in model.tmdl must name a table that "
        "is defined under tables/. A ref to a missing table (a deleted or "
        "renamed table file) stops Power BI Desktop from opening the project. "
        "Restore the table file or delete the ref line."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            mf = model.info.file
            for name, line in model.info.ref_tables:
                if model.find_table(name) is None:
                    out.append(
                        self.violation(
                            f"'ref table {_render_table_ref(name)}' names a table "
                            f"that no file under tables/ defines, so Power BI "
                            f"Desktop will not open the project. Restore the "
                            f"table file, or delete this line if the table was "
                            f"removed on purpose.",
                            file=mf,
                            line=line,
                            obj=name,
                        )
                    )
        return out
