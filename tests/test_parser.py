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
