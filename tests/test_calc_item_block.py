"""The Daily calculation item is read as a whole block: from its
`calculationItem Daily` line to the next calculation item or the end of the
file (spec A-calc-item-blind-average).

A property line of the item carries part of the required shape, so the check
must read the item's source, not only its parsed expression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check

TAG = "3c4d5e6f-0000-4000-8000-{:012d}"

RULE = "calc-item-blind-average"

DAILY_BLOCK = """		calculationItem Daily = ```
				VAR _name = SELECTEDMEASURENAME ()
				VAR _isRatio = CONTAINSSTRING ( _name, "/" ) || CONTAINSSTRING ( _name, " per " )
				RETURN
				    SWITCH ( TRUE (),
				        _isRatio, SELECTEDMEASURE (),
				        SELECTEDMEASURE () )
				```

"""

#: The additivity test and the additive branch sit in the item's own
#: format-string property, not in its expression.
DAILY_WITH_PROPERTY = """		calculationItem Daily = ```
				VAR _name = SELECTEDMEASURENAME ()
				RETURN SELECTEDMEASURE ()
				```

			formatStringDefinition =
					SWITCH (
					    TRUE (),
					    CONTAINSSTRING ( _name, "#" ), "#,##0",
					    CONTAINSSTRING ( _name, "/" ), "0.00",
					    CONTAINSSTRING ( _name, " per " ), "0.00",
					    SUMX ( VALUES ( '__Calendar'[Date] ), SELECTEDMEASURE () )
					        && ISNUMBER ( SELECTEDMEASURE () ) && _additive
					        && AVERAGEX ( VALUES ( '__Calendar'[Date] ), SELECTEDMEASURE () ),
					    "#,##0.00"
					)

"""


def _model(tmp_path: Path, daily: str) -> Path:
    d = tmp_path / "Daily.SemanticModel" / "definition"
    t = d / "tables"
    t.mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    (t / "z-Toggle Daily Calculation.tmdl").write_text(
        f"table 'z-Toggle Daily Calculation'\n\tlineageTag: {TAG.format(1)}\n\n"
        "\tcalculationGroup\n\n" + daily +
        "\tcolumn Name\n\t\tdataType: string\n\t\tlineageTag: " + TAG.format(2) +
        "\n\t\tsourceColumn: Name\n\n", encoding="utf-8")
    return d.parent


def _violations(payload: dict, *needles: str) -> list[dict]:
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in payload["violations"] if all(n in v["message"] for n in needles)]


def test_the_additivity_tokens_may_sit_in_a_property_line(tmp_path):
    """The item's source carries the shape, so the check finds it there."""
    model = _model(tmp_path, DAILY_WITH_PROPERTY)
    code, payload = run_check(model, RULE)
    assert code == 0
    assert _violations(payload) == []


def test_a_blind_daily_item_is_still_reported(tmp_path):
    model = _model(tmp_path, DAILY_BLOCK)
    code, payload = run_check(model, RULE)
    assert code == 1
    found = _violations(payload, "averages blindly")
    assert len(found) == 1
    assert "additivity test" in found[0]["message"]


pytestmark = pytest.mark.layer1
