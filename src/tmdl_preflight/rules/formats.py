"""S005 format-min-decimals: a measure must keep its decimals through the
format calculation group."""

from __future__ import annotations

from ..format_resolver import UNKNOWN, branched_axes, decimals, resolve
from .base import Context, Rule, Severity, Violation


class FormatMinDecimalsRule(Rule):
    id = "S005"
    name = "format-min-decimals"
    severity = Severity.ERROR
    option_defaults = {"expectations": [], "table": "z-Selector Format"}
    description = (
        "Some measures are only meaningful with decimals (a cost per "
        "conversion of 0.53). When a format calculation group picks the "
        "format by matching the measure name, a rename can send it to a "
        "whole-number arm and the visual shows '1'. For each expectation "
        "({name, label?, min_decimals}) the name is resolved through the "
        "calculation group on the measure-name path and on every axis the "
        "group branches on; fewer decimals than required is an error. "
        "Unresolvable or non-numeric results are not findings. Inert until "
        "expectations are configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        expectations = self.options.get("expectations") or []
        if not expectations:
            return []
        out: list[Violation] = []
        for model in ctx.models:
            table = model.get_table(self.options.get("table") or "z-Selector Format")
            if table is None or ctx.is_excluded(table.file):
                continue
            try:
                text = table.file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            axes = [None, *branched_axes(text)]
            for exp in expectations:
                name = exp.get("name", "")
                floor = int(exp.get("min_decimals", 1))
                for axis in axes:
                    fmt, _unresolved = resolve(table.file, name, axis=axis, label=exp.get("label"))
                    places = decimals(fmt)
                    if fmt == UNKNOWN or places is None or places >= floor:
                        continue
                    where = f"axis '{axis}'" if axis else "the measure-name path"
                    out.append(self.violation(
                        f"{ctx.model_key(model)}: '{name}' resolves to '{fmt}' on {where} "
                        f"({places} decimal(s), at least {floor} required). Reorder or add a "
                        f"SWITCH arm, or rename the measure.",
                        file=table.file, obj=f"{name}@{axis or 'measure name'}",
                    ))
        return out
