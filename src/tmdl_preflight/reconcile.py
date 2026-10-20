"""Compare a model manifest with a warehouse schema snapshot.

The snapshot is exported by the user (per warehouse table, a list of
``{"name", "type"}``); this module never connects to a warehouse. A model
column whose warehouse column is gone is the failure that matters (the
refresh breaks in the service); warehouse columns the model does not import
are informational.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from .manifest import normalise

NUMERIC_WH = {"INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"}
DATE_WH = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}
BOOL_WH = {"BOOLEAN", "BOOL"}
NUMERIC_MODEL = {"int64", "double", "decimal"}


def suspicious_type_pair(model_type: str, wh_type: str) -> bool:
    m, w = (model_type or "").lower(), (wh_type or "").upper()
    m_num, w_num = m in NUMERIC_MODEL, w in NUMERIC_WH
    if m_num and w == "STRING":
        return True
    if m == "string" and w_num:
        return True
    if (m == "boolean") != (w in BOOL_WH):
        return True
    if m == "datetime" and w_num:
        return True
    return m_num and w in DATE_WH


def load_ignore_columns(path: Optional[Path]) -> tuple[set[str], set[tuple[str, str]]]:
    """``(ignored column names, {(table, column)} exceptions)``; a missing
    file means nothing is ignored."""
    if path is None:
        return set(), set()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return set(), set()
    cols = {normalise(c) for c in data.get("columns") or [] if isinstance(c, str)}
    exc = {(str(e[0]), normalise(str(e[1]))) for e in data.get("exceptions") or []
           if isinstance(e, (list, tuple)) and len(e) == 2}
    return cols, exc


def classify_drift(columns: Iterable[str], wh_columns: list[dict], table: str,
                   ignore: Iterable[str] = frozenset(),
                   exceptions: Iterable[tuple[str, str]] = frozenset(),
                   programmatic_renames: bool = False,
                   declared_types: Optional[dict[str, str]] = None,
                   m_type_changed: Optional[Iterable[str]] = None) -> tuple[dict, dict]:
    """``(drift, resolved)``: drift lists (missing_in_source or needs_review,
    not_imported, ignored_bookkeeping, type_mismatch; only non-empty keys)
    and the warehouse type of each matched model column."""
    wh = {normalise(c["name"]): c.get("type") for c in wh_columns}
    ignore = {normalise(c) for c in ignore}
    exc = {(t, normalise(c)) for t, c in exceptions}
    changed = {normalise(c) for c in (m_type_changed or ())}
    resolved: dict[str, str] = {}
    matched_wh: set[str] = set()
    unmatched: list[str] = []
    for col in columns:
        key = normalise(col)
        hit = key if key in wh else None
        if hit is None and "." in key:
            head, leaf = key.split(".", 1)[0], key.rsplit(".", 1)[-1]
            hit = head if head in wh else (leaf if leaf in wh else None)
        if hit is None:
            unmatched.append(col)
            continue
        matched_wh.add(hit)
        resolved[col] = wh[hit]
    drift: dict[str, list[str]] = {}
    if unmatched:
        drift["needs_review" if programmatic_renames else "missing_in_source"] = sorted(unmatched)
    rest = [n for n in wh if n not in matched_wh]
    bookkeeping = sorted(n for n in rest if n in ignore and (table, n) not in exc)
    informational = sorted(n for n in rest if n not in bookkeeping)
    if informational:
        drift["not_imported"] = informational
    if bookkeeping:
        drift["ignored_bookkeeping"] = bookkeeping
    mismatches = []
    for col, wtype in resolved.items():
        mtype = (declared_types or {}).get(col)
        if mtype and wtype and suspicious_type_pair(mtype, wtype):
            note = ("M Changed Type confirmed" if normalise(col) in changed
                    else "no M Changed Type found")
            mismatches.append(f"{col}: model {mtype} vs warehouse {wtype} ({note})")
    if mismatches:
        drift["type_mismatch"] = sorted(mismatches)
    return drift, resolved


def reconcile(manifest: dict, snapshot: dict, ignore: Iterable[str] = frozenset(),
              exceptions: Iterable[tuple[str, str]] = frozenset(),
              snapshot_name: str = "") -> dict:
    """Annotate a copy of the manifest with per-table drift and a summary."""
    import copy

    doc = copy.deepcopy(manifest)
    counts = {"checked": 0, "failing": 0, "needs_review": 0, "informational": 0,
              "type_mismatch": 0, "unreachable": 0}
    unresolved, skipped = [], []
    backed = 0
    for t in doc.get("tables", []):
        for key in ("drift", "error", "unreachable", "bq_columns"):
            t.pop(key, None)
        for c in t.get("columns", []):
            c.pop("bqType", None)
        if t.get("unresolved_source"):
            unresolved.append(t["name"])
            backed += 1
            continue
        src = (t.get("bq_source") or {}).get("table")
        if not src:
            if t.get("classification") in ("fact", "dimension", "calendar"):
                skipped.append(t["name"])
            continue
        backed += 1
        wh_cols = snapshot.get(src)
        if wh_cols is None:
            t["error"] = f"{src} is not in the schema snapshot"
            t["unreachable"] = True
            counts["unreachable"] += 1
            continue
        counts["checked"] += 1
        t["bq_columns"] = wh_cols
        sourced = [c for c in t.get("columns", []) if c.get("bqColumn") and not c.get("calculated")]
        declared = {c["bqColumn"]: c.get("dataType") for c in sourced if c.get("dataType")}
        m_changed = set()
        for k in (t.get("m_type_changes") or {}):
            m_changed.add(normalise(k))
        changed = {c["bqColumn"] for c in sourced
                   if {normalise(c["bqColumn"]), normalise(c["name"]),
                       normalise(c.get("sourceColumn") or "")} & m_changed}
        drift, resolved = classify_drift([c["bqColumn"] for c in sourced], wh_cols, t["name"],
                                         ignore, exceptions, bool(t.get("programmatic_renames")),
                                         declared, changed)
        for c in sourced:
            if c["bqColumn"] in resolved:
                c["bqType"] = resolved[c["bqColumn"]]
        if drift:
            t["drift"] = drift
        counts["failing"] += bool(drift.get("missing_in_source"))
        counts["needs_review"] += bool(drift.get("needs_review"))
        counts["informational"] += bool(drift.get("not_imported"))
        counts["type_mismatch"] += bool(drift.get("type_mismatch"))
    gap = bool(unresolved) or (backed > 0 and counts["checked"] == 0)
    doc["schema_check"] = {
        "snapshot": snapshot_name,
        "unresolved_source_tables": unresolved,
        "skipped_without_source": skipped,
        "counts": counts,
        "ignored_columns": sorted({normalise(c) for c in ignore}),
        "coverage_gap": gap,
        "note": None if backed else "the model has no warehouse-backed table",
    }
    return doc


def failing(doc: dict) -> bool:
    sc = doc.get("schema_check") or {}
    c = sc.get("counts") or {}
    return bool(c.get("failing") or c.get("needs_review") or c.get("unreachable")
                or sc.get("coverage_gap"))
