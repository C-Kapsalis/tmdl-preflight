"""M022 diagram-layout-blank: the report, the scope and the line endings.

The diagram layout is the model view Power BI Desktop shows; it is not
regenerated when a table is renamed or dropped, so a stale layout keeps
pointing at nodes that are gone. The blank layout carries no node at all,
so it cannot go stale.

The stand-in is the fictional bike-shop project; the tests add the
layouts they need.
"""
from __future__ import annotations

import json

from conftest import run_check, run_cli, violations
from tmdl_preflight.rules.hygiene import canonical_diagram_layout

RULE = "diagram-layout-blank"


def _layout(project):
    return project / "BikeShop.SemanticModel" / "diagramLayout.json"


def _stale_layout():
    stale = json.loads(canonical_diagram_layout())
    stale["diagrams"][0]["nodes"] = [{"nodeIndex": "Stores", "location": {"x": 10, "y": 20}}]
    return json.dumps(stale, indent=2) + "\n"


def _notes(payload):
    return "\n".join(payload.get("notes", []))


def test_the_check_says_how_many_layouts_it_found(project):
    _layout(project).write_text(_stale_layout(), encoding="utf-8")
    code, payload = run_check(project, RULE)
    notes = _notes(payload)
    assert "Found 1 diagramLayout.json file(s): 0 already blank, 1 to normalize." in notes
    assert "✗ 1 diagram layout(s) carry stale/non-empty node data:" in notes
    assert "    BikeShop.SemanticModel/diagramLayout.json" in notes


def test_a_clean_layout_says_so(project):
    _layout(project).write_text(canonical_diagram_layout(), encoding="utf-8")
    code, payload = run_check(project, RULE)
    notes = _notes(payload)
    assert "Found 1 diagramLayout.json file(s): 1 already blank, 0 to normalize." in notes
    assert "✓ All diagram layouts are already blank." in notes


def test_a_project_without_a_layout_says_nothing_to_do(project):
    code, payload = run_check(project, RULE)
    assert "No diagramLayout.json files found — nothing to blank." in _notes(payload)


def test_a_dry_run_says_what_it_would_blank_and_writes_nothing(project):
    _layout(project).write_text(_stale_layout(), encoding="utf-8")
    before = _layout(project).read_bytes()
    code, out, err = run_cli("fix", project, "--select", RULE, "--dry-run", "--no-config")
    assert "Would blank: BikeShop.SemanticModel/diagramLayout.json" in out, out
    assert "(dry-run) 1 file(s) would be blanked." in out, out
    assert _layout(project).read_bytes() == before


def test_the_repair_blanks_the_layout(project):
    _layout(project).write_text(_stale_layout(), encoding="utf-8")
    code, out, err = run_cli("fix", project, "--select", RULE, "--no-config")
    assert "Blanked: BikeShop.SemanticModel/diagramLayout.json" in out, out
    assert "✓ Blanked 1 diagram layout(s)." in out, out
    assert _layout(project).read_text(encoding="utf-8") == canonical_diagram_layout()


def test_a_layout_the_tool_does_not_load_is_checked_too(project):
    """The layout is stale whoever owns it."""
    folder = project / "Loose.SemanticModel"
    folder.mkdir()
    (folder / "diagramLayout.json").write_text(_stale_layout(), encoding="utf-8")
    code, payload = run_check(project, RULE, strict=True)
    assert code == 1
    assert len(violations(payload)) == 1


def test_a_blank_layout_saved_with_windows_line_endings_is_not_stale(project):
    _layout(project).write_bytes(canonical_diagram_layout().replace("\n", "\r\n").encode("utf-8"))
    code, payload = run_check(project, RULE)
    assert violations(payload) == []
    before = _layout(project).read_bytes()
    code, out, err = run_cli("fix", project, "--select", RULE, "--no-config")
    assert _layout(project).read_bytes() == before
