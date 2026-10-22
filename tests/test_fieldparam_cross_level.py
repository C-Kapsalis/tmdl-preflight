"""Cross-level y-Selector membership integrity (spec A-fieldparam-level-consistency).

Each model carries numbered `y-Selector N` drilldown levels, and every level holds
its OWN copy of the dimension registry. A dimension registered in some levels
and not others appears at some drilldown levels and VANISHES at others, which
reads as data loss.

The law:
  1. The numbered `y-Selector N` tables of a model reference IDENTICAL sets of
     NAMEOF targets.
  2. `y-Plot Specific N` is a SUBSET of that set. The "no legend
     selected" placeholder row is exempt: numbered levels target
     `'#Report Measures'[z]` while Plot Specific targets `[z_space]` by design.

Targets are compared on the normalized NAMEOF reference (quotes removed,
whitespace collapsed, lowercased), scanning the comment-masked text as a
whole so a tuple split across lines and two tuples sharing a line are both
seen.

Stand-ins (tests/fixtures/b3-a2/fieldparam_cross_level/roastery):
``cl_ok_db/Roastery`` levels 1-3 identical, Plot Specific a subset plus the
placeholder -> both checks pass; ``cl_bad_db/Roastery`` level 3 lacks
`Beans[roast]` and Plot Specific adds `Beans[farm]` -> both fail.
"""
from __future__ import annotations

import pytest

from conftest import run_check, violations

RULE = "fieldparam-level-consistency"
OPTIONS = {"families": [{"levels": "y-Selector {n}", "range": [1, 9],
                         "subset": "y-Plot Specific *",
                         "placeholder_table": "#Report Measures"}]}

MODELS = [
    pytest.param("cl_ok_db/Roastery.SemanticModel", "pass", id="cl_ok_db/Roastery"),
    pytest.param("cl_bad_db/Roastery.SemanticModel", "fail", id="cl_bad_db/Roastery"),
]


def _findings(stand_in, folder):
    root = stand_in("b3-a2/fieldparam_cross_level/roastery")
    _code, payload = run_check(root, RULE, config={"rules": {RULE: OPTIONS}})
    assert "summary" in payload, payload
    return [v for v in violations(payload) if folder in (v.get("file") or "").replace("\\", "/")]


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_yselector_levels_identical(stand_in, folder, verdict):
    hits = [v for v in _findings(stand_in, folder) if "missing from" in v["message"].lower()]
    if verdict == "pass":
        assert hits == []
    else:
        assert len(hits) == 1
        assert "beans[roast]" in hits[0]["message"].lower()
        assert "y-Selector 3" in hits[0]["message"]


def test_recognizer_sees_split_line_and_shared_line_tuples():
    """A tuple split across physical lines, and a second tuple sharing a line,
    are live dimensions; a commented row is not."""
    from tmdl_preflight.recognizers import nameof_targets

    text = (
        '("A", NAMEOF(T[a]), 1, "g_y", "Other"), ("B", NAMEOF(T[b]), 2, "g_y", "Other"),\n'
        '("C Split",\n'
        "  NAMEOF('T2'[c]), 3, \"g_y\", \"Other\"),\n"
        '-- ("Dead", NAMEOF(T[dead]), 4, "g_y", "Other"),\n'
    )
    assert nameof_targets(text) == {"t[a]", "t[b]", "t2[c]"}


@pytest.mark.parametrize("folder,verdict", MODELS)
def test_yselector_plot_specific_subset(stand_in, folder, verdict):
    hits = [v for v in _findings(stand_in, folder) if "absent from every numbered" in v["message"]]
    if verdict == "pass":
        assert hits == []          # the placeholder row is exempt
    else:
        assert len(hits) == 1
        assert "beans[farm]" in hits[0]["message"].lower()


def test_yselector_level_message_names_the_levels(stand_in):
    hits = [v for v in _findings(stand_in, "cl_bad_db") if "MISSING from" in v["message"]]
    assert len(hits) == 1
    assert hits[0]["message"] == (
        "NAMEOF(beans[roast]) in y-Selector 1,2 but MISSING from y-Selector 3")


def test_yselector_subset_message_names_the_table_and_the_target(stand_in):
    hits = [v for v in _findings(stand_in, "cl_bad_db")
            if "absent from every numbered" in v["message"]]
    assert len(hits) == 1
    assert hits[0]["message"] == (
        "y-Plot Specific 1: NAMEOF(beans[farm]) absent from every numbered "
        "y-Selector level")

