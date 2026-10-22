"""Compare a model manifest with a warehouse schema snapshot.

The snapshot is exported by the user (per warehouse table, a list of
``{"name", "type"}``); this module never connects to a warehouse. A model
column whose warehouse column is gone is the failure that matters (the
refresh breaks in the service); warehouse columns the model does not import
are informational.

Every result is written into the table's own ``bq_source`` object, so the
manifest stays one document: what was checked against, what the warehouse
has, and how the model's columns differ from it.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
from pathlib import Path
from typing import Iterable, Optional

from .manifest import DATA_CLASSES, normalise

NUMERIC_WH = {"INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"}
DATE_WH = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}
BOOL_WH = {"BOOLEAN", "BOOL"}
NUMERIC_MODEL = {"int64", "double", "decimal"}

SNAPSHOT_NOTE = ("Schema snapshot from the dataset above. Standardized *_n tables share a "
                 "schema across orgs, so a dev dataset (e.g. spinout_01_db) is "
                 "representative of the prod baseline.")


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


def target_block(manifest: dict) -> dict:
    """The warehouse target the manifest declares."""
    for key in ("bigquery", "warehouse"):
        block = manifest.get(key)
        if isinstance(block, dict):
            return block
    return {}


def classify_drift(columns: Iterable[str], wh_columns: list[dict], table: str,
                   ignore: Iterable[str] = frozenset(),
                   exceptions: Iterable[tuple[str, str]] = frozenset(),
                   programmatic_renames: bool = False,
                   declared_types: Optional[dict[str, str]] = None,
                   m_type_changed: Optional[Iterable[str]] = None) -> tuple[dict, dict]:
    """``(drift, resolved)``: drift lists (missing_in_bq or needs_review,
    not_surfaced_in_pbi, ignored_bookkeeping, type_mismatch; only non-empty
    keys) and the warehouse type of each matched model column."""
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
        drift["needs_review" if programmatic_renames else "missing_in_bq"] = sorted(unmatched)
    # the snapshot's own spelling of a column name, as the warehouse writes it
    rest = [c["name"] for c in wh_columns if normalise(c["name"]) not in matched_wh]
    bookkeeping = sorted(n for n in rest
                         if normalise(n) in ignore and (table, normalise(n)) not in exc)
    informational = sorted(set(rest) - set(bookkeeping))
    if informational:
        drift["not_surfaced_in_pbi"] = informational
    if bookkeeping:
        drift["ignored_bookkeeping"] = bookkeeping
    mismatches = []
    for col, wtype in sorted(resolved.items()):
        mtype = (declared_types or {}).get(col)
        if mtype and wtype and suspicious_type_pair(mtype, wtype):
            note = ("M Changed Type confirmed — deliberate conversion"
                    if normalise(col) in changed else "no M Changed Type found — verify upstream")
            mismatches.append(f"{col}: PBI {mtype} vs BQ {wtype} ({note})")
    if mismatches:
        drift["type_mismatch"] = mismatches
    return drift, resolved


def reconcile(manifest: dict, snapshot: dict, ignore: Iterable[str] = frozenset(),
              exceptions: Iterable[tuple[str, str]] = frozenset(),
              snapshot_name: str = "", project: Optional[str] = None,
              dataset: Optional[str] = None) -> dict:
    """Annotate a copy of the manifest with per-table drift and a summary."""
    doc = copy.deepcopy(manifest)
    block = target_block(manifest)
    project = project or block.get("project")
    dataset = dataset or block.get("dataset")
    warehouse = block.get("warehouse") or "internal"
    checked = failing = needs_review = informational = type_mismatch = unreachable = 0
    unresolved = []
    backed = 0
    for t in doc.get("tables", []):
        src = t.get("bq_source") or {}
        for key in ("drift", "check_error", "bq_columns", "checked_against"):
            src.pop(key, None)
        for key in ("drift", "error", "unreachable", "bq_columns"):
            t.pop(key, None)
        for c in t.get("columns", []):
            c.pop("bqType", None)
        if t.get("unresolved_source"):
            unresolved.append(t["name"])
            backed += 1
            continue
        name = src.get("table")
        if not name:
            continue
        backed += 1
        src["checked_against"] = f"{project}.{dataset}.{name}"
        wh_cols = snapshot.get(name)
        if wh_cols is None:
            src["check_error"] = f"NotFound: {name} is not in the schema snapshot"
            unreachable += 1
            continue
        src["bq_columns"] = wh_cols
        checked += 1
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
            src["drift"] = drift
        failing += bool(drift.get("missing_in_bq"))
        needs_review += bool(drift.get("needs_review"))
        informational += bool(drift.get("not_surfaced_in_pbi"))
        type_mismatch += bool(drift.get("type_mismatch"))
    skipped = sorted(t["name"] for t in doc.get("tables", [])
                     if t.get("classification") in DATA_CLASSES
                     and not (t.get("bq_source") or {}).get("table"))
    doc["bq_schema_check"] = {
        "project": project,
        "dataset": dataset,
        "warehouse": warehouse,
        "auth": f"schema snapshot {snapshot_name}" if snapshot_name else "schema snapshot",
        "unresolved_sources": sorted(unresolved),
        "skipped_no_source": skipped,
        "checked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tables_checked": checked,
        "tables_failing": failing,
        "tables_needs_review": needs_review,
        "tables_informational": informational,
        "tables_type_mismatch": type_mismatch,
        "tables_unreachable": unreachable,
        "ignored_bookkeeping_columns": sorted({normalise(c) for c in ignore}),
        "note": SNAPSHOT_NOTE,
    }
    return doc


def coverage_gap(doc: dict) -> bool:
    """True when warehouse-backed tables exist and none of them was checked."""
    block = doc.get("bq_schema_check") or {}
    if block.get("unresolved_sources"):
        return True
    backed = any((t.get("bq_source") or {}).get("table") or t.get("unresolved_source")
                 for t in doc.get("tables", []))
    return bool(backed and not block.get("tables_checked"))


def failing(doc: dict) -> bool:
    block = doc.get("bq_schema_check") or {}
    return bool(block.get("tables_failing") or block.get("tables_needs_review")
                or block.get("tables_unreachable") or coverage_gap(doc))
