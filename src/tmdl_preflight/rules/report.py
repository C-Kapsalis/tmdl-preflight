"""Report-side rules over PBIP report folders: bookmark JSON. IDs B0xx."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .base import Context, Rule, Severity, Violation

# Bookmark JSON fields the report loader requires to be JSON integers.
INT_FIELDS = ("howCreated", "ComparisonKind", "Version")

# Legacy string spellings of howCreated that have a known integer meaning.
HOW_CREATED_MAP = {"user": 0, "manual": 0, "system": 1, "auto": 1}


def _bookmark_files(report_dir: Path) -> list[Path]:
    return sorted(report_dir.rglob("*.bookmark.json"))


def _walk_string_ints(obj: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    """Yield (json_path, field, value) for every INT_FIELD holding a string."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else k
            if k in INT_FIELDS and isinstance(v, str):
                yield here, k, v
            yield from _walk_string_ints(v, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _walk_string_ints(item, f"{path}[{i}]")


def _coerce_string_ints(obj: Any, path: str = "") -> list[str]:
    """Convert string-typed int fields in place; return fix descriptions."""
    fixes: list[str] = []
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            here = f"{path}.{k}" if path else k
            if k in INT_FIELDS and isinstance(v, str):
                new_value = None
                if k == "howCreated" and v.lower() in HOW_CREATED_MAP:
                    new_value = HOW_CREATED_MAP[v.lower()]
                elif v.lstrip("-").isdigit():
                    new_value = int(v)
                if new_value is not None:
                    obj[k] = new_value
                    fixes.append(f"{here}: '{v}' -> {new_value}")
            if isinstance(v, (dict, list)):
                fixes.extend(_coerce_string_ints(v, here))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            fixes.extend(_coerce_string_ints(item, f"{path}[{i}]"))
    return fixes


class BookmarkIntegerTypesRule(Rule):
    id = "B001"
    name = "bookmark-int-types"
    severity = Severity.ERROR
    fixable = True
    description = (
        "Bookmark JSON requires howCreated, ComparisonKind and Version to be "
        "JSON integers. String values ('0', 'User', '2') make the report "
        "loader reject the bookmark with 'Expected Number but got String'. "
        "Auto-fix rewrites the values as integers."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            for bf in _bookmark_files(report_dir):
                try:
                    data = json.loads(bf.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    out.append(self.violation(f"unreadable bookmark JSON: {exc}", file=bf))
                    continue
                for json_path, field, value in _walk_string_ints(data):
                    out.append(
                        self.violation(
                            f"{field} at {json_path} is the string '{value}' "
                            f"(must be a JSON integer)",
                            file=bf,
                            obj=bf.stem,
                        )
                    )
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for report_dir in ctx.report_dirs:
            for bf in _bookmark_files(report_dir):
                try:
                    data = json.loads(bf.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue  # unreadable files stay a plain check failure
                fixes = _coerce_string_ints(data)
                if fixes:
                    bf.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    applied.extend(f"{bf.name}: {fx}" for fx in fixes)
        return applied


class BookmarkVisualRefsRule(Rule):
    id = "B002"
    name = "bookmark-visual-refs"
    severity = Severity.ERROR
    description = (
        "Every visualName a bookmark captures must resolve to an actual "
        "visual folder under pages/*/visuals/. A dangling reference means "
        "the visual was renamed or deleted after the bookmark was authored; "
        "the bookmark will silently no-op or break on apply. Not "
        "auto-fixable: the right resolution (restore the visual, retarget "
        "or delete the bookmark) depends on intent."
    )

    @staticmethod
    def _visual_names(report_dir: Path) -> set[str]:
        names: set[str] = set()
        for visuals_dir in report_dir.rglob("visuals"):
            if not visuals_dir.is_dir():
                continue
            for vdir in visuals_dir.iterdir():
                if vdir.is_dir():
                    names.add(vdir.name)
        return names

    @staticmethod
    def _referenced_visuals(data: dict) -> list[str]:
        refs: list[str] = []
        state = data.get("explorationState") or {}
        containers = state.get("visualContainers")
        if isinstance(containers, dict):
            refs.extend(containers.keys())
        elif isinstance(containers, list):
            for c in containers:
                name = ((c or {}).get("singleVisual") or {}).get("visualName")
                if isinstance(name, str):
                    refs.append(name)
        options = data.get("options") or {}
        for name in options.get("targetVisualNames") or []:
            if isinstance(name, str):
                refs.append(name)
        return refs

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            visuals = self._visual_names(report_dir)
            bookmarks = _bookmark_files(report_dir)
            if not bookmarks or not visuals:
                continue
            for bf in bookmarks:
                try:
                    data = json.loads(bf.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue  # B001 reports unreadable bookmarks
                for ref in self._referenced_visuals(data):
                    if ref not in visuals:
                        out.append(
                            self.violation(
                                f"bookmark captures visual '{ref}', but no "
                                f"visual folder with that name exists under "
                                f"pages/. The visual was probably renamed or "
                                f"deleted after the bookmark was created, so "
                                f"the bookmark will silently stop working; "
                                f"restore the visual, re-create the bookmark, "
                                f"or delete it.",
                                file=bf,
                                obj=bf.stem,
                            )
                        )
        return out
