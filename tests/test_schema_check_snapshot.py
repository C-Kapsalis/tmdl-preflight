"""The schema check against an exported warehouse snapshot.

The check answers one question: does the warehouse still have every column
the model reads? A column the warehouse lost fails the run; a column the
model does not import is only information. The results live in the
manifest, in the table's own source object, so one document says what was
checked and how it went.
"""
from __future__ import annotations

import json

from conftest import run_cli

SNAPSHOT_NOTE = ("Schema snapshot from the dataset above. Standardized *_n tables share a "
                 "schema across orgs, so a dev dataset (e.g. spinout_01_db) is "
                 "representative of the prod baseline.")


def _manifest_doc() -> dict:
    return {
        "model": "Warehouse",
        "source_model_path": "Warehouse.SemanticModel",
        "generated_by": "tmdl-preflight manifest",
        "bigquery": {
            "model_project": "example-project-2",
            "model_dataset": "warehouse_db",
            "model_billing_project": "example-project-2",
            "project": "example-project-2",
            "dataset": "warehouse_db",
            "billing_project": "example-project-2",
            "warehouse": "internal",
            "note": "n/a",
        },
        "counts": {"tables": 5, "relationships": 0, "by_classification": {}},
        "domains": {},
        "tables": [
            {
                "name": "Orders",
                "classification": "fact",
                "column_count": 3,
                "domain": "Other",
                "bq_source": {"table": "orders_n", "date_column": "date"},
                "columns": [
                    {"name": "order_id", "dataType": "int64", "sourceColumn": "order_id",
                     "bqColumn": "order_id"},
                    {"name": "amount", "dataType": "double", "sourceColumn": "amount",
                     "bqColumn": "amount"},
                    {"name": "lost", "dataType": "int64", "sourceColumn": "lost",
                     "bqColumn": "lost"},
                ],
            },
            {
                "name": "Ghost",
                "classification": "fact",
                "column_count": 0,
                "domain": "Other",
                "bq_source": {"table": "ghost_n"},
            },
            {
                "name": "Static",
                "classification": "dimension",
                "column_count": 1,
                "domain": "Other",
                "columns": [{"name": "code", "dataType": "string", "sourceColumn": "code"}],
            },
            {
                "name": "Mystery",
                "classification": "fact",
                "column_count": 0,
                "domain": "Other",
                "unresolved_source": True,
            },
            {
                "name": "Types",
                "classification": "fact",
                "column_count": 2,
                "domain": "Other",
                "bq_source": {"table": "types_n"},
                "m_type_changes": {"clicks": "type number"},
                "columns": [
                    {"name": "clicks", "dataType": "int64", "sourceColumn": "clicks",
                     "bqColumn": "clicks"},
                    {"name": "flag", "dataType": "boolean", "sourceColumn": "flag",
                     "bqColumn": "flag"},
                ],
            },
        ],
        "relationships": [],
    }


def _snapshot() -> dict:
    return {
        "orders_n": [{"name": "order_id", "type": "INTEGER"},
                     {"name": "amount", "type": "FLOAT"},
                     {"name": "Extra Col", "type": "STRING"}],
        "types_n": [{"name": "clicks", "type": "STRING"},
                    {"name": "flag", "type": "INTEGER"}],
    }


def _write(tmp_path, doc=None, snapshot=None):
    manifest = tmp_path / "warehouse-manifest.json"
    manifest.write_text(json.dumps(doc if doc is not None else _manifest_doc(), indent=2),
                        encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(snapshot if snapshot is not None else _snapshot()), encoding="utf-8")
    return manifest, schema


def _check(tmp_path, *extra, manifest=None, snapshot=None, ignore=None):
    man, snap = _write(tmp_path, manifest, snapshot)
    argv = ["schema-check", "--manifest", man, "--schema", snap]
    if ignore is not None:
        path = tmp_path / "ignore.json"
        path.write_text(json.dumps(ignore), encoding="utf-8")
        argv += ["--ignore-columns", path]
    argv += list(extra)
    code, out, err = run_cli(*argv)
    written = tmp_path / "warehouse-manifest.bq.json"
    doc = json.loads(written.read_text(encoding="utf-8")) if written.is_file() else None
    return code, out, err, doc


def test_the_drift_keys_are_the_ones_the_contract_names(tmp_path):
    _code, _out, _err, doc = _check(tmp_path)
    orders = next(t for t in doc["tables"] if t["name"] == "Orders")
    drift = orders["bq_source"]["drift"]
    assert list(drift) == ["missing_in_bq", "not_surfaced_in_pbi"]
    assert drift["missing_in_bq"] == ["lost"]
    assert drift["not_surfaced_in_pbi"] == ["Extra Col"]


def test_the_result_lives_in_the_source_object(tmp_path):
    _code, _out, _err, doc = _check(tmp_path)
    orders = next(t for t in doc["tables"] if t["name"] == "Orders")
    assert list(orders["bq_source"])[-3:] == ["checked_against", "bq_columns", "drift"]
    assert orders["bq_source"]["checked_against"] == "example-project-2.warehouse_db.orders_n"
    assert [c["name"] for c in orders["bq_source"]["bq_columns"]] == ["order_id", "amount",
                                                                     "Extra Col"]
    assert "drift" not in orders and "error" not in orders and "unreachable" not in orders
    assert "bq_columns" not in orders


def test_an_unreachable_table_says_so_in_its_source_object(tmp_path):
    _code, _out, _err, doc = _check(tmp_path)
    ghost = next(t for t in doc["tables"] if t["name"] == "Ghost")
    assert ghost["bq_source"]["checked_against"] == "example-project-2.warehouse_db.ghost_n"
    assert ghost["bq_source"]["check_error"] == "NotFound: ghost_n is not in the schema snapshot"
    assert "bq_columns" not in ghost["bq_source"]
    assert "error" not in ghost and "unreachable" not in ghost


def test_an_ignored_column_keeps_the_snapshot_spelling(tmp_path):
    _code, _out, _err, doc = _check(tmp_path, ignore={"columns": ["Extra Col"]})
    orders = next(t for t in doc["tables"] if t["name"] == "Orders")
    drift = orders["bq_source"]["drift"]
    assert "not_surfaced_in_pbi" not in drift
    assert drift["ignored_bookkeeping"] == ["Extra Col"]
    assert doc["bq_schema_check"]["ignored_bookkeeping_columns"] == ["extra_col"]


def test_a_type_mismatch_names_the_change(tmp_path):
    _code, _out, _err, doc = _check(tmp_path)
    types = next(t for t in doc["tables"] if t["name"] == "Types")
    assert types["bq_source"]["drift"]["type_mismatch"] == [
        "clicks: PBI int64 vs BQ STRING (M Changed Type confirmed — deliberate conversion)",
        "flag: PBI boolean vs BQ INTEGER (no M Changed Type found — verify upstream)",
    ]


def test_the_summary_block_names_the_run(tmp_path):
    _code, _out, _err, doc = _check(tmp_path)
    block = doc["bq_schema_check"]
    assert list(block) == ["project", "dataset", "warehouse", "auth", "unresolved_sources",
                           "skipped_no_source", "checked_at", "tables_checked", "tables_failing",
                           "tables_needs_review", "tables_informational", "tables_type_mismatch",
                           "tables_unreachable", "ignored_bookkeeping_columns", "note"]
    assert block["project"] == "example-project-2"
    assert block["dataset"] == "warehouse_db"
    assert block["warehouse"] == "internal"
    assert block["auth"] == "schema snapshot schema.json"
    assert block["unresolved_sources"] == ["Mystery"]
    assert block["skipped_no_source"] == ["Mystery", "Static"]
    assert block["tables_checked"] == 2
    assert block["tables_failing"] == 1
    assert block["tables_needs_review"] == 0
    assert block["tables_informational"] == 1
    assert block["tables_type_mismatch"] == 1
    assert block["tables_unreachable"] == 1
    assert block["ignored_bookkeeping_columns"] == []
    assert block["note"] == SNAPSHOT_NOTE
    assert block["checked_at"].endswith("+00:00") and len(block["checked_at"]) == 25


def test_the_result_is_written_next_to_the_manifest(tmp_path):
    _code, _out, _err, _doc = _check(tmp_path)
    written = tmp_path / "warehouse-manifest.bq.json"
    assert written.is_file()
    assert not (tmp_path / "warehouse-manifest.bq.bq.json").exists()
    raw = written.read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw


def test_a_manifest_that_is_already_a_bq_file_is_rewritten_in_place(tmp_path):
    manifest, schema = _write(tmp_path)
    target = tmp_path / "warehouse-manifest.bq.json"
    manifest.rename(target)
    code, _out, err = run_cli("schema-check", "--manifest", target, "--schema", schema)
    assert code == 0, err
    assert target.is_file()
    assert not (tmp_path / "warehouse-manifest.bq.bq.json").exists()
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["bq_schema_check"]["tables_checked"] == 2


def test_the_console_report_says_what_was_found(tmp_path):
    code, out, err, _doc = _check(tmp_path)
    assert code == 0
    assert out.splitlines()[:6] == [
        "Auth: schema snapshot schema.json [internal warehouse]",
        "Checked 2 tables against example-project-2.warehouse_db -> "
        + str(tmp_path / "warehouse-manifest.bq.json"),
        "  FAILING       (PBI column missing in BigQuery): 1 table(s)",
        "  needs review  (programmatic renames — adjudicate via the M, e.g. /model-bq-drift): "
        "0 table(s)",
        "  informational (BQ column not imported in PBI):  1 table(s)",
        "  type mismatch (suspicious PBI<->BQ type pairs, informational -- each entry notes "
        "whether an M Changed Type confirms it): 1 table(s)",
    ]
    assert "  skipped (no BQ source — DAX/static tables): Mystery, Static" in out
    assert "  READ-ONLY ROUTING: this sweep never changes BigQuery objects." in out
    assert "    - unexpected production table/view regression -> open an issue with the " \
           "warehouse owners" in out
    assert err.splitlines() == [
        "  1 table(s) unreachable — check SA access to example-project-2.warehouse_db or pass "
        "an accessible --project/--dataset.",
        "  UNRESOLVED partition sources (extractor gap, fails --strict): Mystery",
    ]


def test_a_model_that_reads_no_warehouse_says_it_is_a_pass(tmp_path):
    doc = _manifest_doc()
    for t in doc["tables"]:
        t.pop("bq_source", None)
        t.pop("unresolved_source", None)
    code, out, err, _doc = _check(tmp_path, manifest=doc)
    assert code == 0
    assert "  note: this model reads no BigQuery — nothing to check (pass)." in out
    assert err == ""


def test_warehouse_tables_that_are_never_checked_are_a_coverage_gap(tmp_path):
    doc = _manifest_doc()
    code, out, err, _doc = _check(tmp_path, manifest=doc, snapshot={})
    assert code == 0
    assert "COVERAGE: warehouse-backed tables exist but none was checked — refusing to call " \
           "that a pass." in err
    assert "note: this model reads no BigQuery" not in out


def test_the_project_and_dataset_can_be_overridden(tmp_path):
    code, out, _err, doc = _check(tmp_path, "--project", "example-project-9",
                                  "--dataset", "other_db")
    assert code == 0
    orders = next(t for t in doc["tables"] if t["name"] == "Orders")
    assert orders["bq_source"]["checked_against"] == "example-project-9.other_db.orders_n"
    assert doc["bq_schema_check"]["project"] == "example-project-9"
    assert doc["bq_schema_check"]["dataset"] == "other_db"
    assert "Checked 2 tables against example-project-9.other_db -> " in out
