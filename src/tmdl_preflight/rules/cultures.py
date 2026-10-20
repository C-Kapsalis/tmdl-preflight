"""Culture files: Q&A linguistic metadata bound to tables that are gone.
ID M021."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..edits import EditRefused, TextFile, read_text_file, verified_write
from ..model import SemanticModel
from .base import Context, Rule, Severity, Violation

_PREFIX = "\t\t\t"


def _block(lines: list[str]) -> Optional[tuple[int, int]]:
    """Line range [start, end) of the linguistic-metadata JSON body."""
    for idx, line in enumerate(lines):
        if line.strip() == "linguisticMetadata =":
            end = idx + 1
            while end < len(lines) and lines[end].startswith(_PREFIX):
                end += 1
            return (idx + 1, end) if end > idx + 1 else None
    return None


def _parse(lines: list[str], span: tuple[int, int]) -> Any:
    try:
        return json.loads("\n".join(ln[len(_PREFIX):] for ln in lines[span[0]:span[1]]))
    except ValueError:
        return None


def _bound_entity(node: Any) -> Optional[str]:
    if not isinstance(node, dict):
        return None
    binding = node.get("Binding")
    if isinstance(binding, dict):
        ent = binding.get("ConceptualEntity")
        return ent if isinstance(ent, str) else None
    definition = node.get("Definition")
    if isinstance(definition, dict) and isinstance(definition.get("Binding"), dict):
        ent = definition["Binding"].get("ConceptualEntity")
        return ent if isinstance(ent, str) else None
    return None


def bound_entities(data: Any) -> set[str]:
    out: set[str] = set()

    def walk(node: Any) -> None:
        ent = _bound_entity(node)
        if ent is not None:
            out.add(ent)
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return out


def prune(data: Any, orphans: set[str]) -> tuple[Any, int]:
    """Remove every member and item bound to an orphan entity."""
    removed = 0

    def walk(node: Any) -> Any:
        nonlocal removed
        if isinstance(node, dict):
            kept = {}
            for k, v in node.items():
                if _bound_entity(v) in orphans:
                    removed += 1
                    continue
                kept[k] = walk(v)
            return kept
        if isinstance(node, list):
            kept_list = []
            for v in node:
                if _bound_entity(v) in orphans:
                    removed += 1
                    continue
                kept_list.append(walk(v))
            return kept_list
        return node

    return walk(data), removed


def _model_tables(model: SemanticModel) -> set[str]:
    folder = model.definition_path / "tables"
    return {p.stem for p in folder.glob("*.tmdl")} if folder.is_dir() else set()


class CultureOrphanBindingsRule(Rule):
    id = "M021"
    name = "culture-orphan-bindings"
    severity = Severity.ERROR
    fixable = True
    option_defaults = {"tables": []}
    description = (
        "Q&A linguistic metadata in cultures/*.tmdl binds nodes to tables "
        "(ConceptualEntity). A binding to a table file that no longer exists "
        "does not break queries, but it is dead metadata and a sign the table "
        "was removed without a cleanup (dangling DAX references are likely "
        "too). Option tables names entities to treat as removed. Auto-fix "
        "deletes the nodes bound to missing tables and nothing else."
    )

    def _orphans(self, model: SemanticModel):
        folder = model.definition_path / "cultures"
        if not folder.is_dir():
            return
        tables = _model_tables(model)
        extra = set(self.options.get("tables") or [])
        for path in sorted(folder.glob("*.tmdl")):
            try:
                tf = read_text_file(path)
            except (OSError, UnicodeDecodeError):
                continue
            lines = tf.lines()
            span = _block(lines)
            if span is None:
                continue
            data = _parse(lines, span)
            if data is None:
                continue
            bound = bound_entities(data)
            orphans = {e for e in bound if e not in tables} | (bound & extra)
            if orphans:
                yield path, tf, span, data, orphans

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for path, _tf, span, _d, orphans in self._orphans(model):
                out.append(self.violation(
                    f"{path.name} binds linguistic metadata to missing table(s): "
                    f"{', '.join(sorted(orphans))}; remove those nodes (the auto-fix does).",
                    file=path, line=span[0], obj=path.stem))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for path, tf, span, data, orphans in list(self._orphans(model)):
                new_data, removed = prune(data, orphans)
                if not removed:
                    continue
                body = [_PREFIX + ln for ln in
                        json.dumps(new_data, indent=2, ensure_ascii=False).split("\n")]
                lines = tf.lines()
                new_lines = lines[:span[0]] + body + lines[span[1]:]

                def verify(old: str, new: str, tf: TextFile = tf, orphans=orphans) -> None:
                    nl = new.split(tf.newline)
                    sp = _block(nl)
                    parsed = _parse(nl, sp) if sp else None
                    if parsed is None or bound_entities(parsed) & orphans:
                        raise EditRefused("culture metadata did not round-trip")

                try:
                    verified_write(tf, tf.join(new_lines), verify)
                except EditRefused:
                    continue
                applied.append(f"{path.name}: removed {removed} binding node(s) for "
                               f"{', '.join(sorted(orphans))}")
        return applied
