"""Surgical, verified file edits shared by the fixers.

Every fixer that rewrites a file goes through :func:`verified_write`. The
contract is the same for all of them:

* The edit is computed on the file's text, never by re-serializing a parsed
  object, so the diff a reviewer sees contains only the intended change.
* Before anything is written, a ``verify(old, new)`` callback proves the
  edit did what it claims (for example: both sides parse, and the only
  difference is the removed key). If it raises :class:`EditRefused`, the
  file is left untouched and the violation stays on the report.
* The file must still hold exactly the text the fixer read; a concurrent
  change aborts the write.
* Byte-order mark and newline style are preserved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

_BOM = "﻿"


class EditRefused(RuntimeError):
    """A repair could not be proven safe; nothing was written."""


#: Every edit :func:`verified_write` refused since the last
#: :func:`take_refusals`, as ``(path, reason)``. The fix pass drains it
#: after each fixer, so a refusal a fixer caught and dropped is still
#: reported (exit 2) rather than lost.
_REFUSALS: list[tuple[Path, str]] = []


def take_refusals() -> list[tuple[Path, str]]:
    """The refused edits recorded since the last call; clears the record."""
    out = list(_REFUSALS)
    _REFUSALS.clear()
    return out


@dataclass
class TextFile:
    """A text file's content with its BOM stripped and its newline style noted."""

    path: Path
    text: str
    bom: bool
    newline: str

    def lines(self) -> list[str]:
        return self.text.split(self.newline)

    def join(self, lines: list[str]) -> str:
        return self.newline.join(lines)


def read_text_file(path: Path) -> TextFile:
    raw = Path(path).read_bytes().decode("utf-8")
    bom = raw.startswith(_BOM)
    if bom:
        raw = raw[1:]
    newline = _dominant_newline(raw)
    return TextFile(Path(path), raw, bom, newline)


def _dominant_newline(raw: str) -> str:
    """The file's line-ending style.

    A file whose lines end with a lone CR (no LF) is read line by line like
    any other file: treating it as one line would report a different set of
    findings than the same model with LF.
    """
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    cr = raw.count("\r") - crlf
    if crlf and not lf and not cr:
        return "\r\n"
    if cr and not lf and not crlf:
        return "\r"
    return "\r\n" if crlf else "\n"


def mixed_line_endings(path: Path) -> bool:
    """Does the file mix its line endings?

    A file that mixes them cannot be split on one style and joined on
    another: the lines that use the other style fold into one, and an edit
    computed on that would delete the model. Such a file is read but never
    written.
    """
    try:
        raw = Path(path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    body = raw[1:] if raw.startswith(_BOM) else raw
    crlf = body.count("\r\n")
    lf = body.count("\n") - crlf
    cr = body.count("\r") - crlf
    return sum(1 for n in (crlf, lf, cr) if n) > 1


def dump_json(data: Any, newline: str = "\n") -> str:
    """The document as 2-space JSON with one trailing newline.

    The key order of the document is kept, and a non-ASCII character is
    written literally.
    """
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if newline != "\n":
        text = text.replace("\n", newline)
    return text


def write_json(original: TextFile, data: Any) -> bool:
    """Rewrite the file as 2-space JSON, keeping its byte-order mark.

    The rewrite is proven: the new text must parse to the repaired
    document. Raises :class:`EditRefused` when it does not.
    """
    expected = data

    def verify(_old: str, new: str) -> None:
        try:
            written = json.loads(new)
        except json.JSONDecodeError as exc:
            raise EditRefused(f"the rewritten file is not valid JSON: {exc}") from exc
        if written != expected:
            raise EditRefused("the rewritten file does not hold the repaired document")

    return verified_write(original, dump_json(data, original.newline), verify)


def verified_write(
    original: TextFile,
    new_text: str,
    verify: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Write ``new_text`` over ``original.path`` if, and only if, it is safe.

    Returns True when the file was written, False when there was nothing to
    change. Raises :class:`EditRefused` when ``verify`` rejects the edit or
    the file changed since it was read.
    """
    try:
        return _verified_write(original, new_text, verify)
    except EditRefused as exc:
        _REFUSALS.append((original.path, str(exc)))
        raise


def _verified_write(
    original: TextFile,
    new_text: str,
    verify: Optional[Callable[[str, str], None]],
) -> bool:
    if new_text == original.text:
        return False
    if mixed_line_endings(original.path):
        # A file that mixes its line endings cannot be rewritten safely:
        # the edit was computed on a text whose lines had folded together.
        # The file is left exactly as it is.
        raise EditRefused(
            f"{original.path.name} mixes its line endings; it was left "
            f"untouched (normalize it to one style first)")
    if verify is not None:
        verify(original.text, new_text)
    current = read_text_file(original.path)
    if current.text != original.text or current.bom != original.bom:
        raise EditRefused(f"{original.path.name} changed while it was being fixed")
    payload = (_BOM if original.bom else "") + new_text
    original.path.write_bytes(payload.encode("utf-8"))
    return True
