import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_db_schema.py"
_SPEC = importlib.util.spec_from_file_location("generate_db_schema", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None

generate_db_schema = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generate_db_schema)


def test_schema_name_pattern_collects_official_schema_constants() -> None:
    assert generate_db_schema._SCHEMA_NAME_RE.match("ORDER_REGISTRY_SCHEMA")
    assert generate_db_schema._SCHEMA_NAME_RE.match("TREASURY_SCHEMA")
    assert generate_db_schema._SCHEMA_NAME_RE.match("_CREATE_TABLE_SQL")


def test_schema_name_pattern_does_not_collect_ddl_suffix() -> None:
    assert generate_db_schema._SCHEMA_NAME_RE.match("ORDER_REGISTRY_DDL") is None
    assert generate_db_schema._SCHEMA_NAME_RE.match("_DDL") is None
