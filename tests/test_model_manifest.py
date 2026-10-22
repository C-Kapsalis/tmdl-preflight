"""Manifest extractor, warehouse-target guard and schema reconciliation
(B-manifest-test-port).

The manifest feeds the schema reconciliation, whose whole value is coverage:
a table whose warehouse source silently fails to parse is a table the check
never sees. These tests pin the parsing contracts:

  - every partition form resolves a warehouse source: the shared loader call,
    the inlined incremental-refresh query, and the navigator form;
  - a warehouse-speaking partition that resolves to nothing is stamped
    `unresolved_source` while static partitions stay silent;
  - Power Query renames reverse to warehouse column names even when the pair
    list wraps across lines; AddColumn-synthesized and calculated columns
    never claim a warehouse origin;
  - quoted relationship endpoints split correctly;
  - the template `Ads` table (inline window) resolves to `ads_n` as a fact.

API (proposed by H-model-manifest, H-manifest-source-resolution,
H-manifest-warehouse-target, H-source-schema-reconcile):
  tmdl_preflight.manifest: parse_table, derive_loaders, parse_renames,
    resolve_origin, split_endpoint, parse_inline_window,
    read_warehouse_target, check_warehouse_target, WarehouseTargetError,
    entry_for_model, load_targets
  tmdl_preflight.reconcile: classify_drift, suspicious_type_pair,
    load_ignore_columns
Drift classes `missing_in_bq` and `not_surfaced_in_pbi`; targets-file fields `project`,
`billing_project`, `dataset` (entry key kept as `client_id`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FIXTURES
_IMPORT_ERROR = None
try:
    from tmdl_preflight.manifest import (
        WarehouseTargetError,
        check_warehouse_target,
        derive_loaders,
        entry_for_model,
        load_targets,
        parse_inline_window,
        parse_renames,
        parse_table,
        read_warehouse_target,
        resolve_origin,
        split_endpoint,
    )
    from tmdl_preflight.reconcile import classify_drift, load_ignore_columns, suspicious_type_pair
except ImportError as exc:  # API proposed by the H-manifest specs, not built yet
    _IMPORT_ERROR = exc


@pytest.fixture(autouse=True)
def _require_manifest_api():
    if _IMPORT_ERROR is not None:
        pytest.fail(f"manifest/reconcile API missing: {_IMPORT_ERROR}")


FLEET = FIXTURES / "measure_organization_fleet"
UNIVERSAL_TABLES = FLEET / "universal/Performance.SemanticModel/definition/tables"
IGNORE_COLUMNS = FIXTURES / "model_manifest_ignore_columns.json"
# The internal warehouse project (no shipped default).
DEFAULT_PROJECT = "example-project-2"

# Literal inline-window queries (the shape the template's IR writer renders):
# view ads_n / date column `date` / floor parameter v-fromdate-ads, and
# view shopify_orders_n / date column created_at / no floor.
IR_ADS = 'let ir_dfilter = " cast(date as date) >= parse_date(\'%m/%d/%Y\', \'" & Date.ToText(DateTime.Date(RangeStart), "MM/dd/yyyy") & "\') and cast(date as date) < parse_date(\'%m/%d/%Y\', \'" & Date.ToText(DateTime.Date(RangeEnd), "MM/dd/yyyy") & "\') and cast(date as date) >= parse_date(\'%m/%d/%Y\', \'" & Date.ToText(v-fromdate-ads, "MM/dd/yyyy") & "\') ", ir_qstr = "SELECT * FROM `" & #"v-BQ_project" & "." & #"v-db" & "." & "ads_n" & "` where " & ir_dfilter & #"v-rows_limit", ir_src = Value.NativeQuery(GoogleBigQuery.Database([CommandTimeout=#duration(0,3,0,0), BillingProject=#"v-BQ_billing_project"]){[Name= #"v-BQ_project" ]}[Data], ir_qstr, null, [EnableFolding=true]) in ir_src'
IR_SHOP = 'let ir_dfilter = " cast(created_at as date) >= parse_date(\'%m/%d/%Y\', \'" & Date.ToText(DateTime.Date(RangeStart), "MM/dd/yyyy") & "\') and cast(created_at as date) < parse_date(\'%m/%d/%Y\', \'" & Date.ToText(DateTime.Date(RangeEnd), "MM/dd/yyyy") & "\') ", ir_qstr = "SELECT * FROM `" & #"v-BQ_project" & "." & #"v-db" & "." & "shopify_orders_n" & "` where " & ir_dfilter & #"v-rows_limit", ir_src = Value.NativeQuery(GoogleBigQuery.Database([CommandTimeout=#duration(0,3,0,0), BillingProject=#"v-BQ_billing_project"]){[Name= #"v-BQ_project" ]}[Data], ir_qstr, null, [EnableFolding=true]) in ir_src'


def _table_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "Fixture.tmdl"
    path.write_text(body, encoding="utf-8")
    return path


def _expressions_file(tmp_path: Path, project: str, dataset: str) -> Path:
    path = tmp_path / "expressions.tmdl"
    path.write_text(
        f'expression v-BQ_project = "{project}"\n'
        f'expression v-db = "{dataset}"\n',
        encoding="utf-8",
    )
    return path


def _read(expressions, entry):
    return read_warehouse_target(expressions, entry, default_project=DEFAULT_PROJECT)


def _check(model_rel, target, entry):
    return check_warehouse_target(model_rel, target, entry, True, default_project=DEFAULT_PROJECT)


# ---------------------------------------------------------------------------
# Registry/model warehouse-target contract
# ---------------------------------------------------------------------------

def test_external_registry_project_must_match_model_expression(tmp_path):
    entry = {
        "client_id": "spinout-05",
        "project": "example-project-1",
        "billing_project": "example-project-1",
    }
    bq = _read(_expressions_file(tmp_path, "example-project-2", "spinout_05_db"), entry)

    # The resolved target remains available for reporting, but the model value
    # is preserved so the registry override cannot manufacture a false pass.
    assert bq["project"] == "example-project-1"
    assert bq["model_project"] == "example-project-2"
    with pytest.raises(WarehouseTargetError, match="warehouse targets must match"):
        _check("spinout_05_db/Growth.SemanticModel", bq, entry)


def test_external_registry_project_aligned_with_model_passes(tmp_path):
    entry = {"client_id": "spinout-05", "project": "example-project-1"}
    bq = _read(_expressions_file(tmp_path, "example-project-1", "spinout_05_db"), entry)

    _check("spinout_05_db/Growth.SemanticModel", bq, entry)
    assert bq["warehouse"] == "external"


def test_registry_without_external_project_requires_internal_model(tmp_path):
    entry = {"client_id": "spinout-04"}
    bq = _read(_expressions_file(tmp_path, "unexpected-client-project", "spinout_04_db"), entry)

    with pytest.raises(WarehouseTargetError, match="example-project-2"):
        _check("spinout_04_db/Growth.SemanticModel", bq, entry)


def test_registered_dataset_override_must_match_model_expression(tmp_path):
    entry = {
        "client_id": "spinout-05",
        "project": "example-project-1",
        "dataset": "customer_reporting",
    }
    aligned = _read(_expressions_file(tmp_path, "example-project-1", "customer_reporting"), entry)
    _check("spinout_05_db/Growth.SemanticModel", aligned, entry)

    mismatched = _read(_expressions_file(tmp_path, "example-project-1", "spinout_05_db"), entry)
    with pytest.raises(WarehouseTargetError, match="dataset targets must match"):
        _check("spinout_05_db/Growth.SemanticModel", mismatched, entry)


def test_secondary_model_can_override_primary_dataset_contract():
    entry = {
        "client_id": "spinout-13",
        "model_path": "spinout_13_db/Growth.SemanticModel",
        "dataset": "spinout_12_db",
        "secondary_models": [{
            "path": "spinout_13_db/Performance.SemanticModel",
            "dataset": "spinout_13_db",
            "deviations": [],
        }],
    }

    primary = entry_for_model(entry, "spinout_13_db/Growth.SemanticModel")
    secondary = entry_for_model(entry, "spinout_13_db/Performance.SemanticModel")

    assert primary["dataset"] == "spinout_12_db"
    assert secondary["dataset"] == "spinout_13_db"
    assert secondary["client_id"] == "spinout-13"


def _fleet_mismatches(fleet_root: Path, targets: dict) -> list[str]:
    """The fleet pin, over a targets file."""
    mismatches = []
    for client_id, entry in targets.items():
        paths = [entry.get("model_path")]
        paths += [s.get("path") for s in entry.get("secondary_models") or []]
        for model_rel in (p for p in paths if p):
            model_entry = entry_for_model(entry, model_rel)
            expected_project = model_entry.get("project") or DEFAULT_PROJECT
            expressions = fleet_root / model_rel / "definition" / "expressions.tmdl"
            bq = _read(expressions, model_entry)
            actual_project = bq.get("model_project")
            if actual_project is None:
                continue
            if actual_project != expected_project:
                mismatches.append(
                    f"{client_id} · {model_rel}: model project={actual_project}, "
                    f"registry project={expected_project}")
            expected_dataset = model_entry.get("dataset")
            # convention check: ids of the spin-out naming scheme read <id>_db
            if expected_dataset is None and client_id.startswith("spinout-"):
                expected_dataset = f"{client_id.replace('-', '_')}_db"
            actual_dataset = bq.get("model_dataset")
            if expected_dataset and actual_dataset != expected_dataset:
                mismatches.append(
                    f"{client_id} · {model_rel}: model dataset={actual_dataset}, "
                    f"registry dataset={expected_dataset}")
    return mismatches


def test_registered_model_targets_match_registry_contract(stand_in):
    """Fleet pin: primary and secondary models cannot silently keep reading
    the internal warehouse after their targets entry moves them to an external
    project (or vice versa), and model-specific dataset overrides remain
    explicit. Models with no project parameter are outside this contract."""
    fleet = stand_in("measure_organization_fleet")
    targets = load_targets(FIXTURES / "model_manifest_targets.yml")
    mismatches = _fleet_mismatches(fleet, targets)
    assert not mismatches, (
        "Registry/model warehouse project mismatch(es):\n  - " + "\n  - ".join(mismatches))

    # flip one model's project: exactly one mismatch line
    expr = fleet / "spinout_02_db/Performance.SemanticModel/definition/expressions.tmdl"
    expr.write_text(expr.read_text(encoding="utf-8").replace(
        '"example-project-2"', '"unexpected-client-project"'), encoding="utf-8")
    flipped = _fleet_mismatches(fleet, targets)
    assert len(flipped) == 1 and "unexpected-client-project" in flipped[0]


# ---------------------------------------------------------------------------
# IR inline form + manifest integration
# ---------------------------------------------------------------------------

def test_parse_ir_inline_roundtrips_the_kernel_writer():
    assert parse_inline_window(IR_ADS) == ("ads_n", "date")
    assert parse_inline_window(IR_SHOP) == ("shopify_orders_n", "created_at")
    assert parse_inline_window('let s = source_filter_dates("x_n", "date") in s') is None


def test_ir_inlined_partition_resolves_bq_source(tmp_path):
    t = parse_table(_table_file(tmp_path, (
        "table Ads\n\n"
        "\tcolumn cost\n"
        "\t\tdataType: double\n"
        "\t\tsourceColumn: cost\n\n"
        "\tpartition Ads = m\n"
        "\t\tmode: import\n"
        f"\t\tsource = {IR_ADS}\n"
    )))
    assert t["bq_source"] == {"table": "ads_n", "date_column": "date",
                              "incremental_refresh": True}
    assert t["classification"] == "fact"
    assert "unresolved_source" not in t


def test_sfd_partition_resolves_bq_source(tmp_path):
    t = parse_table(_table_file(tmp_path, (
        "table Campaigns\n\n"
        "\tcolumn clicks\n"
        "\t\tdataType: int64\n"
        "\t\tsourceColumn: clicks\n\n"
        "\tpartition Campaigns = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("campaigns_n", "date", false, #"v-fromdate"),\n'
        "\t\t\t    out = Source\n"
        "\t\t\tin\n"
        "\t\t\t    out\n"
    )))
    assert t["bq_source"]["table"] == "campaigns_n"
    assert t["bq_source"]["date_column"] == "date"
    assert t["classification"] == "fact"


def test_client_wrapper_expressions_are_derived_and_matched(tmp_path):
    """Client models load through their own wrapper expressions (spinout-10's
    `_source_filter_dates_tickets_rowsLimit`); the warehouse-read set is
    derived from expressions.tmdl transitively - the dispatcher itself never
    mentions GoogleBigQuery."""
    expressions = (
        "expression _source_filter_dates_tickets_rowsLimit = ```\n"
        "\t\tlet Source = (table_name as text, date_column as text) =>\n"
        '\t\tlet q = Value.NativeQuery(GoogleBigQuery.Database(){[Name= #"v-BQ_project" ]}[Data], "x")\n'
        "\t\tin q\n"
        "\t```\n"
        "expression source_filter_dates =\n"
        '\t\tlet d = #"_source_filter_dates_tickets_rowsLimit" in d\n'
        "expression _dot_to_underscore =\n"
        "\t\tlet f = (t as text) => t in f\n"
        "expression _source_filter_dates-DBricks =\n"
        '\t\tlet Source = "// dead variant: GoogleBigQuery.Database() lives in a string" in Source\n'
    )
    wrappers = derive_loaders(expressions)
    assert "_source_filter_dates_tickets_rowsLimit" in wrappers
    assert "source_filter_dates" in wrappers          # transitive, via the call
    assert "_dot_to_underscore" not in wrappers       # no warehouse involvement
    # dead code inside a string literal is not a warehouse read
    assert "_source_filter_dates-DBricks" not in wrappers

    t = parse_table(_table_file(tmp_path, (
        "table Ticket Sales\n\n"
        "\tcolumn amount\n"
        "\t\tdataType: double\n"
        "\t\tsourceColumn: amount\n\n"
        "\tpartition Ticket Sales = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let s = #"_source_filter_dates_tickets_rowsLimit"("tickets_n", "date") in s\n'
    )), readers=wrappers)
    assert t["bq_source"]["table"] == "tickets_n"
    assert t["bq_source"]["date_column"] == "date"
    assert t["classification"] == "fact"


def test_duplicate_and_addcolumn_with_step_predecessors(tmp_path):
    """`#"Step Name"` predecessors: a DuplicateColumn after a named step must
    resolve to the SOURCE column, and a nested call in AddColumn's first
    argument must not hide the synthesized name."""
    t = parse_table(_table_file(tmp_path, (
        "table Logs\n\n"
        "\tcolumn 'created_at - Copy'\n"
        "\t\tdataType: dateTime\n"
        "\t\tsourceColumn: created_at - Copy\n\n"
        "\tcolumn Synth2\n"
        "\t\tdataType: int64\n"
        "\t\tsourceColumn: Synth2\n\n"
        "\tpartition Logs = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("logs_n", "created_at"),\n'
        '\t\t\t    #"Removed Columns" = Table.RemoveColumns(Source, {"noise"}),\n'
        '\t\t\t    dup = Table.DuplicateColumn(#"Removed Columns", "created_at", "created_at - Copy"),\n'
        '\t\t\t    add = Table.AddColumn(Table.SelectRows(dup, each [a] > 0), "Synth2", each "x")\n'
        "\t\t\tin\n"
        "\t\t\t    add\n"
    )))
    cols = {c["name"]: c for c in t["columns"]}
    assert cols["created_at - Copy"]["bqColumn"] == "created_at"
    assert cols["Synth2"].get("computed") and "bqColumn" not in cols["Synth2"]


def test_navigator_partition_resolves_bq_source(tmp_path):
    """Third partition form: the warehouse navigator -
    Schema{[Name="view",Kind="Table"]}[Data]."""
    t = parse_table(_table_file(tmp_path, (
        "table _Cluster Mappings\n\n"
        "\tpartition _Cluster Mappings = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        "\t\t\t    Source = GoogleBigQuery.Database([CommandTimeout=#duration(0,3,0,0)]),\n"
        '\t\t\t    DB = Source{[Name=#"v-BQ_project"]}[Data],\n'
        '\t\t\t    Schema = DB{[Name=#"v-db",Kind="Schema"]}[Data],\n'
        '\t\t\t    View = Schema{[Name="clustering_metadata_view",Kind="Table"]}[Data]\n'
        "\t\t\tin\n"
        "\t\t\t    View\n"
    )))
    assert t["bq_source"] == {"table": "clustering_metadata_view",
                              "date_column": None, "navigator": True}
    assert "unresolved_source" not in t


def test_commented_out_loader_never_wins(tmp_path):
    """M line comments are stripped before matching."""
    t = parse_table(_table_file(tmp_path, (
        "table Referrals\n\n"
        "\tpartition Referrals = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    // Source = source_filter_dates("old_view", "date"),\n'
        '\t\t\t    Source = source_filter_dates("new_view", "date")\n'
        "\t\t\tin\n"
        "\t\t\t    Source\n"
    )))
    assert t["bq_source"]["table"] == "new_view"


def test_wrapper_call_with_nonliteral_arg_is_unresolved(tmp_path):
    """A wrapper call that cannot be read still counts as speaking to the
    warehouse -> unresolved_source."""
    wrappers = {"_source_filter_dates_GA4"}
    t = parse_table(_table_file(tmp_path, (
        "table GA4 Traffic\n\n"
        "\tpartition GA4 Traffic = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let s = #"_source_filter_dates_GA4"(SomeVariable, "date") in s\n'
    )), readers=wrappers)
    assert t.get("unresolved_source") is True
    assert "bq_source" not in t


def test_bq_speaking_partition_without_source_is_unresolved(tmp_path):
    t = parse_table(_table_file(tmp_path, (
        "table Mystery\n\n"
        "\tpartition Mystery = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let q = Value.NativeQuery(GoogleBigQuery.Database()'
        '{[Name= #"v-BQ_project" ]}[Data], "SELECT 1") in q\n'
    )))
    assert t.get("unresolved_source") is True
    assert "bq_source" not in t


def test_static_partition_is_not_unresolved(tmp_path):
    t = parse_table(_table_file(tmp_path, (
        "table Conditional Formatting\n\n"
        "\tpartition Conditional Formatting = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let t = #table({"Name"}, {{"a"}}) in t\n'
    )))
    assert "unresolved_source" not in t
    assert "bq_source" not in t


# ---------------------------------------------------------------------------
# Renames / synthesized / calculated columns
# ---------------------------------------------------------------------------

def test_parse_renames_handles_wrapped_pair_lists():
    m_text = (
        "ren = Table.RenameColumns(Source, {\n"
        '    {"ad_strength", "Ad Strength"},\n'
        '    {"cost_micros", "Cost (micros)"}\n'
        "})"
    )
    renames = parse_renames(m_text)
    assert renames == {"Ad Strength": "ad_strength", "Cost (micros)": "cost_micros"}
    assert resolve_origin("Ad Strength", renames) == "ad_strength"


def test_synthesized_and_calculated_columns_have_no_bq_origin(tmp_path):
    t = parse_table(_table_file(tmp_path, (
        "table Ads\n\n"
        "\tcolumn cost\n"
        "\t\tdataType: double\n"
        "\t\tsourceColumn: cost\n\n"
        "\tcolumn 'Ad Strength'\n"
        "\t\tdataType: string\n"
        "\t\tsourceColumn: Ad Strength\n\n"
        "\tcolumn 'Margin' = DIVIDE([a], [b])\n"
        "\t\tdataType: double\n\n"
        "\tcolumn Synth\n"
        "\t\tdataType: int64\n"
        "\t\tsourceColumn: Synth\n\n"
        "\tpartition Ads = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("ads_n", "date"),\n'
        '\t\t\t    ren = Table.RenameColumns(Source, {\n'
        '\t\t\t        {"ad_strength", "Ad Strength"}}),\n'
        '\t\t\t    add = Table.AddColumn(ren, "Synth", each 1)\n'
        "\t\t\tin\n"
        "\t\t\t    add\n"
    )))
    cols = {c["name"]: c for c in t["columns"]}
    assert cols["cost"]["bqColumn"] == "cost"
    assert cols["Ad Strength"]["bqColumn"] == "ad_strength"     # rename reversed
    assert cols["Margin"]["calculated"] and "bqColumn" not in cols["Margin"]
    assert cols["Synth"].get("computed") and "bqColumn" not in cols["Synth"]


def test_transitive_renames_duplicates_and_synthesized_chains(tmp_path):
    """Two-hop renames resolve to the real column; DuplicateColumn copies
    resolve to their origin; a synthesized column stays synthesized through
    later renames (fb_Level -> Fb Level)."""
    t = parse_table(_table_file(tmp_path, (
        "table Posts\n\n"
        "\tcolumn 'FB Post Message'\n"
        "\t\tdataType: string\n"
        "\t\tsourceColumn: FB Post Message\n\n"
        "\tcolumn 'Property Position Rounded'\n"
        "\t\tdataType: int64\n"
        "\t\tsourceColumn: Property Position Rounded\n\n"
        "\tcolumn 'Fb Level'\n"
        "\t\tdataType: string\n"
        "\t\tsourceColumn: Fb Level\n\n"
        "\tpartition Posts = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("posts_n", "date"),\n'
        '\t\t\t    dup = Table.DuplicateColumn(Source, "property_position", "property_position_rounded"),\n'
        '\t\t\t    add = Table.AddColumn(dup, "fb_Level", each "Account"),\n'
        '\t\t\t    r1 = Table.RenameColumns(add, {{"first_message", "post.message"}, '
        '{"fb_Level", "Fb Level"}, {"property_position_rounded", "Property Position Rounded"}}),\n'
        '\t\t\t    r2 = Table.RenameColumns(r1, {{"post.message", "FB Post Message"}})\n'
        "\t\t\tin\n"
        "\t\t\t    r2\n"
    )))
    cols = {c["name"]: c for c in t["columns"]}
    assert cols["FB Post Message"]["bqColumn"] == "first_message"          # 2-hop rename
    assert cols["Property Position Rounded"]["bqColumn"] == "property_position"  # duplicate origin
    assert cols["Fb Level"].get("computed") and "bqColumn" not in cols["Fb Level"]


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

def test_split_endpoint_quoted_and_bare():
    assert split_endpoint("'FB Ads Reach Frequency'.date") == ("FB Ads Reach Frequency", "date")
    assert split_endpoint("Ads.date") == ("Ads", "date")


# ---------------------------------------------------------------------------
# Template model: the blocking case, pinned (stand-in template table)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (UNIVERSAL_TABLES / "Ads.tmdl").exists(),
                    reason="template model not present")
def test_universal_ads_ir_fact_resolves_ads_n():
    t = parse_table(UNIVERSAL_TABLES / "Ads.tmdl")
    assert t["classification"] == "fact"
    assert t["bq_source"]["table"] == "ads_n"
    assert t["bq_source"].get("incremental_refresh") is True


# ---------------------------------------------------------------------------
# Reconciliation semantics (pure - no warehouse client)
# ---------------------------------------------------------------------------

def test_classify_drift_three_way_split_and_trash_suppression():
    """missing_in_bq is FAILING, not_surfaced_in_pbi is informational, ignored
    columns land in ignored_bookkeeping - and per-table exceptions re-admit a
    column."""
    bq_cols = [{"name": "date", "type": "DATE"},
               {"name": "clicks", "type": "INTEGER"},
               {"name": "partition_date", "type": "DATE"},
               {"name": "updated_at_db", "type": "TIMESTAMP"},
               {"name": "extra_metric", "type": "FLOAT"}]
    trash = frozenset({"partition_date", "updated_at_db"})
    exceptions = frozenset({("Sitemap", "updated_at_db")})

    drift, resolved = classify_drift(["date", "clicks", "ghost_col"], bq_cols,
                                     "Ads", trash, exceptions)
    assert drift["missing_in_bq"] == ["ghost_col"]
    assert drift["not_surfaced_in_pbi"] == ["extra_metric"]
    assert drift["ignored_bookkeeping"] == ["partition_date", "updated_at_db"]
    assert resolved == {"date": "DATE", "clicks": "INTEGER"}

    drift_s, _ = classify_drift(["date"], bq_cols, "Sitemap", trash, exceptions)
    assert "updated_at_db" in drift_s["not_surfaced_in_pbi"]
    assert drift_s.get("ignored_bookkeeping") == ["partition_date"]


def test_classify_drift_struct_base_and_leaf_matching():
    bq_struct = [{"name": "comment", "type": "RECORD"}]
    drift, resolved = classify_drift(["comment.attachment"], bq_struct, "T")
    assert not drift.get("missing_in_bq") and resolved["comment.attachment"] == "RECORD"

    bq_flat = [{"name": "attachment", "type": "STRING"}]
    drift, resolved = classify_drift(["comment.attachment"], bq_flat, "T")
    assert not drift.get("missing_in_bq") and resolved["comment.attachment"] == "STRING"

    drift, _ = classify_drift(["comment.attachment"], [{"name": "other", "type": "X"}], "T")
    assert drift["missing_in_bq"] == ["comment.attachment"]


def test_programmatic_renames_downgrade_missing_to_needs_review(tmp_path):
    """A table renaming columns through functions has statically unknowable
    column names: unmatched columns are needs_review, never missing."""
    t = parse_table(_table_file(tmp_path, (
        "table __Anyfirst Cohort Calendar\n\n"
        "\tcolumn 'Anyfirst Cohort Date'\n"
        "\t\tdataType: dateTime\n"
        "\t\tsourceColumn: Anyfirst Cohort Date\n\n"
        "\tpartition __Anyfirst Cohort Calendar = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("__calendar_n", ""),\n'
        '\t\t\t    Custom1 = Table.PrefixColumns(Source, "Anyfirst_Cohort")\n'
        "\t\t\tin\n"
        "\t\t\t    Custom1\n"
    )))
    assert t["programmatic_renames"] is True

    drift, _ = classify_drift(["anyfirst_cohort_date"],
                              [{"name": "calendar_date", "type": "DATE"}],
                              "__Anyfirst Cohort Calendar",
                              programmatic_renames=True)
    assert "missing_in_bq" not in drift
    assert drift["needs_review"] == ["anyfirst_cohort_date"]


def test_type_mismatch_is_informational_with_m_confirmation_note(tmp_path):
    """Suspicious model/warehouse type pairs are INFORMATIONAL, and each entry
    states whether the partition M carries an explicit Changed Type."""
    assert not suspicious_type_pair("int64", "FLOAT")
    assert not suspicious_type_pair("string", "STRING")
    assert suspicious_type_pair("int64", "STRING")
    assert suspicious_type_pair("boolean", "INTEGER")

    bq_cols = [{"name": "clicks", "type": "STRING"}, {"name": "flag", "type": "BOOLEAN"}]
    drift, _ = classify_drift(
        ["clicks", "flag"], bq_cols, "T",
        declared_types={"clicks": "int64", "flag": "string"},
        m_type_changed={"clicks"})
    assert "missing_in_bq" not in drift
    tm = drift["type_mismatch"]
    assert any(e.startswith("clicks:") and "M Changed Type confirmed" in e for e in tm)
    assert any(e.startswith("flag:") and "no M Changed Type found" in e for e in tm)

    t = parse_table(_table_file(tmp_path, (
        "table Queries\n\n"
        "\tcolumn 'Property Position Rounded'\n"
        "\t\tdataType: int64\n"
        "\t\tsourceColumn: Property Position Rounded\n\n"
        "\tpartition Queries = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("queries_n", "date"),\n'
        '\t\t\t    dup = Table.DuplicateColumn(Source, "property_position", "property_position_rounded"),\n'
        '\t\t\t    ct = Table.TransformColumnTypes(dup,{{"property_position_rounded", Int64.Type}, {"date", type date}})\n'
        "\t\t\tin\n"
        "\t\t\t    ct\n"
    )))
    assert t["m_type_changes"] == {"property_position_rounded": "Int64.Type",
                                   "date": "type date"}


def test_load_trash_columns_reads_the_owner_file():
    """The ignore-columns file is the single source of truth; this pin keeps a
    refactor from silently degrading suppression to empty sets."""
    trash, exceptions = load_ignore_columns(IGNORE_COLUMNS)
    assert trash == {"account_id", "report_name", "source_string",
                     "table_x_id", "updated_at_db", "partition_date"}
    assert ("Sitemap", "updated_at_db") in exceptions
