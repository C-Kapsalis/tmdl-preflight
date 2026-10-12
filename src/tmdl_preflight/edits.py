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

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_BOM = "﻿"


class EditRefused(RuntimeError):
    """A repair could not be proven safe; nothing was written."""


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
    newline = "\r\n" if "\r\n" in raw else "\n"
    return TextFile(Path(path), raw, bom, newline)


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
    if new_text == original.text:
        return False
    if verify is not None:
        verify(original.text, new_text)
    current = read_text_file(original.path)
    if current.text != original.text or current.bom != original.bom:
        raise EditRefused(f"{original.path.name} changed while it was being fixed")
    payload = (_BOM if original.bom else "") + new_text
    original.path.write_bytes(payload.encode("utf-8"))
    return True
