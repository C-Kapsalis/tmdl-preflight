"""File-hygiene rules over raw TMDL text: indentation, duplicate model
annotations, query-group references. IDs M017-M019."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..edits import EditRefused, read_text_file, verified_write
from ..parser import indent_level, parse_object_name
from .base import Context, Rule, Severity, Violation

# ---------------------------------------------------------------------------
# M017: structure lines indented with spaces
# ---------------------------------------------------------------------------

_BODY_OWNER_RE = re.compile(
    r"^[\t ]*(?:measure|column|calculationItem|expression|formatStringDefinition|source)\b"
)
_BARE_QUOTED_MEASURE_RE = re.compile(r"""^\s*measure\s+(?:'[^']*'|"[^"]*")\s*=\s*$""")


def expression_body_lines(lines: list[str]) -> set[int]:
    """0-based indexes of lines that belong to an expression body: the inside
    of a ``` fence, or a continuation line indented two or more levels deeper
    than the declaration that opened the body with a trailing ``=``."""
    body: set[int] = set()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if _BODY_OWNER_RE.match(line) and "=" in line:
            after = line.split("=", 1)[1].strip()
            level = indent_level(line)
            if after.startswith("```") and after.count("```") == 1:
                j = i + 1
                while j < n and not lines[j].strip().startswith("```"):
                    body.add(j)
                    j += 1
                i = j + 1
                continue
            if not after:
                j = i + 1
                while j < n and (not lines[j].strip() or indent_level(lines[j]) >= level + 2):
                    if lines[j].strip():
                        body.add(j)
                    j += 1
                i = j
                continue
        i += 1
    return body


class SpaceIndentationRule(Rule):
    id = "M017"
    name = "space-indentation"
    severity = Severity.ERROR
    option_defaults = {"strict": False, "bare_multiline_info": False}
    description = (
        "TMDL nests objects by tab indentation, and Power BI Desktop always "
        "writes tabs. A declaration or property line that starts with four "
        "spaces (usually pasted from an editor that turned tabs into spaces, "
        "or written by a script) may attach to the wrong object or fail to "
        "load. Lines inside expression bodies are exempt unless strict is "
        "on; a line that starts with tabs and then has spaces is never "
        "flagged. Optional info (bare_multiline_info): a quoted measure whose "
        "multi-line body is not fenced with ```."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        strict = bool(self.options.get("strict"))
        style = bool(self.options.get("bare_multiline_info"))
        for model in ctx.models:
            for f in sorted((model.definition_path / "tables").glob("*.tmdl")):
                if ctx.is_excluded(f):
                    continue
                try:
                    lines = f.read_text(encoding="utf-8-sig").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue  # M002 reports unreadable files
                exempt = set() if strict else expression_body_lines(lines)
                for idx, line in enumerate(lines):
                    if line.startswith("    ") and idx not in exempt:
                        out.append(self.violation(
                            f"line {idx + 1} is indented with spaces where TMDL "
                            f"expects tabs; replace each four-space step with "
                            f"one tab.",
                            file=f, line=idx + 1,
                        ))
                    if style and _BARE_QUOTED_MEASURE_RE.match(line):
                        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
                        if nxt.strip() and not nxt.strip().startswith("```"):
                            out.append(self.violation(
                                f"Line {idx + 1}: Multiline DAX should use triple "
                                f"backticks",
                                file=f, line=idx + 1, severity=Severity.INFO,
                            ))
        return out


# ---------------------------------------------------------------------------
# M018: duplicate annotation names in one scope of model.tmdl
# ---------------------------------------------------------------------------

_ANNOTATION_RE = re.compile(r"^(?P<indent>[\t ]*)annotation\s+(?P<name>[\w/]+)\s*=")
_SCOPE_DECL_RE = re.compile(
    r"^[\t ]*(?P<kw>queryGroup|table|measure|column|partition|relationship)\s+(?P<rest>.+)$"
)


class ModelAnnotationDuplicatesRule(Rule):
    id = "M018"
    name = "model-annotation-duplicates"
    severity = Severity.ERROR
    description = (
        "An object may carry each annotation name once. Two 'annotation X = "
        "...' lines in the same scope of model.tmdl (the model itself, a "
        "query group, or any object declared there) are a merge accident: "
        "scripts that append model-level annotations such as the query order "
        "are the usual cause. Names compare exactly. Not auto-fixable: which "
        "value is right is a human decision."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            mf = model.definition_path / "model.tmdl"
            if not mf.is_file() or ctx.is_excluded(mf):
                continue
            try:
                lines = mf.read_text(encoding="utf-8-sig").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            scope = "model"
            seen: dict[tuple[str, str], list[int]] = {}
            order: list[tuple[str, str]] = []
            for idx, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                decl = _SCOPE_DECL_RE.match(line)
                if decl:
                    name, _ = parse_object_name(decl.group("rest"))
                    scope = f"{decl.group('kw')}:{name}"
                    continue
                ann = _ANNOTATION_RE.match(line)
                if ann:
                    if not ann.group("indent"):
                        scope = "model"
                    key = (scope, ann.group("name"))
                    if key not in seen:
                        seen[key] = []
                        order.append(key)
                    seen[key].append(idx)
                    continue
                if indent_level(line) == 0 and not line.startswith("ref "):
                    scope = "model"
                elif line.startswith("ref "):
                    scope = "model"
            for key in order:
                where = seen[key]
                if len(where) < 2:
                    continue
                scope_name, ann_name = key
                lines_text = ", ".join(f"line {n}" for n in where)
                if scope_name == "model":
                    message = (
                        f"Model-level annotation '{ann_name}' appears "
                        f"{len(where)} times ({lines_text})")
                elif scope_name.startswith("queryGroup:"):
                    group = scope_name.split(":", 1)[1]
                    message = (
                        f"QueryGroup '{group}' has duplicate annotation "
                        f"'{ann_name}' ({len(where)} times at {lines_text})")
                else:
                    message = (
                        f"{scope_name.replace(':', ' ', 1)} has duplicate "
                        f"annotation '{ann_name}' ({len(where)} times at "
                        f"{lines_text})")
                out.append(self.violation(
                    message, file=mf, line=where[0],
                    obj=f"{scope_name}/{ann_name}"))
        return out


# ---------------------------------------------------------------------------
# M019: queryGroup references without a declaration
# ---------------------------------------------------------------------------

_GROUP_DECL_RE = re.compile(r"^[\t ]*queryGroup\s+(?P<rest>.+?)\s*$")
_GROUP_REF_RE = re.compile(r"^[\t ]*queryGroup\s*:\s*(?P<value>.+?)\s*$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        q = value[0]
        return value[1:-1].replace(q + q, q)
    return value


def _render_group(name: str) -> str:
    if re.search(r"[\s\\']", name):
        return "'" + name.replace("'", "''") + "'"
    return name


class UndefinedQueryGroupRule(Rule):
    id = "M019"
    name = "undefined-query-group"
    severity = Severity.ERROR
    fixable = True
    option_defaults = {"query_group_order_start": 99}
    description = (
        "A partition or shared expression placed in a Power Query folder "
        "('queryGroup: <name>') needs the folder declared in model.tmdl "
        "('queryGroup <name>'). Copying a table from another model without "
        "its folder declaration leaves the reference dangling. Auto-fix "
        "declares each missing group after the existing ones, with a "
        "PBI_QueryGroupOrder annotation numbered from 99."
    )

    def _scan(self, model) -> tuple[Optional[Path], set[str], dict[str, list[tuple[Path, int, str]]]]:
        mf = model.definition_path / "model.tmdl"
        declared: set[str] = set()
        if mf.is_file():
            try:
                for line in mf.read_text(encoding="utf-8-sig").splitlines():
                    m = _GROUP_DECL_RE.match(line)
                    if m:
                        name, _ = parse_object_name(m.group("rest"))
                        declared.add(name)
            except (OSError, UnicodeDecodeError):
                pass
        refs: dict[str, list[tuple[Path, int, str]]] = {}
        files = sorted((model.definition_path / "tables").glob("*.tmdl"))
        expr = model.definition_path / "expressions.tmdl"
        if expr.is_file():
            files.append(expr)
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8-sig").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            owner = f.stem
            for idx, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped.startswith(("table ", "partition ", "expression ")):
                    owner = stripped.split("=", 1)[0].strip()
                m = _GROUP_REF_RE.match(line)
                if m:
                    refs.setdefault(_unquote(m.group("value")), []).append((f, idx, owner))
        return (mf if mf.is_file() else None), declared, refs

    def _missing(self, model):
        mf, declared, refs = self._scan(model)
        return mf, {name: where for name, where in refs.items() if name not in declared}

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            _mf, missing = self._missing(model)
            for name, where in sorted(missing.items()):
                f, line, _owner = where[0]
                owners = ", ".join(sorted({w[2] for w in where}))
                out.append(self.violation(
                    f"query group '{name}' is used ({owners}) but model.tmdl "
                    f"does not declare it ('queryGroup {_render_group(name)}'). "
                    f"Declare the group (the auto-fix does) or remove the "
                    f"queryGroup property.",
                    file=f, line=line, obj=name,
                ))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        start = int(self.options.get("query_group_order_start", 99))
        for model in ctx.models:
            mf, missing = self._missing(model)
            if not missing or mf is None:
                continue
            original = read_text_file(mf)
            lines = original.lines()
            insert_at = _group_insert_point(lines)
            block: list[str] = []
            for n, name in enumerate(sorted(missing)):
                block += [f"queryGroup {_render_group(name)}",
                          f"\tannotation PBI_QueryGroupOrder = {start + n}", ""]
            if insert_at > 0 and lines[insert_at - 1].strip():
                block.insert(0, "")
            new_lines = lines[:insert_at] + block + lines[insert_at:]

            def verify(old: str, new: str, _added=len(block)) -> None:
                o, nw = old.split(original.newline), new.split(original.newline)
                if len(nw) - len(o) != _added or any(ln not in nw for ln in o):
                    raise EditRefused("query-group insert changed existing lines")

            try:
                if verified_write(original, original.join(new_lines), verify):
                    applied.extend(f"model.tmdl: + queryGroup {_render_group(n)}" for n in sorted(missing))
            except EditRefused:
                continue
        return applied


def _group_insert_point(lines: list[str]) -> int:
    """Where new queryGroup blocks go: after the last existing block (its
    line plus the indented and blank lines after it); else before the first
    model-level annotation; else before the first ``ref`` line; else at the
    end."""
    last_group = None
    for idx, line in enumerate(lines):
        if _GROUP_DECL_RE.match(line) and indent_level(line) == 0:
            last_group = idx
    if last_group is not None:
        j = last_group + 1
        while j < len(lines) and (not lines[j].strip() or indent_level(lines[j]) > 0):
            j += 1
        return j
    for idx, line in enumerate(lines):
        if line.startswith("annotation "):
            return idx
    for idx, line in enumerate(lines):
        if line.startswith("ref "):
            return idx
    return len(lines)


# ---------------------------------------------------------------------------
# M022 blank diagram layout
# ---------------------------------------------------------------------------

def canonical_diagram_layout() -> str:
    import json as _json

    data = {
        "version": "1.1.0",
        "diagrams": [{
            "ordinal": 0,
            "scrollPosition": {"x": 0, "y": 0},
            "nodes": [],
            "name": "All tables",
            "zoomValue": 100,
            "pinKeyFieldsToTop": False,
            "showExtraHeaderInfo": False,
            "hideKeyFieldsWhenCollapsed": False,
            "tablesLocked": False,
        }],
        "selectedDiagram": "All tables",
        "defaultDiagram": "All tables",
    }
    return _json.dumps(data, indent=2, ensure_ascii=False) + "\n"


class DiagramLayoutBlankRule(Rule):
    id = "M022"
    name = "diagram-layout-blank"
    severity = Severity.WARNING
    fixable = True
    opt_in = True
    description = (
        "Opt-in: diagramLayout.json must be the blank layout (one 'All "
        "tables' diagram with no table boxes). Power BI never prunes the "
        "layout when tables are renamed or removed, so stale boxes pile up "
        "and clutter the Model view; a blank layout cannot go stale and the "
        "Model view arranges the tables itself. Auto-fix writes the blank "
        "layout. Leave the rule off if your team curates layouts."
    )

    def _stale(self, ctx: Context):
        want = canonical_diagram_layout()
        for model in ctx.models:
            path = model.definition_path.parent / "diagramLayout.json"
            if not path.is_file() or ".git" in path.parts:
                continue
            try:
                text = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                text = None
            if text != want:
                yield path

    def check(self, ctx: Context) -> list[Violation]:
        return [self.violation(
            "diagramLayout.json is not the blank layout; stale table boxes accumulate "
            "there. Replace it with the blank layout (the auto-fix does).",
            file=path, obj=path.parent.name) for path in self._stale(ctx)]

    def fix(self, ctx: Context) -> list[str]:
        applied = []
        for path in list(self._stale(ctx)):
            path.write_bytes(canonical_diagram_layout().encode("utf-8"))
            applied.append(f"{path.parent.name}/diagramLayout.json: replaced with the blank layout")
        return applied
