"""Report-definition gates for failures that otherwise surface only at import time.

Required pages metadata
(F-pages-metadata-schema) and the Fabric hierarchy-level binding shape
(F-hierarchy-level-binding-shape). The report fixture is the layer-3
stand-in (fictional coffee roastery); ``universal`` passes, ``failing_db``
carries one defect of each kind.
"""
from __future__ import annotations

import json

import pytest

from conftest import run_check, violations


STANDIN = "layer3_integration_standin"
_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
           "pagesMetadata/1.1.0/schema.json")


def _report(stand_in, client="universal"):
    return stand_in(STANDIN) / client / "Roastery.Report"


class TestPagesMetadataSchema:
    """test_pages_metadata_has_required_schema"""

    def test_pages_metadata_has_required_schema(self, stand_in):
        report = _report(stand_in)
        pages = report / "definition" / "pages" / "pages.json"
        assert pages.exists(), f"missing pages metadata: {pages}"
        data = json.loads(pages.read_text(encoding="utf-8"))
        assert data.get("$schema") == _SCHEMA
        assert isinstance(data.get("pageOrder"), list)
        code, payload = run_check(report, "pages-metadata-schema")
        assert code == 0, payload
        assert violations(payload) == []

    def test_old_schema_url_fails(self, stand_in):
        code, payload = run_check(_report(stand_in, "failing_db"), "pages-metadata-schema")
        assert code == 1
        assert len(violations(payload)) == 1
        assert "pages.json" in (violations(payload)[0]["path"] or "")

    def test_missing_pages_json_fails(self, stand_in):
        report = _report(stand_in)
        (report / "definition" / "pages" / "pages.json").unlink()
        code, payload = run_check(report, "pages-metadata-schema")
        assert code == 1 and len(violations(payload)) == 1

    def test_page_order_not_a_list_fails(self, stand_in):
        report = _report(stand_in)
        pages = report / "definition" / "pages" / "pages.json"
        data = json.loads(pages.read_text(encoding="utf-8"))
        data["pageOrder"] = "p1"
        pages.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        code, payload = run_check(report, "pages-metadata-schema")
        assert code == 1 and len(violations(payload)) == 1


class TestHierarchyLevelBindingShape:
    """test_hierarchy_level_bindings_use_valid_fabric_shape"""

    def test_hierarchy_level_bindings_use_valid_fabric_shape(self, stand_in):
        code, payload = run_check(_report(stand_in), "hierarchy-level-binding-shape")
        assert code == 0, payload
        assert violations(payload) == []

    def test_level_inside_expression_fails(self, stand_in):
        code, payload = run_check(_report(stand_in, "failing_db"), "hierarchy-level-binding-shape")
        assert code == 1
        found = violations(payload)
        assert len(found) == 1
        assert "HierarchyLevel" in found[0]["message"]

    def test_missing_expression_fails(self, stand_in):
        report = _report(stand_in)
        vis = report / "definition" / "pages" / "p1" / "visuals" / "v1" / "visual.json"
        data = json.loads(vis.read_text(encoding="utf-8"))
        proj = data["visual"]["query"]["queryState"]["Category"]["projections"][0]
        proj["field"]["HierarchyLevel"] = {"Level": "Month"}
        vis.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        code, payload = run_check(report, "hierarchy-level-binding-shape")
        assert code == 1 and len(violations(payload)) == 1

    def test_unparseable_visual_fails(self, stand_in):
        report = _report(stand_in)
        vis = report / "definition" / "pages" / "p1" / "visuals" / "v2" / "visual.json"
        vis.write_text("{ not json", encoding="utf-8")
        code, payload = run_check(report, "hierarchy-level-binding-shape")
        assert code == 1 and len(violations(payload)) >= 1
