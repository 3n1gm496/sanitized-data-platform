from sanitized_data_platform.adapters.postgres.metadata_discovery import (
    PostgreSQLMetadataDiscoveryAdapter,
)
from sanitized_data_platform.domain.enums import MetadataObjectType

from tests.fakes import sample_source


class FakeCursor:
    def __init__(self, rows_by_query: dict[str, list[tuple[object, ...]]], executed_queries: list[str]) -> None:
        self._rows_by_query = rows_by_query
        self._executed_queries = executed_queries
        self._current_rows: list[tuple[object, ...]] = []

    def execute(self, query: str, params=None) -> None:
        self._executed_queries.append(query)
        if "information_schema.schemata" in query:
            self._current_rows = self._rows_by_query["schemas"]
        elif "information_schema.tables" in query:
            self._current_rows = self._rows_by_query["tables"]
        elif "information_schema.columns" in query:
            self._current_rows = self._rows_by_query["columns"]
        elif "constraint_type = 'PRIMARY KEY'" in query:
            self._current_rows = self._rows_by_query["primary_keys"]
        elif "constraint_type = 'FOREIGN KEY'" in query:
            self._current_rows = self._rows_by_query["foreign_keys"]
        else:
            self._current_rows = []

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._current_rows)

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(self, rows_by_query: dict[str, list[tuple[object, ...]]], executed_queries: list[str]) -> None:
        self._rows_by_query = rows_by_query
        self._executed_queries = executed_queries

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._rows_by_query, self._executed_queries)

    def close(self) -> None:
        return None


def test_postgres_adapter_lists_canonical_schema_table_and_column_objects():
    executed_queries: list[str] = []
    rows_by_query = {
        "schemas": [("public",)],
        "tables": [("public", "customers")],
        "columns": [
            ("public", "customers", "customer_id", "integer", "int4", 1),
            ("public", "customers", "email", "character varying", "varchar", 2),
            ("public", "customers", "payload", "jsonb", "jsonb", 3),
        ],
        "primary_keys": [],
        "foreign_keys": [],
    }
    adapter = PostgreSQLMetadataDiscoveryAdapter(
        lambda _dsn: FakeConnection(rows_by_query, executed_queries)
    )
    source = sample_source()

    schemas = adapter.list_schemas(source)
    tables = adapter.list_tables(source)
    columns = adapter.list_columns(source)

    assert len(executed_queries) == 3
    assert schemas[0].object_type == MetadataObjectType.SCHEMA
    assert schemas[0].qualified_name == "public"
    assert tables[0].object_type == MetadataObjectType.TABLE
    assert tables[0].parent_object_id == "schema:source-crm-replica:public"
    assert columns[0].object_type == MetadataObjectType.COLUMN
    assert columns[0].parent_object_id == "table:source-crm-replica:public.customers"
    assert [column.logical_data_type for column in columns] == ["integer", "string", "json"]


def test_postgres_type_mapping_uses_canonical_logical_types():
    assert (
        PostgreSQLMetadataDiscoveryAdapter.map_postgres_type_to_logical(
            data_type="text",
            udt_name="text",
        )
        == "large_text"
    )
    assert (
        PostgreSQLMetadataDiscoveryAdapter.map_postgres_type_to_logical(
            data_type="timestamp with time zone",
            udt_name="timestamptz",
        )
        == "timestamp"
    )
    assert (
        PostgreSQLMetadataDiscoveryAdapter.map_postgres_type_to_logical(
            data_type="bytea",
            udt_name="bytea",
        )
        == "binary"
    )
    assert (
        PostgreSQLMetadataDiscoveryAdapter.map_postgres_type_to_logical(
            data_type="USER-DEFINED",
            udt_name="citext",
        )
        == "string"
    )


def test_postgres_adapter_discovers_primary_and_foreign_key_relationships():
    executed_queries: list[str] = []
    rows_by_query = {
        "schemas": [],
        "tables": [],
        "columns": [],
        "primary_keys": [
            ("public", "customers", "customer_id", 1),
        ],
        "foreign_keys": [
            ("public", "orders", "customer_id", "public", "customers", "customer_id"),
        ],
    }
    adapter = PostgreSQLMetadataDiscoveryAdapter(
        lambda _dsn: FakeConnection(rows_by_query, executed_queries)
    )

    relationships = adapter.list_relationships(sample_source())

    assert len(relationships) == 2
    assert relationships[0].relationship_type == "primary_key"
    assert relationships[0].source_object_id == "table:source-crm-replica:public.customers"
    assert relationships[0].target_object_id == "column:source-crm-replica:public.customers.customer_id"
    assert relationships[1].relationship_type == "foreign_key"
    assert relationships[1].source_object_id == "column:source-crm-replica:public.orders.customer_id"
    assert relationships[1].target_object_id == "column:source-crm-replica:public.customers.customer_id"
