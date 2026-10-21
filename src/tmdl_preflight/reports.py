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


def _measure_length(expression: str) -> int:
    """The length of an expression as a reviewer counts it: the first line
    without the indentation it carried in the file, the later lines with it.

    The line breaks still count, so the length of a multi-line measure is the
    length of its text.
    """
    head, _, tail = expression.partition("\n")
    return len(head.lstrip()) + len(tail) + (1 if _ else 0)


def complexity(models: list[SemanticModel], top: int = 10,
               helper_prefixes=("-",), core_prefixes=("^", "!")) -> dict[str, Any]:
    rows = []
    tables = 0
    for model in models:
        for t in sorted(model.table_list, key=lambda t: t.file.name):
            tables += 1
            for m in t.measure_list:
                if not m.expression.strip():
                    continue
                expr = m.expression
                up = expr.upper()
                rows.append({
                    "table": t.name,
                    "measure": m.name,
                    "full_name": f"{t.name}[{m.name}]",
                    "is_helper": m.name.startswith(tuple(helper_prefixes)),
                    "is_core": m.name.startswith(tuple(core_prefixes)),
                    "length": _measure_length(expr),
                    "lines": expr.count("\n") + 1,
                    "var_count": _count(up, "VAR "),
                    "calculate_count": _count(up, "CALCULATE"),
                    "filter_count": _count(up, "FILTER"),
                    "sumx_count": _count(up, "SUMX"),
                    "switch_count": _count(up, "SWITCH"),
                    "max_nesting_depth": _depth(expr),
                })
    n = len(rows)
    lengths = sorted(r["length"] for r in rows)

    def pct(p: float) -> int:
        if not lengths:
            return 0
        return lengths[n // 2] if p == 0.5 else lengths[min(n - 1, int(n * p))]

    stats = {
        "avg_length": (sum(lengths) / n) if n else 0,
        "min_length": lengths[0] if lengths else 0,
        "max_length": lengths[-1] if lengths else 0,
        "median_length": pct(0.5),
        "p75_length": pct(0.75), "p90_length": pct(0.90),
        "p95_length": pct(0.95), "p99_length": pct(0.99),
        "avg_nesting_depth": (sum(r["max_nesting_depth"] for r in rows) / n) if n else 0,
        "max_nesting_depth": max((r["max_nesting_depth"] for r in rows), default=0),
        "avg_var_count": (sum(r["var_count"] for r in rows) / n) if n else 0,
        "max_var_count": max((r["var_count"] for r in rows), default=0),
    }
    ranked = sorted(enumerate(rows), key=lambda kv: (-kv[1]["length"], kv[0]))
    top_rows = [dict(r) for _i, r in ranked[:top]]
    rows = [dict(r) for _i, r in ranked]
    blocks = [b for model in models for b in model.dax_blocks()
              if b.kind in ("measure", "calculated_column") and b.expression.strip()]
    lens = [_measure_length(b.expression) for b in blocks]
    expressions = {
        "total_expressions": len(blocks),
        "measures": sum(1 for b in blocks if b.kind == "measure"),
        "calculated_columns": sum(1 for b in blocks if b.kind == "calculated_column"),
        "avg_length": (sum(lens) / len(lens)) if lens else 0,
        "min_length": min(lens, default=0),
        "max_length": max(lens, default=0),
        "total_characters": sum(lens),
    }
    return {
        "total_measures": n,
        "statistics": stats,
        "top_10_complex": top_rows,
        "all_measures": rows,
        "expressions": expressions,
        "table_count": tables,
    }



def render_complexity(data: dict) -> str:
    """The report as a reviewer reads it: the banners, the statistics, the
    distribution, the longest measures and the suggested thresholds."""
    s, e = data["statistics"], data["expressions"]
    lines = [
        "=" * 80,
        "MEASURE COMPLEXITY ANALYSIS",
        "=" * 80,
        "",
        "🔍 Parsing model...",
        f"✅ Parsed {data['table_count']} tables",
        "",
        "📊 Analyzing measures...",
        f"✅ Analyzed {data['total_measures']} measures",
        "",
        "=" * 80,
        "📊 COMPLEXITY ANALYSIS RESULTS",
        "=" * 80,
        "",
        "📈 Statistics:",
        f"   Total measures: {data['total_measures']}",
        "",
        "   Expression Lengths:",
        f"     Average: {s['avg_length']:,.0f} characters",
        f"     Minimum: {s['min_length']:,} characters",
        f"     Maximum: {s['max_length']:,} characters",
        "",
        "   Percentiles:",
        f"     50th (median): {s['median_length']:,} characters",
        f"     75th: {s['p75_length']:,} characters",
        f"     90th: {s['p90_length']:,} characters",
        f"     95th: {s['p95_length']:,} characters",
        f"     99th: {s['p99_length']:,} characters",
        "",
        "   Nesting Depth:",
        f"     Average: {s['avg_nesting_depth']:.1f} levels",
        f"     Maximum: {s['max_nesting_depth']} levels",
        "",
        "   VAR Usage:",
        f"     Average: {s['avg_var_count']:.1f} VARs per measure",
        f"     Maximum: {s['max_var_count']} VARs in a single measure",
        "",
        "📊 Length Distribution:",
    ]
    lengths = sorted(m["length"] for m in data["all_measures"])
    for label, lo, hi in _BUCKETS:
        count = sum(1 for x in lengths if x >= lo and (hi is None or x < hi))
        share = 100.0 * count / len(lengths) if lengths else 0.0
        upper = "inf" if hi is None else f"{hi:,}"
        lines.append(f"   {label:12} ({lo:>6,} - {upper:>6} chars): {count:4} ({share:5.1f}%)")
    lines += [
        "",
        "🏆 Top 10 Most Complex Measures (by length):",
        "-" * 80,
    ]
    for index, row in enumerate(data["top_10_complex"], 1):
        marker = "⚠️" if row["length"] > 10000 else "📝"
        lines += [
            f"{index:2}. {marker} {row['table']}[{row['measure']}]",
            f"     Length: {row['length']:,} chars | Lines: {row['lines']} | "
            f"VARs: {row['var_count']} | Depth: {row['max_nesting_depth']}",
            f"     CALCULATE: {row['calculate_count']} | FILTER: {row['filter_count']} | "
            f"SUMX: {row['sumx_count']}",
            "",
        ]
    max_nesting = s["max_nesting_depth"]
    max_vars = s["max_var_count"]
    lines += [
        "=" * 80,
        "💡 RECOMMENDED THRESHOLDS FOR TESTS",
        "=" * 80,
        "",
        "Based on data analysis:",
        f"   Max length (strict): {s['p95_length']:,} chars (95th percentile)",
        f"   Max length (relaxed): {s['p99_length']:,} chars (99th percentile)",
        f"   Max nesting depth: {max_nesting} levels (current max)",
        f"   Max VAR count: {max_vars} (current max)",
        "",
        "Suggested test thresholds:",
        f"   - Core measures: <{s['p90_length']:,} chars",
        f"   - Helper measures: <{s['p95_length']:,} chars",
        f"   - Critical violation: >{s['p99_length']:,} chars",
        f"   - Max nesting: {min(max_nesting + 2, 20)} levels (allow headroom)",
        f"   - Max VARs: {min(max_vars + 5, 25)} (allow headroom)",
        "",
        "=" * 80,
        "✅ ANALYSIS COMPLETE",
        "=" * 80,
        "",
        "📊 DAX Expression Statistics:",
        f"   Total expressions: {e['total_expressions']}",
        f"   - Measures: {e['measures']}",
        f"   - Calculated columns: {e['calculated_columns']}",
        "",
        "   Expression Lengths:",
        f"   - Average: {e['avg_length']:.0f} characters",
        f"   - Minimum: {e['min_length']} characters",
        f"   - Maximum: {e['max_length']:,} characters",
        f"   - Total characters: {e['total_characters']:,}",
    ]
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
        "cardinality_types": _first_seen(
            f"{r.from_cardinality}_to_{r.to_cardinality}" for r in rels),
        "cross_filtering": {"unidirectional": len(rels) - len(bidir), "bidirectional": len(bidir)},
        "bidirectional_relationships": [
            {"from": f"{r.from_table}[{r.from_column}]", "to": f"{r.to_table}[{r.to_column}]",
             "id": r.rel_id} for r in bidir
        ],
        "tables": {"total": len(stems), "with_relationships": len(related), "orphans": len(orphans)},
        "orphan_categories": {"report_tables": params, "selector_tables": selectors,
                              "other_orphans": other},
        "hub_tables": _hubs(endpoints, rels),
    }


def _first_seen(values) -> dict[str, int]:
    """A counter whose keys keep the order they were first seen in."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _hubs(endpoints: Counter, rels) -> list[dict]:
    """The tables with the most relationships, ties in the order the
    relationships file lists them."""
    order: dict[str, int] = {}
    for index, r in enumerate(rels):
        for table in (r.from_table, r.to_table):
            order.setdefault(table, index)
    ranked = sorted(endpoints.items(), key=lambda kv: (-kv[1], order.get(kv[0], 0)))
    return [{"table": t, "relationship_count": n} for t, n in ranked[:10]]


def render_relationships(data: dict) -> str:
    """The report as a reviewer reads it: the banners, the counts, the
    cardinality types, the tables and the hubs."""
    lines = [
        "=" * 60,
        "RELATIONSHIP ANALYSIS",
        "=" * 60,
        "",
        f"📂 Reading: {data['relationships_file']}",
        f"✅ Found {data['total_relationships']} relationships",
        "",
        f"📂 Scanning tables in: {data['tables_folder']}",
        f"✅ Found {data['tables']['total']} tables",
        "",
        "🔍 Analyzing relationship topology...",
        "✅ Analysis complete",
        "",
        "=" * 60,
        "SUMMARY",
        "=" * 60,
        "",
        f"Total Relationships:     {data['total_relationships']}",
        f"  - Active:              {data['active_relationships']}",
        f"  - Inactive:            {data['inactive_relationships']}",
        "",
        "Cardinality Types:",
    ]
    for name, count in data["cardinality_types"].items():
        lines.append(f"  - {name:20s} {count}")
    lines += [
        "",
        "Cross-Filtering:",
        f"  - Unidirectional:      {data['cross_filtering']['unidirectional']}",
        f"  - Bidirectional:       {data['cross_filtering']['bidirectional']}",
    ]
    bidir = data["bidirectional_relationships"]
    if bidir:
        lines += ["", "  Bidirectional Relationships:"]
        for rel in bidir[:5]:
            lines.append(f"    {rel['from']} <-> {rel['to']}")
        if len(bidir) > 5:
            lines.append(f"    ... and {len(bidir) - 5} more")
    t = data["tables"]
    lines += [
        "",
        "Tables:",
        f"  - Total:               {t['total']}",
        f"  - With relationships:  {t['with_relationships']}",
        f"  - Orphans:             {t['orphans']}",
    ]
    categories = data["orphan_categories"]
    if t["orphans"]:
        lines += [
            "",
            "  Orphan Categories:",
            f"    - Report tables:       {len(categories['report_tables'])}",
            f"    - Selector tables:   {len(categories['selector_tables'])}",
            f"    - Other:             {len(categories['other_orphans'])}",
        ]
    if categories["other_orphans"]:
        lines += ["", "  Other Orphan Tables:"]
        for name in categories["other_orphans"][:10]:
            lines.append(f"    - {name}")
        if len(categories["other_orphans"]) > 10:
            lines.append(f"    ... and {len(categories['other_orphans']) - 10} more")
    lines += ["", "Hub Tables (most connected):"]
    for hub in data["hub_tables"][:5]:
        lines.append(f"  - {hub['table']:30s} {hub['relationship_count']} relationships")
    lines += [
        "",
        "=" * 60,
        "ANALYSIS COMPLETE",
        "=" * 60,
    ]
    return "\n".join(lines)
