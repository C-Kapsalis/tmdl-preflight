"""Advisory style rules. IDs S0xx."""

from __future__ import annotations

import re

from .base import Context, Rule, Severity, Violation


class FormatStringPresenceRule(Rule):
    id = "S001"
    name = "format-strings"
    severity = Severity.INFO
    description = (
        "Visible measures should declare a formatString; without one they "
        "render with engine defaults. A measure with its own "
        "formatStringDefinition is exempt, and a model whose calculation "
        "group items define format strings is exempt as a whole. Advisory "
        "only: run with --ignore S001 if formatting lives elsewhere."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            # Calculation-group items with a formatStringDefinition apply
            # formats at query time to every measure; static ones are optional.
            if any(t.dynamic_format_items for t in model.table_list):
                continue
            for measure in model.all_measures():
                if measure.is_hidden or measure.format_string:
                    continue
                if measure.format_string_definition is not None:
                    continue  # dynamic format string on this measure
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


_WORD_RE = re.compile(r"[a-z/]+")


class MeasureDescriptionRule(Rule):
    id = "S002"
    name = "measure-descriptions"
    severity = Severity.INFO
    option_defaults = {
        "min_length": 10,
        "placeholder_words": ["todo", "tbd", "tbc", "fixme", "xxx", "placeholder", "lorem"],
    }
    description = (
        "Visible measures should carry a real /// description: report "
        "authors see it as the field's tooltip, and it is the only place a "
        "measure's intent is written down. A description shorter than "
        "min_length characters (default 10) or containing a placeholder word "
        "(TODO, TBD, FIXME, ...) does not count. Both are configurable."
    )

    def _is_real(self, text: str) -> bool:
        stripped = text.strip()
        if len(stripped) < int(self.options.get("min_length", 10)):
            return False
        placeholders = {w.lower() for w in self.options.get("placeholder_words", [])}
        words = set(_WORD_RE.findall(stripped.lower()))
        return not (words & placeholders)

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for measure in model.all_measures():
                if measure.is_hidden:
                    continue
                desc = measure.description or ""
                if desc and self._is_real(desc):
                    continue
                reason = (
                    "has no /// description"
                    if not desc
                    else f"has a placeholder description ('{desc.strip()[:40]}')"
                )
                out.append(
                    self.violation(
                        f"visible measure {reason}, so report authors get no "
                        f"tooltip explaining it. Add a /// line directly above "
                        f"the measure saying what it calculates.",
                        file=measure.file,
                        line=measure.line,
                        obj=measure.full_name,
                    )
                )
        return out
