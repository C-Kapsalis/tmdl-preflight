"""M022 diagram-layout-blank, and fix exiting 2 when a repair is refused."""
from __future__ import annotations

import json

from conftest import run_check, run_cli, run_fix, violations
from tmdl_preflight.rules.hygiene import canonical_diagram_layout

RULE = "diagram-layout-blank"


def _layout(project):
    return project / "BikeShop.SemanticModel" / "diagramLayout.json"


def test_no_layout_is_fine(project):
    _layout(project).unlink(missing_ok=True)
    code, payload = run_check(project, RULE)
    assert code == 0 and violations(payload) == []


def test_stale_layout_is_reported_then_blanked(project):
    stale = json.loads(canonical_diagram_layout())
    stale["diagrams"][0]["nodes"] = [{"nodeIndex": "Stores", "location": {"x": 10, "y": 20}}]
    _layout(project).write_text(json.dumps(stale, indent=2), encoding="utf-8")
    code, payload = run_check(project, RULE, strict=True)
    assert code == 1 and len(violations(payload)) == 1
    before = _layout(project).read_bytes()
    code, out, _err = run_cli("fix", project, "--select", RULE, "--dry-run", "--no-config")
    assert code == 0 and _layout(project).read_bytes() == before
    code, payload = run_fix(project, RULE)
    assert code == 0
    assert _layout(project).read_text(encoding="utf-8") == canonical_diagram_layout()
    first = _layout(project).read_bytes()
    run_fix(project, RULE)
    assert _layout(project).read_bytes() == first
    code, payload = run_check(project, RULE, strict=True)
    assert code == 0


def test_not_run_unless_selected(project):
    _layout(project).write_text("{}", encoding="utf-8")
    code, payload = run_check(project)
    assert not violations(payload, "M022")


def test_refused_repair_exits_2(project, monkeypatch):
    from tmdl_preflight.edits import EditRefused
    from tmdl_preflight.rules import report

    bm = next((project / "BikeShop.Report").rglob("*.bookmark.json"))
    data = json.loads(bm.read_text(encoding="utf-8"))
    data.setdefault("options", {})["madeUpKey"] = True
    bm.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def refuse(_text):
        raise EditRefused("proof failed")

    monkeypatch.setattr(report, "strip_illegal_options", refuse)
    before = bm.read_bytes()
    code, payload = run_fix(project, "B003")
    assert code == 2
    assert payload["refused_fixes"] and bm.name in payload["refused_fixes"][0]
    assert bm.read_bytes() == before
