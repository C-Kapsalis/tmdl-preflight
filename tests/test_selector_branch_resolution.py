"""Every measure called by a field-parameter SELECTOR BRANCH must exist.

Ported from the layer-1 suite. A selector branch is one line holding a string KEY
(``"'Table'[object]"``) followed by a RESULT expression, in either shape:

    SelectedField = "'T'[^M]", CALCULATE([^M]),          (assignment)
    "'T'[M]", [M],                                       (positional SWITCH)

Only bare ``[X]`` calls in the RESULT are judged (a bare call that resolves to no
measure breaks the containing measure at processing time, so the model is
rejected on refresh/deploy). Keys are inert and never judged; ``--``/``//``
parked branches are exempt.

Rule (new, selected by name): selector-branch-resolution (error, fixer). The
kernel index, model discovery and the remediation provider are replaced by
``check``/``fix --select selector-branch-resolution``.
"""

from __future__ import annotations

import pytest

from conftest import run_check, run_fix, violations

pytestmark = [pytest.mark.p0]

RULE = "selector-branch-resolution"
FIX = "selector_branch_resolution"


def _branch_findings(payload):
    return sorted((v["line"], v.get("object") or v["message"]) for v in violations(payload))


@pytest.mark.parametrize(
    "sid, verdict",
    [("sel_resolving", "pass"), ("sel_dangling", "fail"), ("sel_parked", "pass"),
     ("sel_none", "skip")],
)
def test_selector_branch_measures_resolve(stand_in, sid, verdict):
    code, payload = run_check(stand_in(FIX) / sid / "Model.SemanticModel", RULE)
    found = violations(payload)
    if verdict == "fail":
        assert len(found) == 1 and "[Retired Blend #]" in found[0]["message"], found
        assert code == 1
        return
    assert found == []
    if verdict == "skip":
        pytest.skip("model has no field-parameter selector chains")


# ── fixture: the POSITIONAL shape must be gated ──────────────────────────────

FIXTURE_TABLE = """table 'Fixture Measures'
	lineageTag: 00000000-0000-0000-0000-000000000001

	measure 'Live Measure' = 1
		lineageTag: 00000000-0000-0000-0000-000000000002

	measure 'Positional Router' = ```
			SWITCH(
			    SELECTEDVALUE('x-Plot Specific 2'[x-Plot Specific 2 Fields]),
			    "'Fixture Measures'[Live Measure]", [Live Measure],
			    "'Fixture Measures'[Gone Measure]", [Gone Measure],
			    -- "'Fixture Measures'[Parked Measure]", [Parked Measure],
			    BLANK()
			)
			```
		lineageTag: 00000000-0000-0000-0000-000000000003

	measure 'Assignment Router' = ```
			VAR SelectedField = SELECTEDVALUE('x-Selector 1'[x-Selector 1 Fields])
			RETURN SWITCH( TRUE(),
			    SelectedField = "'Fixture Measures'[Live Measure]", CALCULATE([Live Measure]),
			    BLANK()
			)
			```
		lineageTag: 00000000-0000-0000-0000-000000000004

	partition 'Fixture Measures' = m
		mode: import
		source = #table({"Column1"}, {{1}})
"""


def write_fixture_model(root, table_text=FIXTURE_TABLE):
    """A one-table model with a positional router, an assignment router and one
    parked branch. Returns the .SemanticModel folder."""
    model = root / "Fixture.SemanticModel"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "Fixture Measures.tmdl").write_text(table_text, encoding="utf-8")
    return model


def test_positional_switch_branch_is_gated(tmp_path):
    # Recognised branches: lines 10 and 11 (positional) and 21 (assignment).
    # Observed through the rule by renaming the live measure so every
    # recognised branch becomes unresolved.
    probe = write_fixture_model(tmp_path / "probe", FIXTURE_TABLE.replace(
        "measure 'Live Measure' = 1", "measure 'Renamed Measure' = 1"))
    _code, payload = run_check(probe, RULE)
    lines = sorted(v["line"] for v in violations(payload))
    msgs = [v["message"] for v in sorted(violations(payload), key=lambda v: v["line"])]
    assert lines == [10, 11, 21], f"recognizer saw the wrong branches: {lines}"
    assert ["[Live Measure]" in msgs[0], "[Gone Measure]" in msgs[1],
            "[Live Measure]" in msgs[2]] == [True, True, True]

    model = write_fixture_model(tmp_path / "real")
    code, payload = run_check(model, RULE)
    found = violations(payload)
    assert [(v["path"].split("/")[-1], v["line"]) for v in found] == [("Fixture Measures.tmdl", 11)], (
        "the positional SWITCH branch calling a purged measure must fail the gate "
        f"and nothing else may; got {found}")
    assert "[Gone Measure]" in found[0]["message"]
    assert code == 1


def test_provider_detects_and_kills_positional_branch(tmp_path):
    """The gate's fixer shares the recognizer: it names the same positional branch
    and removes exactly that line, leaving the live and parked branches alone."""
    model = write_fixture_model(tmp_path)
    _code, payload = run_check(model, RULE)
    found = violations(payload)
    assert [(v["path"].split("/")[-1], v["line"] - 1) for v in found] == [
        ("Fixture Measures.tmdl", 10),  # 0-based line index
    ], f"fixer disagrees with the gate: {found}"
    assert found[0]["fixable"] is True

    code, payload = run_fix(model, RULE)
    assert any("1 dangling selector branch" in f for f in payload["fixes"]), payload["fixes"]

    text = (model / "definition" / "tables" / "Fixture Measures.tmdl").read_text(encoding="utf-8")
    assert "[Gone Measure]" not in text, "the dangling branch survived the kill"
    assert '"\'Fixture Measures\'[Live Measure]", [Live Measure],' in text, (
        "a resolving branch was removed")
    assert '-- "\'Fixture Measures\'[Parked Measure]", [Parked Measure],' in text, (
        "a parked branch was removed — parked branches are exempt")
    assert violations(payload) == [], "gate still red after the fix"
    assert code == 0


TWO_GONE = FIXTURE_TABLE.replace(
    '\t\t\t    "\'Fixture Measures\'[Gone Measure]", [Gone Measure],\n',
    '\t\t\t    "\'Fixture Measures\'[Gone Measure]", [Gone Measure] + [Also Gone],\n'
    '\t\t\t    "\'Fixture Measures\'[Second Gone]", [Second Gone],\n',
)


def test_one_line_with_two_missing_measures_gives_one_finding(tmp_path):
    model = write_fixture_model(tmp_path, TWO_GONE)
    _code, payload = run_check(model, RULE)
    found = violations(payload)
    assert len(found) == 2, found
    one = [v for v in found if "[Also Gone]" in v["message"]]
    assert len(one) == 1
    message = one[0]["message"]
    assert message.startswith(
        "2 field-parameter selector branch(es) call a measure that does not exist — "
        "the containing helper/projected measure fails at processing time and PBI "
        "rejects the model on refresh/deploy.: ")
    assert message.endswith("Fixture Measures.tmdl:11  [Gone Measure] [Also Gone]")


def test_the_fix_reports_how_many_branches_it_killed(tmp_path):
    model = write_fixture_model(tmp_path, TWO_GONE)
    code, payload = run_fix(model, RULE)
    assert code == 0, payload
    assert any("killed 2 dangling selector branch(es)" in f for f in payload["fixes"]), payload["fixes"]
    text = (model / "definition" / "tables" / "Fixture Measures.tmdl").read_text(encoding="utf-8")
    assert "[Gone Measure]" not in text and "[Also Gone]" not in text
    assert "[Second Gone]" not in text
    assert violations(payload) == []

