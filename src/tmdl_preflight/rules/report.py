"""Report-side rules over PBIP report folders: bookmark JSON. IDs B0xx."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterator, Optional

from ..edits import EditRefused, read_text_file, verified_write
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


def _coerce_value(key: str, value: str) -> Optional[int]:
    if key == "howCreated" and value.lower() in HOW_CREATED_MAP:
        return HOW_CREATED_MAP[value.lower()]
    if value.lstrip("-").isdigit():
        return int(value)
    return None


def surgical_coerce_string_ints(text: str) -> tuple[str, list[str]]:
    """Rewrite string-typed int fields in the JSON *text* itself.

    Only the offending values change (``"howCreated": "0"`` becomes
    ``"howCreated": 0``); key order, spacing and every other byte stay as
    they were. The edit is proven by parsing both sides: the new document
    must equal the old one with exactly those values coerced. Raises
    ``EditRefused`` otherwise.
    """
    before = json.loads(text)
    expected = copy.deepcopy(before)
    fixes = _coerce_string_ints(expected)
    if not fixes:
        return text, []
    new = text
    for key in INT_FIELDS:
        pattern = re.compile(r'("' + re.escape(key) + r'"\s*:\s*)"([^"\\]*)"')

        def repl(m: "re.Match[str]", key: str = key) -> str:
            target = _coerce_value(key, m.group(2))
            return m.group(0) if target is None else f"{m.group(1)}{target}"

        new = pattern.sub(repl, new)
    try:
        after = json.loads(new)
    except json.JSONDecodeError as exc:
        raise EditRefused(f"edit produced invalid JSON: {exc}") from exc
    if after != expected:
        raise EditRefused("edit changed something beyond the string-typed integers")
    return new, fixes


class BookmarkIntegerTypesRule(Rule):
    id = "B001"
    name = "bookmark-int-types"
    severity = Severity.ERROR
    fixable = True
    description = (
        "Bookmark JSON requires howCreated, ComparisonKind and Version to be "
        "JSON integers. String values ('0', 'User', '2') make the report "
        "loader reject the bookmark with 'Expected Number but got String'. "
        "Auto-fix rewrites only the offending values in place, then proves the "
        "edit by parsing both versions of the file."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            for bf in _bookmark_files(report_dir):
                try:
                    data = json.loads(bf.read_text(encoding="utf-8-sig"))
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
                    original = read_text_file(bf)
                    new_text, fixes = surgical_coerce_string_ints(original.text)
                    if fixes and verified_write(original, new_text):
                        applied.extend(f"{bf.name}: {fx}" for fx in fixes)
                except (json.JSONDecodeError, OSError, UnicodeDecodeError, EditRefused):
                    continue  # unreadable or unprovable: stays a check failure
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
                    data = json.loads(bf.read_text(encoding="utf-8-sig"))
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


# Keys the report loader accepts in a bookmark's "options" object.
ALLOWED_OPTIONS_KEYS = frozenset(
    {
        "targetVisualNames",
        "applyOnlyToTargetVisuals",
        "suppressData",
        "suppressActiveSection",
        "suppressDisplay",
    }
)


def illegal_option_keys(data: Any) -> list[str]:
    """Sorted bookmark ``options`` keys outside the accepted schema."""
    if not isinstance(data, dict):
        return []
    options = data.get("options")
    if not isinstance(options, dict):
        return []
    return sorted(set(options) - ALLOWED_OPTIONS_KEYS)


def _member_spans(text: str, key: str) -> list[tuple[int, int]]:
    """Candidate ``(start, end)`` spans of a ``"key": value`` member, each
    including the comma that binds it to a neighbor, so removing the span
    keeps the surrounding JSON valid."""
    decoder = json.JSONDecoder()
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r'"' + re.escape(key) + r'"\s*:\s*', text):
        try:
            _value, end = decoder.raw_decode(text, m.end())
        except json.JSONDecodeError:
            continue
        k = end
        while k < len(text) and text[k] in " \t\r\n":
            k += 1
        if k < len(text) and text[k] == ",":
            # first or middle member: take the comma and the whitespace up to
            # the next member
            k += 1
            while k < len(text) and text[k] in " \t\r\n":
                k += 1
            spans.append((m.start(), k))
            continue
        # last member: take the preceding comma and whitespace instead
        b = m.start()
        while b > 0 and text[b - 1] in " \t\r\n":
            b -= 1
        if b > 0 and text[b - 1] == ",":
            spans.append((b - 1, end))
        else:
            spans.append((m.start(), end))  # sole member
    return spans


def strip_illegal_options(text: str) -> tuple[str, list[str]]:
    """Remove illegal ``options`` keys from bookmark JSON *text*, surgically.

    Each key's member is cut out of the text (no re-serialization), and the
    result is proven by parsing: it must equal the original document minus
    exactly those keys. Raises ``EditRefused`` when that cannot be shown.
    """
    data = json.loads(text)
    removed = illegal_option_keys(data)
    if not removed:
        return text, []
    new = text
    for key in removed:
        expected = json.loads(new)
        expected["options"].pop(key, None)
        for start, end in _member_spans(new, key):
            candidate = new[:start] + new[end:]
            try:
                if json.loads(candidate) == expected:
                    new = candidate
                    break
            except json.JSONDecodeError:
                continue
        else:
            raise EditRefused(f"could not remove options.{key} without other changes")
    final = json.loads(new)
    target = copy.deepcopy(data)
    for key in removed:
        target["options"].pop(key, None)
    if final != target:
        raise EditRefused("edit changed something beyond the removed keys")
    return new, removed


class BookmarkOptionsSchemaRule(Rule):
    id = "B003"
    name = "bookmark-options-schema"
    severity = Severity.ERROR
    fixable = True
    description = (
        "A bookmark's 'options' object may only contain targetVisualNames, "
        "applyOnlyToTargetVisuals, suppressData, suppressActiveSection and "
        "suppressDisplay. Any other key (a typo, or a key a script invented) "
        "fails schema validation and the report is rejected on import. "
        "Auto-fix cuts only the illegal members out of the file and proves "
        "the edit by parsing both versions."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            for bf in _bookmark_files(report_dir):
                try:
                    data = json.loads(bf.read_text(encoding="utf-8-sig"))
                except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                    continue  # B001 reports unreadable bookmarks
                for key in illegal_option_keys(data):
                    out.append(
                        self.violation(
                            f"options.{key} is not a bookmark option the "
                            f"report schema accepts, so the report is rejected "
                            f"on import. Remove it (the auto-fix does); the "
                            f"accepted keys are "
                            f"{', '.join(sorted(ALLOWED_OPTIONS_KEYS))}.",
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
                    original = read_text_file(bf)
                    new_text, removed = strip_illegal_options(original.text)
                    if removed and verified_write(original, new_text):
                        applied.extend(f"{bf.name}: removed options.{k}" for k in removed)
                except (json.JSONDecodeError, OSError, UnicodeDecodeError, EditRefused):
                    continue
        return applied


class ReportDefinitionIntegrityRule(Rule):
    id = "B004"
    name = "report-definition-integrity"
    severity = Severity.ERROR
    description = (
        "The report definition must hold together: definition.pbir's byPath "
        "reference must point at an existing *.SemanticModel folder, every "
        "page listed in pages/pages.json (pageOrder, activePageName) must "
        "have its folder, and every page.json and visual.json must be valid "
        "JSON. Any of these breaks the report on open."
    )

    @staticmethod
    def _load(path: Path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            pbir = report_dir / "definition.pbir"
            if pbir.is_file():
                try:
                    data = self._load(pbir)
                except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                    out.append(
                        self.violation(
                            f"definition.pbir is not valid JSON ({exc}), so the "
                            f"report cannot find its semantic model. Restore "
                            f"the file from source control.",
                            file=pbir,
                        )
                    )
                    data = None
                ref = ((data or {}).get("datasetReference") or {}).get("byPath") if isinstance(data, dict) else None
                if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                    target = (report_dir / ref["path"]).resolve()
                    if not target.is_dir() or not target.name.endswith(".SemanticModel"):
                        out.append(
                            self.violation(
                                f"definition.pbir points at '{ref['path']}', "
                                f"but no *.SemanticModel folder exists there, so "
                                f"the report cannot load its data. Fix the "
                                f"path or restore the semantic model folder.",
                                file=pbir,
                                obj=ref["path"],
                            )
                        )
            pages_dir = report_dir / "definition" / "pages"
            pages_json = pages_dir / "pages.json"
            if pages_json.is_file():
                try:
                    meta = self._load(pages_json)
                except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                    out.append(
                        self.violation(
                            f"pages.json is not valid JSON ({exc}). Restore it "
                            f"from source control.",
                            file=pages_json,
                        )
                    )
                    meta = None
                if isinstance(meta, dict):
                    names = [n for n in meta.get("pageOrder") or [] if isinstance(n, str)]
                    active = meta.get("activePageName")
                    if isinstance(active, str) and active not in names:
                        names.append(active)
                    for name in names:
                        if not (pages_dir / name).is_dir():
                            out.append(
                                self.violation(
                                    f"pages.json lists page '{name}', but "
                                    f"pages/{name}/ does not exist, so the "
                                    f"report fails to open. Remove the entry "
                                    f"or restore the page folder.",
                                    file=pages_json,
                                    obj=name,
                                )
                            )
            if pages_dir.is_dir():
                for f in sorted(pages_dir.rglob("*.json")):
                    if f.name not in ("visual.json", "page.json"):
                        continue
                    try:
                        self._load(f)
                    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                        out.append(
                            self.violation(
                                f"{f.name} is not valid JSON ({exc}), so the "
                                f"report cannot render this "
                                f"{'visual' if f.name == 'visual.json' else 'page'}. "
                                f"Restore the file from source control.",
                                file=f,
                                obj=f.parent.name,
                            )
                        )
        return out
