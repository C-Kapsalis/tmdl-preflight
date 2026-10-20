"""Integration pattern: helper measures.

* C-intermediary-helper-folder (test_helper_measure_naming_convention):
  intermediary helpers (``-Foo``) carry a displayFolder. The template-superset
  half is a tmdl-drift-doctor detect assertion and is not covered here.
* C-helper-measures-hidden (test_helper_measures_are_hidden): helper-named
  measures are hidden unless on the always-visible list.
* C-unused-helper-measures (test_helper_measure_dependencies): info only.
"""
from __future__ import annotations

import pytest

from conftest import run_check, run_fix, violations

STANDIN = "layer3_integration_standin"


def _model(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Performance.SemanticModel"
class TestIntermediaryHelperFolder:
    RULE = "intermediary-helper-folder"

    def test_helper_measure_naming_convention(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0, payload
        assert violations(payload) == []

    def test_intermediary_without_folder_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1 and "-Base Cups" in found[0]["message"]
class TestHelperMeasuresHidden:
    RULE = "helper-measures-hidden"

    def test_helper_measures_are_hidden(self, stand_in):
        # f-All and f-Matrix Title are visible but on the always-visible list
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0, payload
        assert violations(payload) == []

    def test_visible_helper_fails(self, stand_in):
        code, payload = run_check(_model(stand_in, "failing_db"), self.RULE, strict=True)
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "i-Debug" in found[0]["message"]
        assert "diagnostic_helper" in found[0]["message"]

    def test_fix_hides_and_is_idempotent(self, stand_in):
        model = _model(stand_in, "failing_db")
        code, _ = run_fix(model, self.RULE)
        assert code == 0
        first = (model / "definition" / "tables" / "Helper Measures.tmdl").read_bytes()
        code, _ = run_fix(model, self.RULE)
        assert (model / "definition" / "tables" / "Helper Measures.tmdl").read_bytes() == first
        code, payload = run_check(model, self.RULE, strict=True)
        assert code == 0

    def test_always_visible_list_uses_generic_names(self):
        import json
        from conftest import run_cli
        code, out, _ = run_cli("rules", "--json")
        rule = next(r for r in json.loads(out) if r["name"] == self.RULE)
        assert "i-HTML x/y Selector-2" in rule["options"]["always_visible"]
        assert "f-All" in rule["options"]["always_visible"]
class TestUnusedHelperMeasures:
    RULE = "unused-helper-measures"

    def test_helper_measure_dependencies(self, stand_in):
        code, payload = run_check(_model(stand_in), self.RULE, strict=True)
        assert code == 0  # info only, never fails
        found = violations(payload)
        assert all(v["severity"] == "info" for v in found)
        unused = "\n".join(v["message"] for v in found if "unused" in v["message"].lower())
        assert "-helper Base" in unused        # referenced nowhere
        assert "f-Orders" not in unused        # referenced by f-All / f-Router

    def test_reference_in_report_json_counts(self, stand_in):
        root = stand_in(STANDIN) / "universal"
        vis = root / "Roastery.Report" / "definition" / "pages" / "p1" / "visuals" / "v2" / "visual.json"
        vis.write_text('{"name": "v2", "measure": "-helper Base"}\n', encoding="utf-8")
        code, payload = run_check(root / "Performance.SemanticModel", self.RULE)
        unused = "\n".join(v["message"] for v in violations(payload) if "unused" in v["message"].lower())
        assert "-helper Base" not in unused
