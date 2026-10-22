"""The schema check against SQL view definitions.

The question is the same as in the snapshot mode — does the view serve
every column the model needs — but the proof comes from the SQL project on
disk: an explicit select list, a star select over the universal source, or
a star select over a model whose own list proves the columns.
"""
from __future__ import annotations

import json

from conftest import run_cli

SQL = "sql_views"
ENTRIES = {
    "schema_version": 1,
    "entries": [
        {"client": "spinout-05", "table": "Orders", "client_view": "orders_v",
         "universal_view": "visits_base_n",
         "columns": [{"sourceColumn": "amount"}, {"sourceColumn": "region"}]},
        {"client": "spinout-05", "table": "Visits", "client_view": "visits_v",
         "universal_view": "visits_base_n",
         "columns": [{"sourceColumn": "visits"}]},
        {"client": "spinout-05", "table": "Refunds", "client_view": "refunds_v",
         "universal_view": "visits_base_n",
         "columns": [{"sourceColumn": "amt"}]},
        {"client": "spinout-05", "table": "Deep", "client_view": "deep_v",
         "universal_view": "visits_base_n",
         "columns": [{"sourceColumn": "visits"}]},
        {"client": "spinout-05", "table": "Gone", "client_view": "gone_v",
         "universal_view": "visits_base_n",
         "columns": [{"sourceColumn": "visits"}]},
    ],
}


def _entries_file(tmp_path, entries=None):
    path = tmp_path / "entries.json"
    path.write_text(json.dumps(entries if entries is not None else ENTRIES, indent=2),
                    encoding="utf-8")
    return path


def _run(stand_in, tmp_path, *extra, entries=None):
    root = stand_in(SQL)
    path = _entries_file(tmp_path, entries)
    argv = ["schema-check", "--sql-dir", root, "--entries", path]
    argv += list(extra)
    code, out, err = run_cli(*argv)
    return code, out, err, root


def test_the_entries_file_is_read_in_the_registry_shape(stand_in, tmp_path):
    code, out, err, _root = _run(stand_in, tmp_path)
    assert code == 3
    assert "✓ READY spinout-05 · Orders · orders_v" in out
    assert "05/orders_v.sql: every required column exposed explicitly (2 col(s))" in out


def test_the_console_names_the_state_and_every_entry(stand_in, tmp_path):
    code, out, err, root = _run(stand_in, tmp_path)
    assert code == 3
    lines = out.splitlines()
    assert lines[0].startswith(f"SQL state: {root} @ ")
    assert lines[0].endswith("unknown") or len(lines[0].split(" @ ")[1]) == 7
    assert lines[1] == "✓ READY spinout-05 · Orders · orders_v"
    assert lines[2] == "         05/orders_v.sql: every required column exposed explicitly (2 col(s))"
    assert lines[3] == "✓ READY spinout-05 · Visits · visits_v"
    assert lines[4] == ("         05/visits_v.sql: SELECT * passes through the ETL-materialized "
                        "universal source 'visits_base_n' — columns flow with the underlay "
                        "materialization")
    assert lines[5] == "✗ HELD  spinout-05 · Refunds · refunds_v"
    assert lines[6] == ("         05/refunds_v.sql: explicit select list lacks 1 required "
                        "column(s): amt")
    assert lines[9] == "✗ HELD  spinout-05 · Gone · gone_v"
    assert lines[10] == ("         view not in DBT (repo-stale / hand-made) — import via "
                         "/enrich-view")
    assert lines[11] == ""
    assert lines[12] == "READY to /deploy: —"
    assert lines[13] == "HELD (view enrichment pending): ['spinout-05']"


def test_a_client_is_ready_only_when_every_entry_is(stand_in, tmp_path):
    entries = {"schema_version": 1, "entries": [
        {"client": "spinout-05", "table": "Orders", "client_view": "orders_v",
         "columns": [{"sourceColumn": "amount"}]},
        {"client": "spinout-06", "table": "Refunds", "client_view": "refunds_v",
         "columns": [{"sourceColumn": "amt"}]},
    ]}
    code, out, _err, _root = _run(stand_in, tmp_path, entries=entries)
    assert code == 3
    assert "READY to /deploy: ['spinout-05']" in out
    assert "HELD (view enrichment pending): ['spinout-06']" in out


def test_every_reason_names_the_file_and_the_finding(stand_in, tmp_path):
    entries = {"schema_version": 1, "entries": [
        {"client": "spinout-05", "table": "Visits", "client_view": "visits_v",
         "universal_view": "visits_base_n", "columns": [{"sourceColumn": "visits"}]},
        {"client": "spinout-05", "table": "Hop", "client_view": "hop_v",
         "universal_view": "visits_base_n", "columns": [{"sourceColumn": "visits"}]},
        {"client": "spinout-05", "table": "Deep", "client_view": "deep_v",
         "universal_view": "visits_base_n", "columns": [{"sourceColumn": "visits"}]},
        {"client": "spinout-05", "table": "Other", "client_view": "other_v",
         "universal_view": "visits_base_n", "columns": [{"sourceColumn": "visits"}]},
    ]}
    _code, out, _err, _root = _run(stand_in, tmp_path, entries=entries)
    assert ("05/visits_v.sql: SELECT * passes through the ETL-materialized universal source "
            "'visits_base_n' — columns flow with the underlay materialization") in out
    assert ("05/hop_v.sql: SELECT * over ref('visits_base') — one-hop trace exposes all required "
            "columns") in out
    assert ("05/deep_v.sql: SELECT * over ref('star_v') which is itself SELECT * — beyond the "
            "one-hop static trace; verify manually") in out
    assert ("05/other_v.sql: SELECT * but not over the universal source 'visits_base_n' "
            "(source:other_n) — missing column(s) not statically provable: visits") in out


def test_a_star_select_is_a_star_select(stand_in, tmp_path):
    """``select distinct *`` is not a star select, and a relation outside the
    jinja braces does not count."""
    root = stand_in(SQL)
    (root / "05" / "distinct_v.sql").write_text("select distinct * from raw\n", encoding="utf-8")
    (root / "05" / "loose_v.sql").write_text("select * from raw -- {{ ref('visits_base') }}\n",
                                              encoding="utf-8")
    entries = {"schema_version": 1, "entries": [
        {"client": "spinout-05", "table": "Distinct", "client_view": "distinct_v",
         "universal_view": "visits_base_n", "columns": [{"sourceColumn": "visits"}]},
        {"client": "spinout-05", "table": "Loose", "client_view": "loose_v",
         "universal_view": "visits_base_n", "columns": [{"sourceColumn": "visits"}]},
    ]}
    path = _entries_file(tmp_path, entries)
    _code, out, _err = run_cli("schema-check", "--sql-dir", root, "--entries", path)
    assert "05/distinct_v.sql: explicit select list lacks 1 required column(s): visits" in out
    assert ("05/loose_v.sql: SELECT * but not over the universal source 'visits_base_n' "
            "(no relation found) — missing column(s) not statically provable: visits") in out


def test_an_owner_the_pattern_does_not_match_is_held(stand_in, tmp_path):
    entries = {"schema_version": 1, "entries": [
        {"client": "spinout-05", "table": "Orders", "client_view": "orders_v",
         "columns": [{"sourceColumn": "amount"}]},
        {"client": "other", "table": "Orders", "client_view": "orders_v",
         "columns": [{"sourceColumn": "amount"}]},
    ]}
    code, out, _err, _root = _run(stand_in, tmp_path, "--owner-folder-pattern", r"spinout-(\d+)",
                                  entries=entries)
    assert code == 3
    assert "✓ READY spinout-05 · Orders · orders_v" in out
    assert "✗ HELD  other · Orders · orders_v" in out
    assert "         cannot derive org id from 'other'" in out


def test_the_holdbacks_file_holds_every_entry_of_the_registry(stand_in, tmp_path):
    root = stand_in(SQL)
    path = _entries_file(tmp_path)
    hb = tmp_path / "deploy_holdbacks.yml"
    code, out, err = run_cli("schema-check", "--sql-dir", root, "--entries", path,
                             "--holdbacks", hb, "--write-holdbacks")
    assert code == 3, err
    text = hb.read_text(encoding="utf-8")
    assert text.startswith(
        "## deploy_holdbacks.yml — clients whose deploy is HELD pending view enrichment.\n"
        "## AUTO-GENERATED by `tmdl-preflight schema-check --sql-dir ... --write-holdbacks`\n"
        "## from the outstanding-enrichment entries file — do not\n"
        "## hand-edit. Entries clear when the SQL-state check turns READY and\n"
        "## `--clear-ready` removes them from the entries file.\n"
        "version: 1\n"
        "holdbacks:\n"
        "- client: spinout-05\n"
        "  since: '")
    assert "  blocking:\n" in text
    assert "  - table: Orders\n    view: orders_v\n    columns:\n    - amount\n    - region\n" in text
    # a READY entry is still outstanding work
    assert "  - table: Visits\n    view: visits_v\n" in text
    assert f"  holdbacks written: {hb} (1 client(s)) — commit it with the registry" in out


def test_a_preserved_date_is_written_as_it_was(stand_in, tmp_path):
    root = stand_in(SQL)
    path = _entries_file(tmp_path)
    hb = tmp_path / "deploy_holdbacks.yml"
    hb.write_text("version: 1\nholdbacks:\n- client: spinout-05\n  since: 2026-01-02\n"
                  "  blocking: []\n", encoding="utf-8")
    run_cli("schema-check", "--sql-dir", root, "--entries", path, "--holdbacks", hb,
            "--write-holdbacks")
    assert "  since: 2026-01-02\n" in hb.read_text(encoding="utf-8")


def test_an_empty_registry_holds_nothing(stand_in, tmp_path):
    root = stand_in(SQL)
    path = tmp_path / "entries.json"
    hb = tmp_path / "deploy_holdbacks.yml"
    code, out, err = run_cli("schema-check", "--sql-dir", root, "--entries", path,
                             "--holdbacks", hb, "--write-holdbacks")
    assert code == 0, err
    assert out.splitlines()[0] == "outstanding-enrichment registry is empty — nothing to hold."
    assert "holdbacks: []" in hb.read_text(encoding="utf-8")


def test_ready_entries_are_removed_from_the_registry(stand_in, tmp_path):
    root = stand_in(SQL)
    entries = {"schema_version": 1, "entries": [
        {"client": "spinout-05", "table": "Orders", "client_view": "orders_v",
         "columns": [{"sourceColumn": "amount"}]},
        {"client": "spinout-06", "table": "Refunds", "client_view": "refunds_v",
         "columns": [{"sourceColumn": "amt"}]},
    ]}
    path = _entries_file(tmp_path, entries)
    code, out, err = run_cli("schema-check", "--sql-dir", root, "--entries", path, "--clear-ready")
    assert code == 3, err
    assert "--clear-ready: removed 1 READY entr(ies) from " in out
    assert "⚠ REMEMBER TO COMMIT the updated registry (it is a committed receipt)." in out
    left = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert [e["client"] for e in left] == ["spinout-06"]
