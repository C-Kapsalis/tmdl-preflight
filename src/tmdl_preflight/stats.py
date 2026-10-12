"""``tmdl-preflight stats``: an inventory of a project, counts only.

Nothing here judges the numbers; there are no thresholds. The counts are
what a reviewer wants to see change (or not) in a pull request.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .engine import scan_summary
from .rules.base import Context


def collect_stats(ctx: Context) -> dict[str, Any]:
    base = scan_summary(ctx)
    tables = [t for m in ctx.models for t in m.table_list]
    measures = [x for t in tables for x in t.measure_list]
    columns = [x for t in tables for x in t.column_list]
    rels = [r for m in ctx.models for r in m.relationships]
    partitions = Counter(p.kind for t in tables for p in t.partitions)
    stats: dict[str, Any] = dict(base)
    stats.update(
        {
            "hidden_tables": sum(1 for t in tables if t.is_hidden),
            "calculated_tables": sum(
                1 for t in tables if any(p.kind == "calculated" for p in t.partitions)
            ),
            "field_parameters": sum(1 for t in tables if t.is_field_parameter),
            "calculation_items": sum(len(t.calculation_items) for t in tables),
            "calculated_columns": sum(1 for c in columns if c.is_calculated),
            "hidden_columns": sum(1 for c in columns if c.is_hidden),
            "hidden_measures": sum(1 for x in measures if x.is_hidden),
            "measures_with_description": sum(1 for x in measures if x.description),
            "measures_with_format_string": sum(
                1 for x in measures if x.format_string or x.format_string_definition is not None
            ),
            "display_folders": len({x.display_folder for x in measures if x.display_folder}),
            "partitions": dict(sorted(partitions.items())),
            "active_relationships": sum(1 for r in rels if r.is_active),
            "inactive_relationships": sum(1 for r in rels if not r.is_active),
            "bidirectional_relationships": sum(
                1 for r in rels if r.cross_filtering.lower() == "bothdirections"
            ),
            "parameters": sum(1 for m in ctx.models for e in m.expressions if e.is_parameter),
            "lineage_tags": sum(len(m.lineage_tags) for m in ctx.models),
            "tables_with_refresh_policy": sum(1 for t in tables if t.refresh_policy),
        }
    )
    return stats


def render_stats(stats: dict[str, Any]) -> str:
    width = max(len(k) for k in stats)
    lines = []
    for key, value in stats.items():
        if isinstance(value, dict):
            value = ", ".join(f"{k}: {v}" for k, v in value.items()) or "none"
        lines.append(f"{key.replace('_', ' '):<{width}}  {value}")
    return "\n".join(lines)
