"""The contract and grain findings carry the same facts as the reference
messages: the count of the missing columns, their names and the guard's
name (slice item CG-22).

One finding per object, but the facts a reader needs to act on it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check

TAG = "3c4d5e6f-0000-4000-8000-{:012d}"

GUARD = "-helper Cost Grain Valid"
GUARD_TABLE = "#Backend Measures"


def _table(d: Path, name: str, cols: list[str], extra: str = "", n: int = 1) -> None:
    body = f"table '{name}'\n\tlineageTag: {TAG.format(n)}\n\n"
    for k, c in enumerate(cols):
        body += (f"\tcolumn {c}\n\t\tdataType: string\n\t\tlineageTag: {TAG.format(n * 100 + k)}\n"
                 f"\t\tsourceColumn: {c}\n\n")
    body += extra
    body += f"\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource = Sql.Database(\"s\", \"d\")\n"
    (d / f"{name}.tmdl").write_text(body, encoding="utf-8")


def _model(tmp_path: Path, guard: str, columns: list[tuple[str, str]]) -> Path:
    d = tmp_path / "Delivery.SemanticModel" / "definition"
    t = d / "tables"
    t.mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    _table(t, "_Devices", ["device", "region"], n=1)
    _table(t, "_Countries", ["country"], n=2)
    measures = f"\tmeasure '{GUARD}' = ```\n{guard}\n\t\t\t```\n" \
               f"\t\tlineageTag: {TAG.format(2001)}\n\n"
    _table(t, GUARD_TABLE, [], n=20, extra=measures)
    rows = "".join(f"\t\t\t\t  (\"{t_}\", NAMEOF('{t_}'[{c}]), {i})\n"
                   for i, (t_, c) in enumerate(columns))
    (t / "y-Selector 1.tmdl").write_text(
        f"table 'y-Selector 1'\n\tlineageTag: {TAG.format(30)}\n\n"
        "\tpartition 'y-Selector 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        "\t\t\t\t{\n" + rows + "\t\t\t\t }\n", encoding="utf-8")
    return d.parent


def _violations(payload: dict, *needles: str) -> list[dict]:
    assert "violations" in payload, f"check did not run: {payload}"
    return [v for v in payload["violations"] if all(n in v["message"] for n in needles)]


def _config() -> dict:
    return {"rules": {"grain-guard-coverage": {"models": {"m": {
        "model": "Delivery",
        "guard_table": GUARD_TABLE,
        "guard_measure": GUARD,
        "blocked_tables": ["_Devices"],
        "permitted_tables": ["_Countries"],
    }}}}}


def test_a_missing_column_finding_carries_the_count_the_names_and_the_guard(tmp_path):
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Devices' )",
                   [("_Devices", "device"), ("_Devices", "region"),
                    ("_Countries", "country")])
    code, payload = run_check(model, "grain-guard-coverage", config=_config())
    assert code == 1
    found = _violations(payload, "ISINSCOPE", "'_Devices'[")
    assert len(found) == 2
    for v in found:
        assert GUARD in v["message"]
        assert "2" in v["message"]
        assert "'_Devices'[device]" in v["message"]
        assert "'_Devices'[region]" in v["message"]


def test_a_blocked_conformed_column_finding_carries_the_guard(tmp_path):
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Devices' ) || "
                             "ISINSCOPE ( '_Countries'[country] )",
                   [("_Devices", "device"), ("_Countries", "country")])
    code, payload = run_check(model, "grain-guard-coverage", config=_config())
    assert code == 1
    found = _violations(payload, "SELECTEDVALUE")
    assert len(found) == 1
    assert GUARD in found[0]["message"]


def test_a_blocked_table_finding_carries_the_guard(tmp_path):
    model = _model(tmp_path, "\t\t\tISFILTERED ( '_Devices' ) || "
                             "ISFILTERED ( '_Countries' )",
                   [("_Devices", "device"), ("_Countries", "country")])
    code, payload = run_check(model, "grain-guard-coverage", config=_config())
    assert code == 1
    found = _violations(payload, "conformed table")
    assert len(found) == 1
    assert GUARD in found[0]["message"]


pytestmark = pytest.mark.layer1
