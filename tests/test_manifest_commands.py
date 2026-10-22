"""The manifest, schema-check and refs commands."""
from __future__ import annotations

import json

from conftest import run_cli

FLEET = "measure_organization_fleet"
MODEL = "universal/Performance.SemanticModel"


def _manifest(path):
    return path / "generated" / "performance-manifest.json"


def test_manifest_writes_then_checks_then_detects_drift(stand_in):
    model = stand_in(FLEET) / MODEL
    code, out, _ = run_cli("manifest", model, "--no-config")
    assert code == 0 and _manifest(model).is_file()
    doc = json.loads(_manifest(model).read_text(encoding="utf-8"))
    ads = next(t for t in doc["tables"] if t["name"] == "Ads")
    assert ads["classification"] == "fact" and ads["bq_source"]["table"] == "ads_n"
    assert ads["bq_source"]["fqtn_default"] == "example-project-2.universal_db.ads_n"
    assert list(doc)[:4] == ["model", "source_model_path", "generated_by", "bigquery"]
    first = _manifest(model).read_bytes()
    assert run_cli("manifest", model, "--no-config")[0] == 0
    assert _manifest(model).read_bytes() == first          # byte-stable
    assert run_cli("manifest", model, "--check", "--no-config")[0] == 0
    _manifest(model).write_bytes(first + b" ")
    code, _o, err = run_cli("manifest", model, "--check", "--no-config")
    assert code == 1 and err.startswith("DRIFT:")
    _manifest(model).unlink()
    code, _o, err = run_cli("manifest", model, "--check", "--no-config")
    assert code == 1 and err.startswith("MISSING:")


def test_manifest_refuses_a_model_that_breaks_its_target_contract(stand_in, tmp_path):
    fleet = stand_in(FLEET)
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"universal": {"model_path": MODEL,
                                                 "project": "another-project"}}), encoding="utf-8")
    code, _o, err = run_cli("manifest", fleet / MODEL, "--targets", targets, "--no-config")
    assert code == 1 and "warehouse targets must match" in err
    assert not _manifest(fleet / MODEL).exists()


def test_manifest_warns_about_an_unregistered_model(stand_in, tmp_path):
    fleet = stand_in(FLEET)
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"other": {"model_path": "x/Y.SemanticModel"}}), encoding="utf-8")
    code, _o, err = run_cli("manifest", fleet / MODEL, "--targets", targets, "--no-config")
    assert code == 0
    assert err.startswith("WARNING: ")
    assert "is not in targets.json — no client_id" in err
    assert "warehouse derived from the model's v-BQ_project only." in err


def test_manifest_rejects_a_folder_without_definition(tmp_path):
    code, _o, err = run_cli("manifest", tmp_path, "--no-config")
    assert code == 2 and "definition" in err


def test_schema_check_against_a_snapshot(stand_in, tmp_path):
    model = stand_in(FLEET) / MODEL
    run_cli("manifest", model, "--no-config")
    doc = json.loads(_manifest(model).read_text(encoding="utf-8"))
    snapshot = {}
    for t in doc["tables"]:
        src = (t.get("bq_source") or {}).get("table")
        if src:
            snapshot[src] = [{"name": c["bqColumn"], "type": "STRING"}
                             for c in t.get("columns", []) if c.get("bqColumn")]
            snapshot[src].append({"name": "Extra Col", "type": "STRING"})
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(snapshot), encoding="utf-8")
    code, out, _ = run_cli("schema-check", "--manifest", _manifest(model), "--schema", schema,
                           "--strict")
    assert code == 0, out
    result = json.loads(_manifest(model).with_name("performance-manifest.bq.json")
                        .read_text(encoding="utf-8"))
    ads = next(t for t in result["tables"] if t["name"] == "Ads")
    assert ads["bq_source"]["drift"]["not_surfaced_in_pbi"] == ["Extra Col"]
    # drop a column from the warehouse: strict fails
    first = next(iter(snapshot))
    snapshot[first] = snapshot[first][1:]
    schema.write_text(json.dumps(snapshot), encoding="utf-8")
    code, _o, _e = run_cli("schema-check", "--manifest", _manifest(model), "--schema", schema,
                           "--strict")
    assert code == 1
    assert run_cli("schema-check", "--manifest", _manifest(model), "--schema", schema)[0] == 0


def _sql(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_schema_check_sql_dir(tmp_path):
    root = tmp_path / "sql"
    _sql(root, "05/orders_v.sql", "select id, `amount`, x AS region from t -- note\n")
    _sql(root, "05/visits_v.sql", "{{ config(materialized='view') }}\nselect * from {{ ref('visits_base') }}")
    _sql(root, "05/visits_base.sql", "select visit_id, visits from raw")
    _sql(root, "05/refunds_v.sql", "select id from t")
    entries = tmp_path / "entries.json"
    entries.write_text(json.dumps({"version": 1, "entries": [
        {"client": "spinout-05", "table": "Orders", "view": "orders_v", "columns": ["amount", "region"]},
        {"client": "spinout-05", "table": "Visits", "view": "visits_v", "columns": ["visits"]},
        {"client": "spinout-05", "table": "Refunds", "view": "refunds_v", "columns": ["amt"]},
        {"client": "spinout-05", "table": "Gone", "view": "gone_v", "columns": ["a"]},
    ]}), encoding="utf-8")
    hb = tmp_path / "holdbacks.yml"
    code, out, _ = run_cli("schema-check", "--sql-dir", root, "--entries", entries,
                           "--holdbacks", hb, "--write-holdbacks")
    assert code == 3
    assert "✓ READY spinout-05 · Orders · orders_v" in out
    assert "✓ READY spinout-05 · Visits · visits_v" in out
    assert "✗ HELD  spinout-05 · Refunds · refunds_v" in out
    assert "amt" in out
    assert "view not in DBT" in out
    first = hb.read_bytes()
    run_cli("schema-check", "--sql-dir", root, "--entries", entries, "--holdbacks", hb,
            "--write-holdbacks")
    assert hb.read_bytes() == first
    code, _o, _e = run_cli("schema-check", "--sql-dir", tmp_path / "nope", "--entries", entries)
    assert code == 2


def test_refs_counts_anchored_shapes_by_layer(tmp_path):
    model = tmp_path / "Shop.SemanticModel" / "definition" / "tables"
    model.mkdir(parents=True)
    (model / "M.tmdl").write_text("measure 'Margin' = [Margin] + [Big Margin]\n", encoding="utf-8")
    rep = tmp_path / "Shop.Report" / "definition"
    rep.mkdir(parents=True)
    (rep / "visual.json").write_text('{"a": "Margin", "b": "Sales.Margin", "c": "Margin Trend"}',
                                     encoding="utf-8")
    old = tmp_path / "legacy" / "Old.SemanticModel"
    old.mkdir(parents=True)
    (old / "x.tmdl").write_text("[Margin]", encoding="utf-8")
    code, out, _ = run_cli("refs", "Margin", tmp_path, "--files")
    assert code == 0
    assert "  LIVE      model     1   report     2   total     3   files 2" in out
    assert "  non-live  model     1   report     0   total     1   files 1" in out
    assert "report bindings no model-side test checks" in out
    assert "non-live file(s) hidden" in out
    code, out, _ = run_cli("refs", "Nothing", tmp_path)
    assert code == 0 and "no references found" in out
