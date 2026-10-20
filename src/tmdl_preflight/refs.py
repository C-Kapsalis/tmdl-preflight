"""Reference census: how many places name an object, model side and report
side, before it is renamed or deleted (``tmdl-preflight refs``)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterable, Optional

HISTORY_GLOBS = ["*_backup/*", "*_legacy/*", "*_b2/*", "legacy/*", "*/legacy/*"]


def reference_pattern(name: str, loose: bool = False) -> re.Pattern:
    n = re.escape(name)
    if loose:
        return re.compile(n + r"\]|" + n + r'"')
    return re.compile(r"\[" + n + r"\]" + r'|"' + n + r'"' + r'|"[^".]+\.' + n + r'"')


def _tracked(root: Path) -> Optional[list[Path]]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                             timeout=60, check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return [root / p for p in out.split("\0") if p]


def scan_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in paths:
        root = Path(root)
        if root.is_file():
            files.append(root)
            continue
        tracked = _tracked(root)
        cands = tracked if tracked is not None else list(root.rglob("*"))
        files.extend(p for p in cands if p.suffix in (".tmdl", ".json") and p.is_file())
    return sorted(set(files))


@dataclass
class FileCount:
    path: Path
    count: int
    layer: str  # model | report
    scope: str  # live | history


def census(name: str, paths: Iterable[Path], history: Optional[list[str]] = None,
           loose: bool = False) -> list[FileCount]:
    rx = reference_pattern(name, loose)
    globs = history if history is not None else HISTORY_GLOBS
    out = []
    for f in scan_files(paths):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = len(rx.findall(text))
        if not n:
            continue
        posix = f.as_posix()
        layer = "report" if ".Report/" in posix else "model"
        scope = "history" if any(fnmatchcase(posix, "*" + g if not g.startswith("*") else g)
                                 for g in globs) else "live"
        out.append(FileCount(f, n, layer, scope))
    return out


def render(name: str, counts: list[FileCount], loose: bool, files: bool,
           include_history: bool) -> str:
    shape = ("loose: NAME] or NAME\" (over-counts)" if loose
             else '[NAME], "NAME" or "Table.NAME"')
    lines = [f"references to {name!r} (shape: {shape})"]
    for scope in ("live", "history"):
        sel = [c for c in counts if c.scope == scope]
        model = sum(c.count for c in sel if c.layer == "model")
        report = sum(c.count for c in sel if c.layer == "report")
        lines.append(f"{scope}: model {model}, report {report}, total {model + report} "
                     f"in {len(sel)} file(s)")
    live = [c for c in counts if c.scope == "live"]
    lines.append(f"live blast radius: {sum(c.count for c in live)}")
    rep = sum(c.count for c in live if c.layer == "report")
    if rep:
        lines.append(f"warning: {rep} report reference(s); model-side checks cannot see them")
    if not counts:
        lines.append("no references found: check the exact spelling and case of the name")
    if files:
        shown = [c for c in counts if include_history or c.scope == "live"]
        for c in sorted(shown, key=lambda c: (-c.count, c.path.as_posix())):
            lines.append(f"  {c.count:5d}  {c.scope:7s}  {c.layer:6s}  {c.path}")
        hidden = len(counts) - len(shown)
        if hidden:
            lines.append(f"  ({hidden} history file(s) hidden; --include-history shows them)")
    return "\n".join(lines)
