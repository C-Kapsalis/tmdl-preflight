"""``report relationships``: the topology of a model's relationships.

The report says how many relationships the model has, how many are active,
which cardinalities and cross-filtering directions they use, which tables
take part and which stand alone, and which tables are the hubs.

The reference reads the relationships file itself, so a relationship block
on the first line of the file counts too.
"""
from __future__ import annotations

import json

from conftest import run_cli

TREE = "rp_reports"


def _model(stand_in):
    return stand_in(TREE) / "Growth.SemanticModel"


def test_the_text_report_has_the_reference_layout(stand_in):
    code, out, _err = run_cli("report", "relationships", str(_model(stand_in)))
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "=" * 60
    assert lines[1] == "RELATIONSHIP ANALYSIS"
    assert lines[2] == "=" * 60
    assert lines[4].startswith("📂 Reading: ")
    assert lines[4].endswith("/Growth.SemanticModel/definition/relationships.tmdl")
    assert lines[5] == "✅ Found 4 relationships"
    assert lines[7].startswith("📂 Scanning tables in: ")
    assert lines[7].endswith("/Growth.SemanticModel/definition/tables")
    assert lines[8] == "✅ Found 8 tables"
    assert lines[10] == "🔍 Analyzing relationship topology..."
    assert lines[11] == "✅ Analysis complete"
    assert lines[13] == "=" * 60
    assert lines[14] == "SUMMARY"
    assert lines[15] == "=" * 60
    assert lines[17] == "Total Relationships:     4"
    assert lines[18] == "  - Active:              3"
    assert lines[19] == "  - Inactive:            1"
    assert lines[21] == "Cardinality Types:"
    assert lines[22] == "  - many_to_one          3"
    assert lines[23] == "  - one_to_one           1"
    assert lines[25] == "Cross-Filtering:"
    assert lines[26] == "  - Unidirectional:      3"
    assert lines[27] == "  - Bidirectional:       1"
    assert lines[29] == "  Bidirectional Relationships:"
    assert lines[30] == "    Sales[date] <-> __Calendar[date]"
    assert lines[32] == "Tables:"
    assert lines[33] == "  - Total:               8"
    assert lines[34] == "  - With relationships:  4"
    assert lines[35] == "  - Orphans:             4"
    assert lines[37] == "  Orphan Categories:"
    assert lines[38] == "    - Report tables:       2"
    assert lines[39] == "    - Selector tables:   1"
    assert lines[40] == "    - Other:             1"
    assert lines[42] == "  Other Orphan Tables:"
    assert lines[43] == "    - Old Import"
    assert lines[45] == "Hub Tables (most connected):"
    assert lines[46] == "  - Sales                          3 relationships"
    assert lines[47] == "  - _Products                      2 relationships"
    assert lines[48] == "  - __Calendar                     2 relationships"
    assert lines[49] == "  - Report Helpers                 1 relationships"
    assert lines[-3] == "=" * 60
    assert lines[-2] == "ANALYSIS COMPLETE"
    assert lines[-1] == "=" * 60


def test_the_json_report_has_the_reference_layout(stand_in):
    code, out, _err = run_cli("report", "relationships", str(_model(stand_in)), "--json")
    assert code == 0
    data = json.loads(out)
    assert list(data) == [
        "total_relationships", "active_relationships", "inactive_relationships",
        "cardinality_types", "cross_filtering", "bidirectional_relationships",
        "tables", "orphan_categories", "hub_tables",
    ]
    assert data["total_relationships"] == 4
    assert data["active_relationships"] == 3
    assert data["inactive_relationships"] == 1
    assert list(data["cardinality_types"]) == ["many_to_one", "one_to_one"]
    assert data["cardinality_types"] == {"many_to_one": 3, "one_to_one": 1}
    assert data["bidirectional_relationships"] == [
        {"from": "Sales[date]", "to": "__Calendar[date]", "id": "bbbb-2"},
    ]
    assert data["tables"] == {"total": 8, "with_relationships": 4, "orphans": 4}
    assert list(data["orphan_categories"]) == [
        "report_tables", "selector_tables", "other_orphans",
    ]
    assert data["orphan_categories"] == {
        "report_tables": ["x-Selector 1", "y-Selector 1"],
        "selector_tables": ["z-Selector Format"],
        "other_orphans": ["Old Import"],
    }
    assert [h["table"] for h in data["hub_tables"]] == [
        "Sales", "_Products", "__Calendar", "Report Helpers",
    ]


def test_a_relationship_on_the_first_line_of_the_file_counts(stand_in, tmp_path):
    import shutil

    model = _model(stand_in)
    rels = model / "definition" / "relationships.tmdl"
    rels.write_text(rels.read_text(encoding="utf-8"), encoding="utf-8")
    text = rels.read_text(encoding="utf-8")
    first, _, rest = text.partition("\n\n")
    rels.write_text(first + "\n" + rest, encoding="utf-8")
    code, out, _err = run_cli("report", "relationships", str(model), "--json")
    assert code == 0
    assert json.loads(out)["total_relationships"] == 4
