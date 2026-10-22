"""Report-side rules over PBIP report folders: bookmark JSON. IDs B0xx."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterator, Optional

from ..edits import EditRefused, read_text_file, verified_write, write_json
from .base import Context, Rule, Severity, Violation

# Bookmark JSON fields the report loader requires to be JSON integers.
INT_FIELDS = ("howCreated", "ComparisonKind", "Version")

# Legacy string spellings of howCreated that have a known integer meaning.
HOW_CREATED_MAP = {"user": 0, "manual": 0, "system": 1, "auto": 1}


# Path fragments that mark an archived copy of a report; bookmarks below them
# are not scanned (project section ``bookmarks.archive_markers``).
ARCHIVE_MARKERS = ["legacy/", "_backup/", "_legacy/", "_b2/", "DemoData.", "demodata/"]


def _bookmark_files(report_dir: Path, ctx: Optional[Context] = None) -> list[Path]:
    files = sorted(report_dir.rglob("*.bookmark.json"))
    if ctx is None:
        return files
    markers = (ctx.options.get("bookmarks") or {}).get("archive_markers", ARCHIVE_MARKERS)
    if not markers:
        return files
    out = []
    for f in files:
        rel = ctx.scan_relative(f) or f.as_posix()
        if not any(m in rel for m in markers):
            out.append(f)
    return out


def _is_archived(ctx: Context, path: Path) -> bool:
    """Is this bookmark a copy of a report that was archived?"""
    markers = (ctx.options.get("bookmarks") or {}).get("archive_markers", ARCHIVE_MARKERS)
    if not markers:
        return False
    rel = ctx.scan_relative(path) or path.as_posix()
    return any(m in rel for m in markers)


def bookmark_files(ctx: Context) -> list[Path]:
    """Every bookmark file in scope (archived copies skipped)."""
    files = [f for r in ctx.report_dirs for f in _bookmark_files(r, ctx)]
    files.extend(f for f in ctx.bookmark_targets if not _is_archived(ctx, f))
    return sorted(set(files))


def report_of(path: Path) -> Optional[Path]:
    """The report folder a bookmark belongs to, when there is one."""
    for parent in path.parents:
        if parent.name.endswith(".Report"):
            return parent
    return None


def _direct_bookmarks(ctx: Context) -> list[Path]:
    """The bookmarks the scan root names itself (a file, or a folder of them)."""
    out: list[Path] = []
    for target in ctx.bookmark_targets:
        if target.is_file():
            out.append(target)
        else:
            out.extend(sorted(p for p in target.glob("*.bookmark.json") if p.is_file()))
    return [f for f in out if not _is_archived(ctx, f)]


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


class BookmarkIntegerTypesRule(Rule):
    id = "B001"
    name = "bookmark-int-types"
    severity = Severity.ERROR
    fixable = True
    description = (
        "Bookmark JSON requires howCreated, ComparisonKind and Version to be "
        "JSON integers. String values ('0', 'User', '2') make the report "
        "loader reject the bookmark with 'Expected Number but got String'. "
        "The auto-fix rewrites the file with the integers in place."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        files = bookmark_files(ctx)
        if not files:
            ctx.notes.append(f"No .bookmark.json files found under {ctx.root}")
            return out
        total = 0
        dirty = 0
        for bf in files:
            try:
                data = json.loads(bf.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                out.append(self.violation(
                    f"ERROR reading {bf}: {exc}", file=bf, fixable=False))
                total += 1
                dirty += 1
                continue
            found = 0
            for json_path, field, value in _walk_string_ints(data):
                out.append(self.violation(
                    f"[{field}] at {json_path} = '{value}' (string, must be int)",
                    file=bf,
                    obj=bf.stem,
                    fixable=_coerce_value(field, value) is not None,
                ))
                found += 1
            total += found
            dirty += 1 if found else 0
        if total:
            ctx.notes.append(
                f"Total: {total} violation(s) across {dirty} file(s).")
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        files_changed = 0
        total = 0
        for bf in bookmark_files(ctx):
            try:
                original = read_text_file(bf)
                data = json.loads(original.text)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue  # unreadable: stays a check failure
            fixes = _coerce_string_ints(data)
            if not fixes:
                continue
            try:
                written = write_json(original, data)
            except EditRefused:
                continue
            if written:
                files_changed += 1
                total += len(fixes)
                applied.extend(f"fix: {fx}" for fx in fixes)
        if files_changed:
            ctx.notes.append(
                f"Applied {total} fix(es) across {files_changed} file(s).")
        else:
            ctx.notes.append("No fixes needed.")
        return applied


class BookmarkVisualRefsRule(Rule):
    id = "B002"
    name = "bookmark-visual-refs"
    severity = Severity.ERROR
    description = (
        "Every visualName a bookmark captures must resolve to an actual "
        "visual folder under pages/*/visuals/. A dangling reference means "
        "the visual was renamed or deleted after the bookmark was authored; "
        "the bookmark will silently no-op or break on apply. It cannot be "
        "auto-repaired: restore the missing visual, retarget the bookmark to "
        "an existing visual, or delete the obsolete bookmark."
    )

    @staticmethod
    def _visual_names(report_dir: Path) -> set[str]:
        """The names of the visuals the report holds.

        Only the folders directly under a page's ``visuals`` folder count:
        a folder named ``visuals`` anywhere else (a theme's static
        resources, for example) holds no visual.
        """
        names: set[str] = set()
        pages = report_dir / "definition" / "pages"
        if not pages.is_dir():
            return names
        for page_dir in sorted(pages.iterdir()):
            visuals_dir = page_dir / "visuals"
            if not visuals_dir.is_dir():
                continue
            for vdir in sorted(visuals_dir.iterdir()):
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
        pairs = self._bookmarks_in_scope(ctx)
        if not pairs:
            return out
        visuals = {report: self._visual_names(report) for _bf, report in pairs}
        for bf, report in pairs:
            if not visuals[report]:
                continue
            try:
                data = json.loads(bf.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                out.append(self.violation(
                    f"Could not parse {bf}: {exc}", file=bf, obj=bf.stem))
                continue
            if not isinstance(data, dict):
                continue
            for ref in self._referenced_visuals(data):
                if ref not in visuals[report]:
                    out.append(self.violation(
                        f"{bf.name}: visualName '{ref}' has no matching visual "
                        f"directory",
                        file=bf, obj=bf.stem))
        return out

    @staticmethod
    def _bookmarks_in_scope(ctx: Context) -> list[tuple[Path, Path]]:
        """The bookmark files to read, each with the report folder it is in.

        A report's bookmarks are the files directly under its
        ``definition/bookmarks`` folder: a copy in a sub-folder is not one.
        """
        pairs: list[tuple[Path, Path]] = []
        for report_dir in ctx.report_dirs:
            folder = report_dir / "definition" / "bookmarks"
            if not folder.is_dir():
                continue
            for bf in sorted(folder.glob("*.bookmark.json")):
                if not _is_archived(ctx, bf):
                    pairs.append((bf, report_dir))
        for bf in _direct_bookmarks(ctx):
            report = report_of(bf)
            if report is not None:
                pairs.append((bf, report))
        return pairs


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
            for bf in _bookmark_files(report_dir, ctx):
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
            for bf in _bookmark_files(report_dir, ctx):
                try:
                    original = read_text_file(bf)
                    new_text, removed = strip_illegal_options(original.text)
                    if removed and verified_write(original, new_text):
                        applied.extend(f"{bf.name}: removed options.{k}" for k in removed)
                except EditRefused as exc:
                    ctx.refused_fixes.append(f"{self.id}: {bf}: {exc}")
                except (json.JSONDecodeError, OSError, UnicodeDecodeError):
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


# ---------------------------------------------------------------------------
# Report-definition schema shapes
# ---------------------------------------------------------------------------

PAGES_METADATA_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                         "definition/pagesMetadata/1.1.0/schema.json")


class PagesMetadataSchemaRule(Rule):
    id = "B005"
    name = "pages-metadata-schema"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"accepted_schemas": [PAGES_METADATA_SCHEMA]}
    description = (
        "Opt-in pin of the PBIR pages metadata: definition/pages/pages.json "
        "must exist, declare an accepted $schema (default: the 1.1.0 URL; "
        "accepted_schemas lists the versions your tooling expects) and a "
        "pageOrder array. A missing file or a pageOrder that is not a list "
        "breaks page navigation; an unexpected schema version means the file "
        "was written by a different tool version than the one you validate "
        "against. Unparseable JSON is B004's finding."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        accepted = list(self.options.get("accepted_schemas") or [PAGES_METADATA_SCHEMA])
        for report_dir in ctx.report_dirs:
            pages = report_dir / "definition" / "pages" / "pages.json"
            if not pages.is_file():
                out.append(self.violation(
                    "definition/pages/pages.json is missing; the report has no pages "
                    "metadata. Save the report again from Power BI Desktop (PBIR format).",
                    file=pages, obj=report_dir.name))
                continue
            try:
                data = json.loads(pages.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue  # B004 reports unreadable report JSON
            if not isinstance(data, dict):
                continue
            schema = data.get("$schema")
            if schema not in accepted:
                out.append(self.violation(
                    f"pages.json declares $schema {schema!r}; expected "
                    f"{' or '.join(accepted)}. Update the URL (or add the version to "
                    f"accepted_schemas if your tooling targets it).",
                    file=pages, obj=report_dir.name))
            if not isinstance(data.get("pageOrder"), list):
                out.append(self.violation(
                    "pages.json pageOrder is missing or not a list of page names.",
                    file=pages, obj=report_dir.name))
        return out


def _hierarchy_problems(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key == "HierarchyLevel" and isinstance(value, dict):
                expr = value.get("Expression")
                problems = []
                if not isinstance(expr, dict):
                    problems.append("has no Expression object")
                elif "Level" in expr:
                    problems.append("carries Level inside its Expression")
                if "Level" not in value:
                    problems.append("has no Level next to its Expression")
                if problems:
                    yield here, " and ".join(problems)
            yield from _hierarchy_problems(value, here)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _hierarchy_problems(value, f"{path}[{i}]")


class HierarchyLevelBindingShapeRule(Rule):
    id = "B006"
    name = "hierarchy-level-binding-shape"
    severity = Severity.ERROR
    description = (
        "A visual field bound to a hierarchy level must be written as "
        "HierarchyLevel: {Expression: {Hierarchy: ...}, Level: <name>}: the "
        "Level sits next to the Expression, never inside it. Any other shape "
        "does not match the report definition schema, so the report can fail "
        "to load. Unparseable visual.json files are reported too."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for report_dir in ctx.report_dirs:
            pages = report_dir / "definition" / "pages"
            if not pages.is_dir():
                continue
            for vf in sorted(pages.rglob("visual.json")):
                try:
                    data = json.loads(vf.read_text(encoding="utf-8-sig"))
                except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                    out.append(self.violation(f"visual.json cannot be parsed ({exc}).",
                                              file=vf, obj=vf.parent.name))
                    continue
                for where, problem in _hierarchy_problems(data):
                    out.append(self.violation(
                        f"HierarchyLevel at {where} {problem}; write it as "
                        f"{{Expression: {{Hierarchy: ...}}, Level: ...}}.",
                        file=vf, obj=f"{vf.parent.name}:{where}"))
        return out
