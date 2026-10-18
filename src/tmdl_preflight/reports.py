"""Read-only reports: ``tmdl-preflight report complexity|nameof|relationships``.

Reports never judge and never write; they give a reviewer the numbers
(measure length distribution, NAMEOF inventory, relationship topology) a
threshold or a refactor would be based on.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from .model import SemanticModel

# ---------------------------------------------------------------------------
# complexity
# ---------------------------------------------------------------------------

_BUCKETS = [
    ("Tiny", 0, 100), ("Small", 100, 500), ("Medium", 500, 1000),
    ("Large", 1000, 5000), ("Very Large", 5000, 10000), ("Huge", 10000, None),
]


def _depth(expr: str) -> int:
    level = top = 0
    for ch in expr:
        if ch == "(":
            level += 1
            top = max(top, level)
        elif ch == ")":
            level -= 1
    return top


def _count(upper: str, word: str) -> int:
    return upper.count(word)


def complexity(models: list[SemanticModel], top: int = 10,
               helper_prefixes=("-",), core_prefixes=("^", "!")) -> dict[str, Any]:
    rows = []
    for model in models:
        for t in sorted(model.table_list, key=lambda t: t.file.name):
            for m in t.measure_list:
                if not m.expression.strip():
                    continue
                expr = m.expression
                up = expr.upper()
                rows.append({
                    "table": t.name, "measure": m.name,
                    "length": len(expr),
                    "lines": expr.count("\n") + 1,
                    "var_count": _count(up, "VAR "),
                    "calculate_count": _count(up, "CALCULATE"),
                    "filter_count": _count(up, "FILTER"),
                    "sumx_count": _count(up, "SUMX"),
                    "switch_count": _count(up, "SWITCH"),
                    "max_nesting_depth": _depth(expr),
                    "is_helper": m.name.startswith(tuple(helper_prefixes)),
                    "is_core": m.name.startswith(tuple(core_prefixes)),
                })
    n = len(rows)
    lengths = sorted(r["length"] for r in rows)

    def pct(p: float) -> int:
        if not lengths:
            return 0
        return lengths[n // 2] if p == 0.5 else lengths[min(n - 1, int(n * p))]

    stats = {
        "avg_length": round(sum(lengths) / n, 1) if n else 0,
        "min_length": lengths[0] if n else 0,
        "max_length": lengths[-1] if n else 0,
        "p50": pct(0.5), "p75": pct(0.75), "p90": pct(0.9), "p95": pct(0.95), "p99": pct(0.99),
        "avg_nesting_depth": round(sum(r["max_nesting_depth"] for r in rows) / n, 1) if n else 0,
        "max_nesting_depth": max((r["max_nesting_depth"] for r in rows), default=0),
        "avg_var_count": round(sum(r["var_count"] for r in rows) / n, 1) if n else 0,
        "max_var_count": max((r["var_count"] for r in rows), default=0),
    }
    buckets = []
    for label, lo, hi in _BUCKETS:
        count = sum(1 for x in lengths if x >= lo and (hi is None or x < hi))
        buckets.append({"bucket": label, "count": count,
                        "share": round(100.0 * count / n, 1) if n else 0.0})
    ranked = sorted(enumerate(rows), key=lambda kv: (-kv[1]["length"], kv[0]))[:top]
    top_rows = [dict(r, flagged=r["length"] > 10000) for _i, r in ranked]
    thresholds = {
        "strict_max_length": stats["p95"],
        "relaxed_max_length": stats["p99"],
        "core_max_length": stats["p90"],
        "helper_max_length": stats["p95"],
        "critical_length": stats["p99"],
        "max_nesting": min(stats["max_nesting_depth"] + 2, 20),
        "max_vars": min(stats["max_var_count"] + 5, 25),
    }
    blocks = [b for model in models for b in model.dax_blocks()
              if b.kind in ("measure", "calculated_column") and b.expression.strip()]
    lens = [len(b.expression) for b in blocks]
    expressions = {
        "total_expressions": len(blocks),
        "measures": sum(1 for b in blocks if b.kind == "measure"),
        "calculated_columns": sum(1 for b in blocks if b.kind == "calculated_column"),
        "avg_length": round(sum(lens) / len(lens), 1) if lens else 0,
        "min_length": min(lens, default=0),
        "max_length": max(lens, default=0),
        "total_characters": sum(lens),
    }
    payload = {
        "total_measures": n,
        "statistics": stats,
        "buckets": buckets,
        "top": top_rows,
        "thresholds": thresholds,
        "expressions": expressions,
        "measures": rows,
    }
    # flat copies of the expression block for quick reads ("measures" stays
    # the per-measure list)
    payload.update({k: v for k, v in expressions.items() if k != "measures"})
    return payload


def render_complexity(data: dict) -> str:
    s, e = data["statistics"], data["expressions"]
    lines = [
        f"measures: {data['total_measures']}",
        f"  length avg {s['avg_length']}, min {s['min_length']}, max {s['max_length']}",
        f"  percentiles p50 {s['p50']}, p75 {s['p75']}, p90 {s['p90']}, p95 {s['p95']}, p99 {s['p99']}",
        f"  nesting avg {s['avg_nesting_depth']}, max {s['max_nesting_depth']}; "
        f"VARs avg {s['avg_var_count']}, max {s['max_var_count']}",
        "length buckets:",
    ]
    lines += [f"  {b['bucket']}: {b['count']} ({b['share']}%)" for b in data["buckets"]]
    lines.append("longest measures:")
    lines += [f"  {r['table']}[{r['measure']}]: {r['length']}" + ("  (over 10000)" if r["flagged"] else "")
              for r in data["top"]]
    lines.append("suggested thresholds (advisory):")
    lines += [f"  {k}: {v}" for k, v in data["thresholds"].items()]
    lines.append(
        f"expressions: {e['total_expressions']} ({e['measures']} measures, "
        f"{e['calculated_columns']} calculated columns), avg {e['avg_length']}, "
        f"min {e['min_length']}, max {e['max_length']}, total {e['total_characters']} characters"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# relationships
# ---------------------------------------------------------------------------

_PARAM_RE = re.compile(r"^[xy]-(?:Selector \d+|Plot Specific(?: \d+)?)$")


def relationships(model: SemanticModel, parameter_markers: Optional[list[str]] = None) -> dict:
    rels = list(model.relationships)
    stems = sorted(p.stem for p in (model.definition_path / "tables").glob("*.tmdl"))
    related: set[str] = set()
    endpoints: Counter = Counter()
    for r in rels:
        related |= {r.from_table, r.to_table}
        endpoints[r.from_table] += 1
        endpoints[r.to_table] += 1
    bidir = [r for r in rels if r.cross_filtering == "bothDirections"]
    orphans = [s for s in stems if s not in related]
    markers = parameter_markers or []

    def is_param(name: str) -> bool:
        return bool(_PARAM_RE.match(name)) or any(m in name for m in markers)

    params = sorted(o for o in orphans if is_param(o))
    selectors = sorted(o for o in orphans if o not in params
                       and ("selector" in o.lower() or o.startswith("z-")))
    other = sorted(o for o in orphans if o not in params and o not in selectors)
    return {
        "total_relationships": len(rels),
        "active_relationships": sum(1 for r in rels if r.is_active),
        "inactive_relationships": sum(1 for r in rels if not r.is_active),
        "cardinality_types": dict(sorted(Counter(
            f"{r.from_cardinality}_to_{r.to_cardinality}" for r in rels).items())),
        "cross_filtering": {"unidirectional": len(rels) - len(bidir), "bidirectional": len(bidir)},
        "bidirectional_relationships": [
            {"from": f"{r.from_table}[{r.from_column}]", "to": f"{r.to_table}[{r.to_column}]",
             "id": r.rel_id} for r in bidir
        ],
        "tables": {"total": len(stems), "with_relationships": len(related), "orphans": len(orphans)},
        "orphan_categories": {"parameter_tables": params, "selector_tables": selectors,
                              "other_orphans": other},
        "hub_tables": [{"table": t, "relationship_count": n}
                       for t, n in sorted(endpoints.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
    }


def render_relationships(data: dict) -> str:
    lines = [
        f"relationships: {data['total_relationships']} ({data['active_relationships']} active, "
        f"{data['inactive_relationships']} inactive)",
        "cardinality: " + (", ".join(f"{k} {v}" for k, v in data["cardinality_types"].items()) or "none"),
        f"cross filtering: {data['cross_filtering']['unidirectional']} one direction, "
        f"{data['cross_filtering']['bidirectional']} both directions",
    ]
    for b in data["bidirectional_relationships"]:
        lines.append(f"  both directions: {b['from']} -> {b['to']} ({b['id']})")
    t = data["tables"]
    lines.append(f"tables: {t['total']}, {t['with_relationships']} in relationships, "
                 f"{t['orphans']} unrelated")
    for key, label in (("parameter_tables", "parameter"), ("selector_tables", "selector"),
                       ("other_orphans", "other")):
        names = data["orphan_categories"][key]
        if names:
            lines.append(f"  unrelated {label} tables: {', '.join(names)}")
    lines.append("hub tables: " + ", ".join(
        f"{h['table']} ({h['relationship_count']})" for h in data["hub_tables"]))
    return "\n".join(lines)
