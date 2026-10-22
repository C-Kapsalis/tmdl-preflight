"""The three partition forms the manifest reads, and how strictly it reads
them.

A partition that talks to the warehouse must be recognised as such even
when the source cannot be recovered: a table that is silently dropped
from the manifest is a table the schema check never sees.
"""
from __future__ import annotations

from tmdl_preflight.manifest import parse_inline_window, parse_table


def _table(tmp_path, body, name="Fixture.tmdl"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_the_inline_window_needs_its_marker(tmp_path):
    """A windowed query without the marker is not the inline form: it falls
    through to unresolved rather than being read as one."""
    with_marker = (
        'let ir_dfilter = " cast(date as date) >= parse_date(\'%m/%d/%Y\', \'" & '
        'Date.ToText(DateTime.Date(RangeStart), "MM/dd/yyyy") & "\') ", ir_qstr = "SELECT * '
        'FROM `" & #"v-BQ_project" & "." & #"v-db" & "." & "ads_n" & "` where " & ir_dfilter'
    )
    assert parse_inline_window(with_marker) == ("ads_n", "date")
    without_marker = with_marker.replace("ir_dfilter", "window_filter")
    assert parse_inline_window(without_marker) is None


def test_a_windowed_query_without_the_marker_is_unresolved(tmp_path):
    table = parse_table(_table(tmp_path, (
        "table Ads\n\n"
        "\tpartition Ads = m\n"
        "\t\tmode: import\n"
        "\t\tsource = let window_filter = \" cast(date as date) >= parse_date('%m/%d/%Y', '\" & "
        "Date.ToText(DateTime.Date(RangeStart), \"MM/dd/yyyy\") & \"') \", ir_qstr = \"SELECT * "
        "FROM `\" & #\"v-BQ_project\" & \".\" & #\"v-db\" & \".\" & \"ads_n\" & \"` where \" & "
        "window_filter, ir_src = Value.NativeQuery(GoogleBigQuery.Database()"
        "{[Name= #\"v-BQ_project\" ]}[Data], ir_qstr, null) in ir_src\n"
    )))
    assert table.get("unresolved_source") is True
    assert "bq_source" not in table


def test_a_connector_named_in_a_string_still_speaks_the_warehouse(tmp_path):
    """The mention is read on the raw text: a dead variant inside a string
    literal is still a warehouse-reading partition, so it is reported as
    unresolved instead of being dropped."""
    table = parse_table(_table(tmp_path, (
        "table Spend\n\n"
        "\tpartition Spend = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let dead = "GoogleBigQuery.Database() lives here" in dead\n'
    )))
    assert table.get("unresolved_source") is True
    assert "bq_source" not in table


def test_a_transformer_named_in_a_string_marks_the_table(tmp_path):
    """A programmatic rename is read on the raw text too: a table whose
    partition names a renaming helper is one whose column names cannot be
    read statically."""
    table = parse_table(_table(tmp_path, (
        "table Ads\n\n"
        "\tpartition Ads = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let A = source_filter_dates("ads_n", "date"), '
        'B = "PrefixColumns is mentioned here" in A\n'
    )))
    assert table.get("programmatic_renames") is True


def test_the_earliest_loader_call_wins(tmp_path):
    """Among every loader name the model uses, the earliest call in the text
    is the source."""
    table = parse_table(_table(tmp_path, (
        "table Orders\n\n"
        "\tpartition Orders = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    A = source_filter_dates("first_n", "date"),\n'
        '\t\t\t    B = _source_filter_dates_tickets_rowsLimit("second_n", "date")\n'
        "\t\t\tin\n"
        "\t\t\t    A\n"
    )), readers={"_source_filter_dates_tickets_rowsLimit"})
    assert table["bq_source"]["table"] == "first_n"


def test_a_loader_call_is_matched_without_a_left_boundary(tmp_path):
    table = parse_table(_table(tmp_path, (
        "table Orders\n\n"
        "\tpartition Orders = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let A = my_source_filter_dates("wrapped_n", "date") in A\n'
    )))
    assert table["bq_source"]["table"] == "wrapped_n"


def test_a_pair_list_may_carry_spaces(tmp_path):
    table = parse_table(_table(tmp_path, (
        "table Ads\n\n"
        "\tcolumn 'Ad Strength'\n"
        "\t\tdataType: string\n"
        "\t\tsourceColumn: Ad Strength\n\n"
        "\tpartition Ads = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t    Source = source_filter_dates("ads_n", "date"),\n'
        '\t\t\t    ren = Table.RenameColumns(Source, { "ad_strength", "Ad Strength" })\n'
        "\t\t\tin\n"
        "\t\t\t    ren\n"
    )))
    cols = {c["name"]: c for c in table["columns"]}
    assert cols["Ad Strength"]["bqColumn"] == "ad_strength"


def test_a_column_property_is_read_from_a_deeper_line(tmp_path):
    table = parse_table(_table(tmp_path, (
        "table Orders\n\n"
        "\tcolumn amount\n"
        "\t\tformatStringDefinition\n"
        "\t\t\tdataType: double\n"
        "\t\tsourceColumn: amount\n\n"
        "\tpartition Orders = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let A = source_filter_dates("orders_n", "date") in A\n'
    )))
    cols = {c["name"]: c for c in table["columns"]}
    assert cols["amount"]["dataType"] == "double"


def test_a_file_with_a_byte_order_mark_is_read(tmp_path):
    path = tmp_path / "Orders.tmdl"
    path.write_bytes(b"\xef\xbb\xbf" + (
        "table Orders\n\n"
        "\tcolumn amount\n"
        "\t\tdataType: double\n"
        "\t\tsourceColumn: amount\n\n"
        "\tpartition Orders = m\n"
        "\t\tmode: import\n"
        '\t\tsource = let A = source_filter_dates("orders_n", "date") in A\n'
    ).encode("utf-8"))
    table = parse_table(path)
    assert table["name"] == "Orders"
    assert table["bq_source"]["table"] == "orders_n"
