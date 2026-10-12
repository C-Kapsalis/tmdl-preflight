"""Parser coherence: the clean fixture parses into the expected shape."""

from __future__ import annotations

from tmdl_preflight.parser import parse_endpoint, parse_model, parse_object_name


def test_tables_discovered(definition):
    model = parse_model(definition)
    assert set(model.tables) == {
        "Sales",
        "Products",
        "Stores",
        "Calendar",
        "Sales Measures",
        "Metric Selector",
    }
    assert not model.parse_errors


def test_columns_and_properties(definition):
    model = parse_model(definition)
    sales = model.tables["Sales"]
    assert sales.is_hidden
    assert sales.columns["net_amount"].data_type == "double"
    assert sales.columns["order_date"].format_string == "General Date"
    assert sales.columns["order_id"].source_column == "order_id"
    products = model.tables["Products"]
    assert products.columns["product_id"].is_key


def test_measures_parsed(definition):
    model = parse_model(definition)
    measures = model.tables["Sales Measures"].measures
    assert measures["Revenue"].expression == "SUM(Sales[net_amount])"
    assert measures["Revenue"].format_string == "$ #,0.00"
    assert "Orders #" in measures
    # fenced multi-line measure keeps its body
    assert "DIVIDE([Revenue], store_count)" in measures["Revenue per Store"].expression
    # hidden diagnostic measure on the fact table
    assert model.tables["Sales"].measures["countrows sales"].is_hidden


def test_calculated_partitions(definition):
    model = parse_model(definition)
    calendar = model.tables["Calendar"].partitions[0]
    assert calendar.kind == "calculated"
    assert "CALENDAR(DATE(2024, 1, 1)" in calendar.source
    selector = model.tables["Metric Selector"].partitions[0]
    assert selector.kind == "calculated"
    assert "NAMEOF ( [Revenue] )" in selector.source
    assert selector.source_start_line is not None
    assert selector.source_end_line >= selector.source_start_line


def test_field_parameter_detected(definition):
    model = parse_model(definition)
    assert model.tables["Metric Selector"].is_field_parameter
    assert not model.tables["Sales"].is_field_parameter


def test_relationships_parsed(definition):
    model = parse_model(definition)
    assert len(model.relationships) == 4
    first = model.relationships[0]
    assert (first.from_table, first.from_column) == ("Sales", "product_id")
    assert (first.to_table, first.to_column) == ("Products", "product_id")
    inactive = [r for r in model.relationships if not r.is_active]
    assert len(inactive) == 1
    assert inactive[0].from_column == "ship_date"


def test_lineage_tags_collected(definition):
    model = parse_model(definition)
    assert len(model.lineage_tags) >= 20
    tags = [occ.tag for occ in model.lineage_tags]
    assert len(tags) == len(set(tags))  # fixture is duplicate-free
    contexts = {occ.context for occ in model.lineage_tags}
    assert any(c.startswith("table") for c in contexts)
    assert any(c.startswith("column") for c in contexts)


def test_parse_object_name_forms():
    assert parse_object_name("Revenue = SUM(1)") == ("Revenue", "= SUM(1)")
    assert parse_object_name("'Orders #' = COUNTROWS(x)") == ("Orders #", "= COUNTROWS(x)")
    assert parse_object_name("'It''s Fine'") == ("It's Fine", "")
    assert parse_object_name('"Quoted Name" = 1') == ("Quoted Name", "= 1")


def test_parse_endpoint_forms():
    assert parse_endpoint("Sales.product_id") == ("Sales", "product_id")
    assert parse_endpoint("'Sales Measures'.Revenue") == ("Sales Measures", "Revenue")
    assert parse_endpoint("'A'.'b name'") == ("A", "b name")
    assert parse_endpoint("'It''s'.col") == ("It's", "col")


# ---------------------------------------------------------------------------
# 1.1.0 parser robustness
# ---------------------------------------------------------------------------

from tmdl_preflight.parser import parse_table_file  # noqa: E402
from tmdl_preflight.rules.base import Context  # noqa: E402
from tmdl_preflight.rules.structural import TmdlWellFormedRule  # noqa: E402


def test_byte_order_mark_is_tolerated(definition):
    f = definition / "tables" / "Stores.tmdl"
    f.write_bytes(b"\xef\xbb\xbf" + f.read_bytes())
    model = parse_model(definition)
    assert "Stores" in model.tables
    assert not model.parse_errors


def test_byte_order_mark_relationships(definition):
    f = definition / "relationships.tmdl"
    f.write_bytes(b"\xef\xbb\xbf" + f.read_bytes())
    assert len(parse_model(definition).relationships) == 4


def test_unreadable_relationships_file_is_a_parse_error(project, definition):
    (definition / "relationships.tmdl").write_bytes(b"relationship x\n\tfromColumn: \xff\xfe\n")
    model = parse_model(definition)
    assert model.relationships == []
    assert any("relationships.tmdl" in str(e.file) for e in model.parse_errors)
    assert any(
        v.file.name == "relationships.tmdl" for v in TmdlWellFormedRule().check(Context(project))
    )


def test_duplicate_declarations_are_kept(definition, replace_in):
    f = definition / "tables" / "Sales Measures.tmdl"
    replace_in(
        f,
        "\tmeasure Revenue = SUM(Sales[net_amount])\n",
        "\tmeasure Revenue = SUM(Sales[net_amount])\n"
        "\t\tlineageTag: 0d0d0d0d-0000-4000-8000-000000000001\n\n"
        "\tmeasure revenue = 1\n",
    )
    table = parse_model(definition).tables["Sales Measures"]
    assert [m.name for m in table.measure_list].count("Revenue") == 1
    assert {m.name for m in table.measure_list} >= {"Revenue", "revenue"}
    # first declaration wins in the dict
    assert table.measures["Revenue"].expression == "SUM(Sales[net_amount])"
    assert table.find_measure("REVENUE") is table.measures["Revenue"]


def test_case_insensitive_table_index(definition):
    model = parse_model(definition)
    assert model.find_table("sales measures") is model.tables["Sales Measures"]
    assert model.get_table("sales measures") is None  # exact lookup stays exact


def test_malformed_relationship_is_kept(definition, replace_in):
    replace_in(
        definition / "relationships.tmdl",
        "\tfromColumn: Sales.store_id\n",
        "",
    )
    model = parse_model(definition)
    assert len(model.relationships) == 3
    assert len(model.malformed_relationships) == 1
    assert model.malformed_relationships[0].to_table == "Stores"


def test_parser_reports_dropped_measures(definition, replace_in):
    # a measure indented one level too deep is swallowed by nothing and
    # attached to nothing; the raw-count sanity check must notice
    replace_in(
        definition / "tables" / "Sales Measures.tmdl",
        "\tmeasure 'Units Sold' = SUM(Sales[quantity])",
        "\t\tmeasure 'Units Sold' = SUM(Sales[quantity])",
    )
    model = parse_model(definition)
    assert any("parser dropped 1 object" in e.message for e in model.parse_errors)


def test_parser_reports_dropped_relationships(definition, replace_in):
    replace_in(
        definition / "relationships.tmdl",
        "relationship 2a7c3d4b-9d2e-4f60-8b81-2c3d4e5f6071",
        "\trelationship 2a7c3d4b-9d2e-4f60-8b81-2c3d4e5f6071",
    )
    model = parse_model(definition)
    assert any("parser dropped 1 object" in e.message for e in model.parse_errors)


def test_clean_fixture_has_no_dropped_objects(definition):
    assert parse_model(definition).parse_errors == []


def test_descriptions_and_display_folders(definition, replace_in):
    replace_in(
        definition / "tables" / "Sales Measures.tmdl",
        "\t\tformatString: #,0\n\t\tlineageTag: b3662637",
        "\t\tformatString: #,0\n\t\tdisplayFolder: Counts\n\t\tlineageTag: b3662637",
    )
    model = parse_model(definition)
    table = model.tables["Sales Measures"]
    assert table.description == "Measure home table: all user-facing measures live here."
    assert table.measures["Revenue"].description.startswith("Net sales amount")
    assert table.measures["Orders #"].display_folder == "Counts"
    assert model.tables["Sales"].description.startswith("One row per order line")
    assert "\n" in model.tables["Sales"].description  # multi-line run kept


def test_measure_level_format_string_definition(definition, replace_in):
    replace_in(
        definition / "tables" / "Sales Measures.tmdl",
        "\t\tformatString: #,0\n\t\tlineageTag: d5884859",
        '\t\tlineageTag: d5884859',
    )
    f = definition / "tables" / "Sales Measures.tmdl"
    replace_in(
        f,
        "\t\tlineageTag: d5884859-48d9-4a1b-a03c-374859607182\n",
        "\t\tlineageTag: d5884859-48d9-4a1b-a03c-374859607182\n\n"
        '\t\tformatStringDefinition = IF([Units Sold] > 1000, "#,0,K", "#,0")\n',
    )
    table = parse_model(definition).tables["Sales Measures"]
    assert table.measures["Units Sold"].format_string_definition.startswith("IF(")
    assert table.format_string_definitions[-1][0] == "Units Sold"
    assert table.dynamic_format_items == []


def test_expressions_file(definition):
    (definition / "expressions.tmdl").write_text(
        'expression RangeStart = #datetime(2024, 1, 1, 0, 0, 0) meta '
        '[IsParameterQuery = true, Type = "DateTime", IsParameterQueryRequired = true]\n'
        "\tlineageTag: 11111111-2222-4333-8444-555555555555\n\n"
        "expression 'Shared Source' =\n"
        "\t\tlet\n"
        '\t\t    Source = Csv.Document(File.Contents("x.csv"))\n'
        "\t\tin\n"
        "\t\t    Source\n"
        "\tlineageTag: 11111111-2222-4333-8444-555555555556\n",
        encoding="utf-8",
    )
    exprs = parse_model(definition).expressions
    assert [e.name for e in exprs] == ["RangeStart", "Shared Source"]
    assert exprs[0].is_parameter and exprs[0].meta["Type"] == "DateTime"
    assert exprs[0].lineage_tag.endswith("555")
    assert not exprs[1].is_parameter and "Csv.Document" in exprs[1].expression


def test_refresh_policy_placement(definition, replace_in):
    replace_in(
        definition / "tables" / "Sales.tmdl",
        "\tpartition Sales = m\n",
        "\trefreshPolicy\n"
        "\t\tpolicyType: basic\n"
        "\t\trollingWindowGranularity: year\n"
        "\t\trollingWindowPeriods: 3\n\n"
        "\tpartition Sales = m\n",
    )
    policy = parse_model(definition).tables["Sales"].refresh_policy
    assert policy is not None and policy.level == 1
    assert policy.properties["policyType"] == "basic"
    assert policy.properties["rollingWindowPeriods"] == "3"


def test_model_info(definition):
    info = parse_model(definition).info
    assert info.name == "Model"
    assert ("Sales Measures", 15) in info.ref_tables
    assert not info.discourage_implicit_measures


def test_expression_start_lines(definition):
    table = parse_model(definition).tables["Sales Measures"]
    inline = table.measures["Revenue"]
    assert inline.expression_line == inline.line
    fenced = table.measures["Revenue per Store"]
    assert fenced.expression_line == fenced.line + 1


def test_parse_table_file_keeps_properties_on_their_owner(tmp_path):
    f = tmp_path / "T.tmdl"
    f.write_text(
        "table T\n"
        "\tlineageTag: 11111111-2222-4333-8444-555555555555\n\n"
        "\tcolumn a\n"
        "\t\tdataType: string\n"
        "\t\tsourceColumn: a\n\n"
        "\tisHidden\n",
        encoding="utf-8",
    )
    table, errors = parse_table_file(f)
    assert not errors
    assert table.is_hidden
    assert not table.columns["a"].is_hidden
