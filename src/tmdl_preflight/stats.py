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


def measure_summary(ctx: Context, field_parameter_tables=None, options=None) -> dict[str, Any]:
    """How measures are organised: name classes, field-parameter surfacing,
    helper subcategories, top tables, described dash helpers. Informational
    only; there are no thresholds besides the surfacing advisory.

    The summary is PER MODEL: a folder with two models prints two
    summaries, each with its own totals. A sum across models would hide
    which model is the problem."""
    from .measure_classes import classify_measure_name
    from .roles import surfaced_measures

    per_model = []
    for model in ctx.models:
        per_model.append(
            _model_measure_summary(model, field_parameter_tables, options))
    return {
        "per_model": per_model,
        "total": sum(s["total"] for s in per_model),
        "user_facing": sum(s["user_facing"] for s in per_model),
        "helpers": sum(s["helpers"] for s in per_model),
        "surfaced": sum(s["surfaced"] for s in per_model),
        "surfaced_user_facing": sum(s["surfaced_user_facing"] for s in per_model),
        "not_surfaced": sum(s["not_surfaced"] for s in per_model),
        "advisory": any(s["advisory"] for s in per_model),
        "subcategories": dict(sorted(
            Counter({k: v for s in per_model for k, v in s["subcategories"].items()}
                    ).items(), key=lambda kv: (-kv[1], kv[0]))),
        "top_tables": [[name, n] for name, n in sorted(
            Counter({k: v for s in per_model for k, v in s["top_tables"]}.items()
                    ).items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
        "dash_helpers": sum(s["dash_helpers"] for s in per_model),
        "dash_helpers_described": sum(
            s["dash_helpers_described"] for s in per_model),
    }


def _model_measure_summary(model, field_parameter_tables, options) -> dict[str, Any]:
    """The measure organisation of ONE model."""
    from .measure_classes import classify_measure_name
    from .roles import surfaced_measures

    measures = list(model.all_measures())
    classes = [classify_measure_name(m.name, options) for m in measures]
    user = {c.name for c in classes if not c.is_helper}
    surfaced = surfaced_measures(model, field_parameter_tables)
    subcats = Counter(c.subcategory or "unknown_helper"
                      for c in classes if c.is_helper)
    per_table = Counter(m.table for m in measures)
    dash = [m for m in measures if m.name.startswith("-")]
    total = len(measures)
    users = sum(1 for c in classes if not c.is_helper)
    inter = len(surfaced & user)
    return {
        "model": model.definition_path.parent.name,
        "total": total,
        "user_facing": users,
        "helpers": total - users,
        "user_facing_pct": round(100.0 * users / total, 1) if total else 0.0,
        "helpers_pct": round(100.0 * (total - users) / total, 1) if total else 0.0,
        "surfaced": len(surfaced),
        "surfaced_user_facing": inter,
        "not_surfaced": len(user - surfaced),
        "advisory": bool(users) and inter < users * 0.5,
        "subcategories": dict(sorted(subcats.items(),
                                     key=lambda kv: (-kv[1], kv[0]))),
        "top_tables": [[name, n] for name, n in sorted(
            per_table.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
        "dash_helpers": len(dash),
        "dash_helpers_described": sum(
            1 for m in dash if (m.description or "").strip()),
    }


def render_measure_summary(s: dict[str, Any]) -> str:
    """One summary per model, in the layout a reviewer reads."""
    rule = "=" * 70
    blocks: list[str] = []
    for one in s.get("per_model") or []:
        blocks.append(_render_model_summary(one, rule))
    if not blocks:
        return "No measures in model."
    dash = s.get("dash_helpers") or 0
    described = s.get("dash_helpers_described") or 0
    block = "\n".join(blocks)
    if dash:
        share = f"{100.0 * described / dash:.1f}%"
        block += (
            "\n\nHelper Measure Analysis:"
            f"\n   Total helper measures (- prefix): {dash}"
            f"\n   With description: {described} ({share})"
            f"\n   Without description: {dash - described} ({100.0 * (dash - described) / dash:.1f}%)"
            "\n\n   Descriptions are optional for helper measures (P2)")
    return block


def _render_model_summary(s: dict[str, Any], rule: str) -> str:
    if not s["total"]:
        return "No measures in model."
    pct = lambda n: f"{100.0 * n / s['total']:.1f}%"  # noqa: E731
    lines = [
        "",
        rule,
        "MEASURE ORGANIZATION SUMMARY",
        rule,
        "",
        f"Total measures: {s['total']}",
        f"  User-facing names: {s['user_facing']} ({pct(s['user_facing'])})",
        f"  Helper names:      {s['helpers']} ({pct(s['helpers'])})",
        "",
        "Field-parameter surfacing (x-Selector / y-Selector NAMEOF refs):",
        f"  Distinct measures referenced by x/y-Selector field params: {s['surfaced']}",
        f"  User-facing measures surfaced (intersection):          {s['surfaced_user_facing']}",
        f"  User-facing measures NOT in any x/y-Selector field param:  {s['not_surfaced']}",
    ]
    if s["advisory"]:
        lines.append(
            "  ! >50% of user-facing names are not surfaced via x/y-Selector - "
            "possible naming mess or analysis-category gap.")
    lines.append("")
    lines.append("Helper subcategories:")
    for name, n in s["subcategories"].items():
        lines.append(f"  {name:<22}: {n:>4} ({pct(n)})")
    lines.append("")
    lines.append("Top 10 tables by measure count:")
    for name, n in s["top_tables"]:
        lines.append(f"  {name:<40}: {n:>4} ({pct(n)})")
    lines.append(rule)
    return "\n".join(lines)
