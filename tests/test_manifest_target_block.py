"""The manifest's target block, its table records and its relationships
(the target-block and document-shape half of the manifest command).

The manifest is read by the pipelines next to the model, so its shape is a
contract: the target block is named ``bigquery``, its keys keep their order,
and every table record lists its keys in the same order.
"""
from __future__ import annotations

import json

from conftest import run_cli

FIXTURE = "manifest_target"
MODEL = "Warehouse.SemanticModel"


def _manifest(model):
    return model / "generated" / "warehouse-manifest.json"


def _build(stand_in, tmp_path):
    model = stand_in(FIXTURE) / MODEL
    code, out, err = run_cli("manifest", model, "--no-config")
    assert code == 0, err
    return model, json.loads(_manifest(model).read_text(encoding="utf-8"))


def test_target_block_is_named_bigquery_and_keeps_its_key_order(stand_in, tmp_path):
    model, doc = _build(stand_in, tmp_path)
    assert "bigquery" in doc
    assert list(doc)[:4] == ["model", "source_model_path", "generated_by", "bigquery"]
    block = doc["bigquery"]
    assert list(block) == ["model_project", "model_dataset", "model_billing_project",
                           "project", "dataset", "billing_project", "warehouse", "note"]


def test_target_block_note_is_the_contracts_own_words(stand_in, tmp_path):
    _model, doc = _build(stand_in, tmp_path)
    assert doc["bigquery"]["note"] == (
        "Model declarations from expressions.tmdl must match the warehouse target contract "
        "in real_clients_registry.yml; registry bq_project/bq_dataset values are never "
        "allowed to mask a stale model target.")
    assert doc["generated_by"] == "tmdl-preflight manifest"


def test_a_registered_model_stamps_the_registry_fields(stand_in, tmp_path):
    model = stand_in(FIXTURE) / MODEL
    targets = tmp_path / "targets.yml"
    targets.write_text("clients:\n"
                       "  spinout-05:\n"
                       "    model_path: manifest_target/Warehouse.SemanticModel\n"
                       "    bq_project: example-project-2\n"
                       "    bq_dataset: warehouse_db\n", encoding="utf-8")
    code, _out, err = run_cli("manifest", model, "--targets", targets, "--no-config")
    assert code == 0, err
    block = json.loads(_manifest(model).read_text(encoding="utf-8"))["bigquery"]
    assert list(block) == ["model_project", "model_dataset", "model_billing_project",
                           "project", "dataset", "billing_project", "client_id",
                           "registry_project", "registry_dataset", "warehouse", "note"]
    assert block["client_id"] == "spinout-05"
    assert block["registry_project"] == "example-project-2"
    assert block["registry_dataset"] == "warehouse_db"


def test_fqtn_default_lives_in_the_source_object(stand_in, tmp_path):
    _model, doc = _build(stand_in, tmp_path)
    orders = next(t for t in doc["tables"] if t["name"] == "Orders")
    assert "fqtn_default" not in orders
    assert orders["bq_source"]["fqtn_default"] == "example-project-2.warehouse_db.orders_n"
    assert list(orders["bq_source"])[-1] == "fqtn_default"
    # a selector that reads the warehouse gets one too
    selector = next(t for t in doc["tables"] if t["name"] == "z-Selector Spend")
    assert selector["bq_source"]["fqtn_default"] == "example-project-2.warehouse_db.spend_n"
    assert all("fqtn_default" not in t for t in doc["tables"])


def test_domains_are_assigned_by_the_shipped_rules(stand_in, tmp_path):
    _model, doc = _build(stand_in, tmp_path)
    domains = {t["name"]: t.get("domain") for t in doc["tables"]}
    assert domains["__Calendar"] == "Core / Shared"
    assert domains["Campaign Stats"] == "Advertising"
    assert domains["GA4 Sessions"] == "GA4"
    # a table outside the data classes carries no domain
    assert domains["z-Selector Spend"] is None
    assert doc["domains"] == {"Advertising": ["Campaign Stats"],
                              "Core / Shared": ["__Calendar"],
                              "GA4": ["GA4 Sessions"],
                              "Other": ["Orders"]}


def test_a_table_record_lists_its_keys_in_order(stand_in, tmp_path):
    _model, doc = _build(stand_in, tmp_path)
    orders = next(t for t in doc["tables"] if t["name"] == "Orders")
    assert list(orders)[:5] == ["name", "classification", "column_count", "domain",
                                "bq_source"]
    assert list(orders)[-1] == "columns"
    calendar = next(t for t in doc["tables"] if t["name"] == "__Calendar")
    assert list(calendar) == ["name", "classification", "column_count", "domain", "columns"]


def test_a_relationship_has_no_name_and_the_agreed_keys(stand_in, tmp_path):
    _model, doc = _build(stand_in, tmp_path)
    assert len(doc["relationships"]) == 1
    rel = doc["relationships"][0]
    assert list(rel) == ["fromTable", "fromColumn", "toTable", "toColumn", "isActive",
                         "crossFilteringBehavior", "fromCardinality", "toCardinality"]
    assert rel["fromTable"] == "Orders" and rel["toTable"] == "__Calendar"
    assert rel["isActive"] is True
    assert rel["crossFilteringBehavior"] == "single"
    assert rel["fromCardinality"] == "many" and rel["toCardinality"] == "one"


def test_a_type_step_keeps_the_spaces_it_was_written_with(tmp_path):
    from tmdl_preflight.manifest import parse_table

    path = tmp_path / "Types.tmdl"
    path.write_text(
        "table Types\n\n"
        "\tcolumn amount\n"
        "\t\tdataType: double\n"
        "\t\tsourceColumn: amount\n\n"
        "\tpartition Types = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("types_n", "date"),\n'
        '\t\t\t    ct = Table.TransformColumnTypes(Source,{{"amount", type  number}})\n'
        "\t\t\tin\n"
        "\t\t\t    ct\n", encoding="utf-8")
    table = parse_table(path)
    assert table["m_type_changes"] == {"amount": "type  number"}
