"""Ticket references in comments (S004) and the scanner the
``comment-refs`` command shares with it."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from ..ratchet import RatchetFileError, entry_for, load_floors
from .base import Context, Rule, Severity, Violation

TICKET_RE = re.compile(r"#\d+(?!\w)")
CLASSES = ("description", "inline")
#: Folders the scanner never reads. ``tests/`` holds the stand-in models, not
#: the client's, and a reference there is nobody's backlog.
DEFAULT_EXCLUDES = ("tests/**",)


@dataclass
class TicketRef:
    file: Path
    line: int
    cls: str  # "description" or "inline"
    ref: str
    text: str
    #: the model the file belongs to (the folder key of the scan root)
    model: str = ""


#: A string literal: a pair of double quotes on one line. An unclosed quote
#: masks nothing, so a comment behind it still counts.
_STRING_RE = re.compile(r'"[^"\n]*"')


def _mask_strings(raw: str) -> str:
    """Blank out every paired string literal, keeping the line's length."""
    return _STRING_RE.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', raw)


def comment_text(lines: list[str]) -> Iterator[tuple[int, str, str]]:
    """``(line number, class, comment text)`` for every comment in a file.

    A line starting with ``///`` (outside a block comment) is a
    description. Elsewhere a character scan collects ``--`` / ``//`` line
    comments and ``/* */`` blocks (which may span lines) as inline text.
    Only a *paired* double quote masks text, so an unclosed quote does not
    hide a comment that follows it.
    """
    in_block = False
    for number, raw in enumerate(lines, start=1):
        if not in_block and raw.lstrip().startswith("///"):
            yield number, "description", raw.lstrip()[3:]
            continue
        line = _mask_strings(raw)
        pos = 0
        while pos < len(line):
            if in_block:
                end = line.find("*/", pos)
                if end < 0:
                    yield number, "inline", line[pos:]
                    break
                yield number, "inline", line[pos:end]
                in_block = False
                pos = end + 2
                continue
            starts = [i for i in (line.find("--", pos), line.find("//", pos),
                                  line.find("/*", pos)) if i >= 0]
            if not starts:
                break
            first = min(starts)
            if line[first:first + 2] == "/*":
                in_block = True
                pos = first + 2
                continue
            yield number, "inline", line[first + 2:]
            break


def scan_ticket_refs(path: Path, text: str) -> Iterator[TicketRef]:
    """Ticket references in one file's comments, by class."""
    lines = text.splitlines()
    for number, cls, body in comment_text(lines):
        for m in TICKET_RE.finditer(body):
            yield TicketRef(path, number, cls, m.group(0), lines[number - 1].strip())


def model_ticket_refs(definition_dir: Path, ctx: Context | None = None) -> list[TicketRef]:
    refs: list[TicketRef] = []
    for f in sorted(Path(definition_dir).rglob("*.tmdl")):
        if ctx is not None and ctx.is_excluded(f):
            continue
        try:
            text = f.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        refs.extend(scan_ticket_refs(f, text))
    return refs


def count_by_class(refs: list[TicketRef]) -> dict[str, int]:
    return {c: sum(1 for r in refs if r.cls == c) for c in CLASSES}


# ---------------------------------------------------------------------------
# The scan root
# ---------------------------------------------------------------------------


def _git_root(root: Path) -> Optional[Path]:
    """The folder holding the ``.git`` of the work tree ``root`` sits in."""
    for folder in (root, *root.parents):
        if (folder / ".git").exists():
            return folder
    return None


def _tracked_files(root: Path) -> Optional[list[Path]]:
    """The tracked ``*.tmdl`` files under ``root``, or None when the tree is
    not a git work tree (or git is not available)."""
    top = _git_root(root)
    if top is None:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(top), "ls-files", "-z", "--", "*.tmdl"],
            check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    files = []
    for rel in out.stdout.decode("utf-8", "replace").split("\0"):
        if not rel:
            continue
        path = top / rel
        try:
            path.relative_to(root)
        except ValueError:
            continue
        files.append(path)
    return files


def _walked_files(root: Path) -> list[Path]:
    """Every ``*.tmdl`` under ``root``, without the version-control and
    assistant folders."""
    files = []
    for path in sorted(root.rglob("*.tmdl")):
        parts = path.relative_to(root).parts
        if ".git" in parts or ".claude" in parts:
            continue
        files.append(path)
    return files


def model_key_for(path: Path, root: Path) -> str:
    """The folder key of the model a file belongs to: the ``*.SemanticModel``
    folder relative to the scan root, or the file's first folder under it."""
    rel = path.relative_to(root)
    parts = rel.parts
    for index, part in enumerate(parts):
        if part.endswith(".SemanticModel"):
            return "/".join(parts[:index + 1])
    return parts[0] if len(parts) > 1 else "."


def root_ticket_refs(root: Path, ctx: Optional[Context] = None) -> list[TicketRef]:
    """Every ticket reference under the scan root, in file order.

    The scan reads the whole root, not only the model definition folders: a
    ``*.tmdl`` outside a model belongs to the folder it sits in. In a git
    work tree only tracked files are read; elsewhere the folder is walked.
    """
    from ..config import glob_match

    root = Path(root)
    files = _tracked_files(root)
    if files is None:
        files = _walked_files(root)
    refs: list[TicketRef] = []
    for f in sorted(files):
        rel = f.relative_to(root)
        if any(glob_match(pattern, rel.as_posix()) for pattern in DEFAULT_EXCLUDES):
            continue
        if ctx is not None and ctx.is_excluded(f):
            continue
        try:
            text = f.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        key = model_key_for(f, root)
        for ref in scan_ticket_refs(f, text):
            ref.model = key
            refs.append(ref)
    return refs


class CommentTicketRefsRule(Rule):
    id = "S004"
    name = "comment-ticket-refs"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"floors": None}
    description = (
        "Ticket numbers in model comments (#365, org/repo#12) mean nothing to "
        "the people reading the model and go stale; /// descriptions are the "
        "tooltips report users see. Ratcheted per model and class "
        "(description, inline) against a 'floors' file: a count above its "
        "floor fails, a missing file or entry means a floor of 0, and a "
        "count below its floor prints a tighten hint ('tmdl-preflight "
        "comment-refs --tighten'). Colours such as #FF00AA and names such as "
        "#Report Measures are not references. Opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        floors: dict = {}
        if self.options.get("floors"):
            try:
                floors = load_floors(self.options["floors"], missing_ok=True)
            except RatchetFileError as exc:
                return [self.violation(str(exc))]
        for model in ctx.models:
            key = ctx.model_key(model)
            refs = model_ticket_refs(model.definition_path, ctx)
            counts = count_by_class(refs)
            _found, entry = entry_for(floors, key)
            entry = entry or {}
            for cls in CLASSES:
                floor = int(entry.get(cls, 0))
                if counts[cls] > floor:
                    hits = [r for r in refs if r.cls == cls]
                    listing = "; ".join(f"{r.file.name}:{r.line} {r.ref}" for r in hits[:40])
                    out.append(self.violation(
                        f"{key}: {counts[cls]} ticket reference(s) in {cls} comments, above "
                        f"the floor of {floor} ({listing}). Explain the model in the "
                        f"comment and cite the ticket in the commit instead.",
                        file=hits[0].file if hits else None,
                        line=hits[0].line if hits else None,
                        obj=f"{key}:{cls}",
                    ))
                elif counts[cls] < floor:
                    ctx.notes.append(
                        f"comment-ticket-refs: {key}: {cls} references fell to "
                        f"{counts[cls]} (floor {floor}); run 'tmdl-preflight comment-refs "
                        f"--floors FILE --tighten' to lower the floor."
                    )
        return out
