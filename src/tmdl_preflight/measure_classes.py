"""Measure-name classes: is a measure meant for report authors, or plumbing?

One shared, name-only classifier for every organisation rule (placement,
purity, visibility, folders, descriptions). Visibility is deliberately not an
input: a user-facing measure that was hidden by accident must still classify
as user-facing so the visibility rule can catch it.

A name is a *helper* when it starts with ``-`` or ``_``; or its second
character is ``-`` after a letter that is not a user-facing letter (``z`` by
default, compared case-sensitively); or it contains the word ``test`` at a
word boundary. Everything else, including names with sigils such as ``#``,
``^`` or ``!``, is *user-facing*. Helpers get a subcategory; user-facing
names can be *noise* (scaffolding the visibility rule ignores).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

DEFAULTS: dict[str, Any] = {
    "strict_helper_prefix": "-helper ",
    "visual_helper_prefix": "-Visual ",
    "visual_table_letter": "w",
    "diagnostic_letter": "i",
    "filter_letter": "f",
    "user_facing_letters": ["z"],
    "noise_exact": ["max", "min", "value"],
    "noise_prefixes": ["max ", "min "],
    "noise_substrings": ["blank", "date", "day", "countrows", "filter", "calendar", "facebook"],
}

_TEST_WORD_RE = re.compile(r"\btest", re.IGNORECASE)

SUBCATEGORIES = (
    "measure_helper", "visual_helper", "diagnostic_helper", "slicer_helper",
    "intermediary_helper", "test_measure",
)


@dataclass(frozen=True)
class MeasureClass:
    name: str
    is_helper: bool
    subcategory: Optional[str]
    is_noise: bool

    @property
    def is_user_facing(self) -> bool:
        return not self.is_helper


def _options(options: Optional[dict]) -> dict:
    merged = dict(DEFAULTS)
    if options:
        merged.update({k: v for k, v in options.items() if k in DEFAULTS})
    return merged


def is_helper_name(name: str, options: Optional[dict] = None) -> bool:
    opts = _options(options)
    if not name:
        return False
    if name[0] in "-_":
        return True
    if (
        len(name) >= 2
        and name[1] == "-"
        and name[0].isalpha()
        and name[0] not in opts["user_facing_letters"]
    ):
        return True
    return bool(_TEST_WORD_RE.search(name))


def helper_subcategory(name: str, options: Optional[dict] = None) -> str:
    """Subcategory of a helper name (first matching row wins)."""
    opts = _options(options)
    visual = opts["visual_helper_prefix"]
    if name.startswith(opts["strict_helper_prefix"]):
        return "measure_helper"
    if name.startswith(visual) or name.startswith(visual[:1] + visual[1:].lower()):
        return "visual_helper"
    if name.startswith(opts["diagnostic_letter"] + "-"):
        return "diagnostic_helper"
    if name.startswith(opts["filter_letter"] + "-"):
        return "slicer_helper"
    if name.startswith(opts["visual_table_letter"] + "-"):
        return "visual_helper"
    if name.startswith("_"):
        return "measure_helper"
    if name.startswith("-"):
        return "intermediary_helper"
    if _TEST_WORD_RE.search(name):
        return "test_measure"
    return "intermediary_helper"


def is_noise_name(name: str, options: Optional[dict] = None) -> bool:
    opts = _options(options)
    low = name.lower()
    if low in {n.lower() for n in opts["noise_exact"]}:
        return True
    if any(low.startswith(p.lower()) for p in opts["noise_prefixes"]):
        return True
    if "_" in name:
        return True
    return any(s.lower() in low for s in opts["noise_substrings"])


def classify_measure_name(name: str, options: Optional[dict] = None) -> MeasureClass:
    helper = is_helper_name(name, options)
    return MeasureClass(
        name=name,
        is_helper=helper,
        subcategory=helper_subcategory(name, options) if helper else None,
        is_noise=is_noise_name(name, options) if name else False,
    )
