from scripts import generate_db_schema


def test_schema_name_pattern_collects_official_schema_constants() -> None:
    assert generate_db_schema._SCHEMA_NAME_RE.match("ORDER_REGISTRY_SCHEMA")
    assert generate_db_schema._SCHEMA_NAME_RE.match("TREASURY_SCHEMA")
    assert generate_db_schema._SCHEMA_NAME_RE.match("_CREATE_TABLE_SQL")


def test_schema_name_pattern_does_not_collect_ddl_suffix() -> None:
    assert generate_db_schema._SCHEMA_NAME_RE.match("ORDER_REGISTRY_DDL") is None
    assert generate_db_schema._SCHEMA_NAME_RE.match("_DDL") is None
