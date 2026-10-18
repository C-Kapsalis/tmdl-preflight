"""Ticket references in comments (S004) and the scanner the
``comment-refs`` command shares with it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..ratchet import RatchetFileError, entry_for, load_floors
from .base import Context, Rule, Severity, Violation

TICKET_RE = re.compile(r"#\d+(?!\w)")
CLASSES = ("description", "inline")


@dataclass
class TicketRef:
    file: Path
    line: int
    cls: str  # "description" or "inline"
    ref: str
    text: str


def comment_text(lines: list[str]) -> Iterator[tuple[int, str, str]]:
    """``(line number, class, comment text)`` for every comment in a file.

    A line starting with ``///`` (outside a block comment) is a
    description. Elsewhere a character scan skips double-quoted strings and
    collects ``--`` / ``//`` line comments and ``/* */`` blocks (which may
    span lines) as inline text.
    """
    in_block = False
    for number, raw in enumerate(lines, start=1):
        if not in_block and raw.lstrip().startswith("///"):
            yield number, "description", raw.lstrip()[3:]
            continue
        collected: list[str] = []
        quoted = False
        k = 0
        while k < len(raw):
            pair = raw[k:k + 2]
            if in_block:
                if pair == "*/":
                    in_block = False
                    collected.append(" ")
                    k += 2
                else:
                    collected.append(raw[k])
                    k += 1
            elif quoted:
                quoted = raw[k] != '"'
                k += 1
            elif raw[k] == '"':
                quoted = True
                k += 1
            elif pair in ("--", "//"):
                collected.append(raw[k + 2:])
                break
            elif pair == "/*":
                in_block = True
                k += 2
            else:
                k += 1
        if collected:
            yield number, "inline", "".join(collected)


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
