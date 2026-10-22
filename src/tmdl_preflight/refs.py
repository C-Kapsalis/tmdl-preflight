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
    return re.compile(r"\[" + n + r"\]" + r'|"' + n + r'"' + r'|"[^"]*\.' + n + r'"')


def _tracked(root: Path) -> Optional[list[Path]]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                             timeout=60, check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return [root / p for p in out.split("\0") if p]


def scan_files(paths: Iterable[Path]) -> list[tuple[Path, Path]]:
    """``(file, root)`` for every candidate file under the given roots."""
    files: list[tuple[Path, Path]] = []
    for root in paths:
        root = Path(root)
        if root.is_file():
            files.append((root, root.parent))
            continue
        tracked = _tracked(root)
        cands = tracked if tracked is not None else list(root.rglob("*"))
        files.extend((p, root) for p in cands
                     if p.suffix in (".tmdl", ".json") and p.is_file())
    return sorted(set(files))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass
class FileCount:
    path: Path
    count: int
    layer: str  # model | report
    scope: str  # live | non-live
    rel: str = ""


def live_roots(targets: dict[str, dict]) -> set[str]:
    """The first path segment of every registered model path: the live set."""
    roots: set[str] = set()
    for entry in targets.values():
        for path in [entry.get("model_path")] + [s.get("path")
                                                 for s in entry.get("secondary_models") or []]:
            if path:
                roots.add(str(path).replace("\\", "/").strip("/").split("/")[0])
    return roots


def census(name: str, paths: Iterable[Path], history: Optional[list[str]] = None,
           loose: bool = False, live: Optional[set[str]] = None) -> list[FileCount]:
    """The files that name the object, with the layer and the scope."""
    rx = reference_pattern(name, loose)
    globs = history if history is not None else HISTORY_GLOBS
    out = []
    for f, root in scan_files(paths):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = len(rx.findall(text))
        if not n:
            continue
        rel = _relative(f, root)
        layer = "report" if ".Report/" in rel else "model"
        if live is not None:
            scope = "live" if rel.split("/")[0] in live else "non-live"
        else:
            scope = ("non-live" if any(fnmatchcase(rel, "*" + g if not g.startswith("*") else g)
                                      for g in globs) else "live")
        out.append(FileCount(f, n, layer, scope, rel))
    return out


def render(name: str, counts: list[FileCount], loose: bool, files: bool,
           include_nonlive: bool) -> str:
    shape = (f'`{name}]` / `{name}"` — LOOSE, also counts measures whose name ENDS with this one'
             if loose else f'`[{name}]`, `"{name}"` or `"Table.{name}"`')
    live = [c for c in counts if c.scope == "live"]
    other = [c for c in counts if c.scope == "non-live"]
    lm = sum(c.count for c in live if c.layer == "model")
    lr = sum(c.count for c in live if c.layer == "report")
    nm = sum(c.count for c in other if c.layer == "model")
    nr = sum(c.count for c in other if c.layer == "report")
    warning = f"⚠ {lr} are report bindings no model-side test checks." if lr else ""
    lines = ["", f'References to "{name}"  (matched as {shape})', "",
             f"  LIVE      model {lm:>5}   report {lr:>5}   total {lm + lr:>5}   "
             f"files {len(live)}",
             f"  non-live  model {nm:>5}   report {nr:>5}   total {nm + nr:>5}   "
             f"files {len(other)}",
             "",
             f"  Live blast radius: {lm + lr} reference(s). {warning}"]
    if not (lm + lr + nm + nr):
        lines.append("  (no references found — check the exact name, including case)")
    if files:
        lines.append("")
        shown = [c for c in counts if include_nonlive or c.scope == "live"]
        for c in sorted(shown, key=lambda c: (-c.count, c.rel)):
            lines.append(f"  {c.count:>4}  {c.scope:<8} {c.layer:<6} {c.rel}")
        if not include_nonlive and (nm + nr):
            lines.append("")
            lines.append(f"  ({len(other)} non-live file(s) hidden — --include-nonlive to show)")
    lines.append("")
    return "\n".join(lines)
