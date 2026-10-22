"""The analysis-category attribution: the mapping table's rows, the axis
rows that carry the group ids, and the measure trace behind them.

* the payload the mapping fixer writes (the JSON layout the table stores)
* which mapping rows attribute a category (three values or more, the third
  one is the group id, a null cell counts as empty)
* which axis tables attribute (the numbered x-axis tables)
* the measure-reference graph and the direct fact match
* the shape an axis row must have to attribute
"""

from __future__ import annotations

import base64
import json
import re
import zlib
from pathlib import Path

from conftest import run_check, run_cli, run_fix, violations

TAG = "11111111-1111-4111-8111-{:012d}"
ZMAP = "z-Map Dimension-Measure Groupings"


def _encode(rows) -> str:
    """The payload as the table stores it, built with the standard library."""
    payload = json.dumps(rows, ensure_ascii=True, separators=(", ", ": ")).encode("utf-8")
    packer = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    return base64.b64encode(packer.compress(payload) + packer.flush()).decode("ascii")


def _fact(name: str, tag: int, measures: str = "") -> str:
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            "\tcolumn amount\n\t\tdataType: double\n\t\tlineageTag: "
            + TAG.format(tag + 50) + "\n\t\tsourceColumn: amount\n\n"
            + measures +
            f"\tpartition {name} = m\n\t\tmode: import\n\t\tsource = x\n")


def _measures(*rows: str) -> str:
    out = ""
    for i, body in enumerate(rows):
        name, expression = body.split("=", 1)
        out += (f"\tmeasure {name.strip()} = {expression.strip()}\n"
                f"\t\tlineageTag: {TAG.format(700 + i)}\n\n")
    return out


def _axis(name: str, tag: int, rows: str) -> str:
    return (f"table '{name}'\n\tlineageTag: " + TAG.format(tag) + "\n\n"
            f"\tpartition '{name}' = calculated\n\t\tmode: import\n\t\tsource = ```\n"
            + rows +
            "\t\t```\n")


def _mapping(rows, tag: int = 900) -> str:
    return ("table '" + ZMAP + "'\n"
            "\tlineageTag: " + TAG.format(tag) + "\n\n"
            "\tcolumn 'Analysis Category'\n\t\tdataType: string\n\t\tlineageTag: "
            + TAG.format(tag + 1) + "\n\t\tsourceColumn: Analysis Category\n\n"
            "\tcolumn 'Analysis Subcategory'\n\t\tdataType: string\n\t\tlineageTag: "
            + TAG.format(tag + 2) + "\n\t\tsourceColumn: Analysis Subcategory\n\n"
            "\tcolumn category_x_id\n\t\tdataType: string\n\t\tlineageTag: "
            + TAG.format(tag + 3) + "\n\t\tsourceColumn: category_x_id\n\n"
            f"\tpartition '{ZMAP}' = m\n"
            "\t\tmode: import\n\t\tsource =\n"
            "\t\t\t\tlet\n"
            "\t\t\t\t    Source = Table.FromRows(Json.Document(Binary.Decompress("
            f'Binary.FromText("{_encode(rows)}", BinaryEncoding.Base64), '
            "Compression.Deflate)), let _t = ((type nullable text) meta "
            '[Serialized.Text = true]) in type table [#"Analysis Category" = _t, '
            '#"Analysis Subcategory" = _t, category_x_id = _t])\n'
            "\t\t\t\tin\n"
            "\t\t\t\t    Source\n")


def _model(tmp_path: Path, tables: dict[str, str]) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n" + "".join(f"ref table '{n}'\n" for n in tables),
        encoding="utf-8")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    return definition


def _zmap_file(model: Path) -> Path:
    return model / "tables" / f"{ZMAP}.tmdl"


def _blob(model: Path) -> str:
    text = _zmap_file(model).read_text(encoding="utf-8")
    return re.search(r'Binary\.FromText\("([^"]+)"', text).group(1)


def _rows(model: Path) -> list:
    raw = base64.b64decode(_blob(model))
    return json.loads(zlib.decompress(raw, -zlib.MAX_WBITS).decode("utf-8"))


def _categories(model: Path) -> dict:
    code, out, err = run_cli("info", str(model), "--categories", "--json")
    assert code == 0, err
    return json.loads(out)


# ---------------------------------------------------------------------------
# the payload the fixer writes
# ---------------------------------------------------------------------------


def test_the_fixer_writes_the_payload_in_the_original_json_layout(tmp_path):
    """The rows are written with a comma and a space between items."""
    rows = [["Sales", "", "Ad Group_y"]]
    model = _model(tmp_path, {ZMAP: _mapping(rows)})
    code, payload = run_fix(model, "A003")
    assert code == 0, payload
    expected = rows + [["Sales", "", "Account_y"], ["Sales", "", "Service_y"]]
    assert _rows(model) == expected
    assert _blob(model) == _encode(expected)


def test_a_second_fix_writes_nothing(tmp_path):
    model = _model(tmp_path, {ZMAP: _mapping([["Sales", "", "Ad Group_y"]])})
    run_fix(model, "A003")
    first = _zmap_file(model).read_bytes()
    run_fix(model, "A003")
    assert _zmap_file(model).read_bytes() == first


# ---------------------------------------------------------------------------
# which mapping rows attribute a category
# ---------------------------------------------------------------------------


def _shop(tmp_path, mapping_rows, axis_rows='\t\t\t\t{ ("Revenue", NAMEOF(\'Shop\'[Revenue]), 0, "Sales_x") }\n',
          axis_name="x-Selector 1"):
    return _model(tmp_path, {
        "Orders": _fact("Orders", 1, _measures("Revenue = SUM(Orders[amount])")),
        axis_name: _axis(axis_name, 2, axis_rows),
        ZMAP: _mapping(mapping_rows),
    })


def test_a_three_column_row_attributes_its_third_value(tmp_path):
    model = _shop(tmp_path, [["Sales", "", "Sales_x"]])
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == ["Sales"]


def test_a_two_column_row_attributes_nothing(tmp_path):
    model = _shop(tmp_path, [["Sales", "Sales_x"]])
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == []


def test_a_row_with_a_null_category_is_ignored(tmp_path):
    model = _shop(tmp_path, [[None, "", "Sales_x"]])
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == []


def test_a_four_value_row_uses_the_third_value(tmp_path):
    model = _shop(tmp_path, [["Sales", "Sub", "Sales_x", "ignored"]])
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == ["Sales"]


# ---------------------------------------------------------------------------
# which axis tables attribute
# ---------------------------------------------------------------------------


def test_a_plot_specific_row_does_not_attribute(tmp_path):
    model = _shop(tmp_path, [["Sales", "", "Sales_x"]], axis_name="x-Plot Specific 1")
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == []


def test_a_plot_specific_row_leaves_the_fact_uncovered(tmp_path):
    model = _shop(tmp_path, [["Sales", "", "Sales_x"]], axis_name="x-Plot Specific 1")
    code, payload = run_check(model, "O015")
    found = violations(payload, "O015")
    assert found, "the fact was exempt through a plot-specific row"
    assert "Orders" in found[0]["message"], found[0]


# ---------------------------------------------------------------------------
# the measure-reference graph
# ---------------------------------------------------------------------------


def test_a_qualified_measure_reference_is_traced(tmp_path):
    model = _model(tmp_path, {
        "Orders": _fact("Orders", 1),
        "Coffee Measures": _fact("Coffee Measures", 3, _measures(
            "Store Revenue = SUM(Orders[amount])",
            "Revenue = 'Coffee Measures'[Store Revenue]")),
        "x-Selector 1": _axis("x-Selector 1", 2,
                               '\t\t\t\t{ ("Revenue", NAMEOF(\'Coffee Measures\'[Revenue]), 0, "Sales_x") }\n'),
        ZMAP: _mapping([["Sales", "", "Sales_x"]]),
    })
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == ["Sales"], facts


def test_a_padded_measure_reference_is_traced(tmp_path):
    model = _model(tmp_path, {
        "Orders": _fact("Orders", 1),
        "Coffee Measures": _fact("Coffee Measures", 3, _measures(
            "Store Revenue = SUM(Orders[amount])",
            "Revenue = [ Store Revenue ]")),
        "x-Selector 1": _axis("x-Selector 1", 2,
                               '\t\t\t\t{ ("Revenue", NAMEOF(\'Coffee Measures\'[Revenue]), 0, "Sales_x") }\n'),
        ZMAP: _mapping([["Sales", "", "Sales_x"]]),
    })
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == ["Sales"], facts


# ---------------------------------------------------------------------------
# the shape an axis row must have
# ---------------------------------------------------------------------------


def test_a_row_split_over_two_lines_attributes(tmp_path):
    model = _shop(tmp_path, [["Sales", "", "Sales_x"]],
                  axis_rows='\t\t\t\t{ ("Revenue",\n\t\t\t\t  NAMEOF(\'Shop\'[Revenue]), 0, "Sales_x") }\n')
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == ["Sales"], facts


def test_a_row_with_a_fractional_order_does_not_attribute(tmp_path):
    model = _shop(tmp_path, [["Sales", "", "Sales_x"]],
                  axis_rows='\t\t\t\t{ ("Revenue", NAMEOF(\'Shop\'[Revenue]), 1.5, "Sales_x") }\n')
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == [], facts


def test_a_row_with_an_empty_label_does_not_attribute(tmp_path):
    model = _shop(tmp_path, [["Sales", "", "Sales_x"]],
                  axis_rows='\t\t\t\t{ ("", NAMEOF(\'Shop\'[Revenue]), 0, "Sales_x") }\n')
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == [], facts


def test_a_commented_row_does_not_attribute(tmp_path):
    model = _shop(tmp_path, [["Sales", "", "Sales_x"]],
                  axis_rows='\t\t\t\t// { ("Revenue", NAMEOF(\'Shop\'[Revenue]), 0, "Sales_x") }\n')
    facts = _categories(model)["fact_tables"]
    assert facts["Orders"] == [], facts
