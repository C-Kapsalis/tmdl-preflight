"""Advisory style rules. IDs S0xx."""

from __future__ import annotations

from .base import Context, Rule, Severity, Violation


class FormatStringPresenceRule(Rule):
    id = "S001"
    name = "format-strings"
    severity = Severity.INFO
    description = (
        "Visible measures should declare a formatString; without one they "
        "render with engine defaults. Advisory only — models that apply "
        "formats dynamically through a calculation group should ignore this "
        "rule (run with --ignore S001)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            # If the model carries dynamic format-string definitions, formats
            # are applied at query time and static ones are optional.
            has_dynamic_formats = any(
                t.format_string_definitions for t in model.tables.values()
            )
            if has_dynamic_formats:
                continue
            for measure in model.all_measures():
                if measure.is_hidden or measure.format_string:
                    continue
                out.append(
                    self.violation(
                        "visible measure has no formatString, so it renders "
                        "with the engine's default formatting. Add a "
                        "formatString, or run with --ignore S001 if your "
                        "formatting strategy lives elsewhere.",
                        file=measure.file,
                        line=measure.line,
                        obj=measure.full_name,
                    )
                )
        return out
