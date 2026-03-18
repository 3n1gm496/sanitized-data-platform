from sanitized_data_platform.adapters.oracle.metadata_discovery import (
    OracleMetadataDiscoveryAdapter,
)
from sanitized_data_platform.domain.enums import MetadataObjectType

from tests.oracle_helpers import OracleDiscoveryConnection, sample_oracle_source


def test_oracle_adapter_lists_canonical_schema_table_and_column_objects():
    executed_queries: list[str] = []
    rows_by_query = {
        "schemas": [("CRM",)],
        "tables": [("CRM", "CUSTOMERS")],
        "columns": [
            ("CRM", "CUSTOMERS", "CUSTOMER_ID", "NUMBER", 38, 0, 1),
            ("CRM", "CUSTOMERS", "EMAIL", "VARCHAR2", None, None, 2),
            ("CRM", "CUSTOMERS", "PAYLOAD", "JSON", None, None, 3),
        ],
        "primary_keys": [],
        "foreign_keys": [],
    }
    adapter = OracleMetadataDiscoveryAdapter(
        lambda _dsn: OracleDiscoveryConnection(rows_by_query, executed_queries)
    )
    source = sample_oracle_source()

    schemas = adapter.list_schemas(source)
    tables = adapter.list_tables(source)
    columns = adapter.list_columns(source)

    assert len(executed_queries) == 3
    assert schemas[0].object_type == MetadataObjectType.SCHEMA
    assert schemas[0].qualified_name == "CRM"
    assert tables[0].object_type == MetadataObjectType.TABLE
    assert tables[0].parent_object_id == "schema:source-crm-oracle:CRM"
    assert columns[0].object_type == MetadataObjectType.COLUMN
    assert columns[0].parent_object_id == "table:source-crm-oracle:CRM.CUSTOMERS"
    assert [column.logical_data_type for column in columns] == [
        "integer",
        "string",
        "json",
    ]


def test_oracle_type_mapping_uses_canonical_logical_types():
    assert (
        OracleMetadataDiscoveryAdapter.map_oracle_type_to_logical(
            data_type="CLOB"
        )
        == "large_text"
    )
    assert (
        OracleMetadataDiscoveryAdapter.map_oracle_type_to_logical(
            data_type="TIMESTAMP WITH TIME ZONE"
        )
        == "timestamp"
    )
    assert (
        OracleMetadataDiscoveryAdapter.map_oracle_type_to_logical(
            data_type="RAW"
        )
        == "binary"
    )
    assert (
        OracleMetadataDiscoveryAdapter.map_oracle_type_to_logical(
            data_type="NUMBER",
            data_precision=10,
            data_scale=2,
        )
        == "decimal"
    )


def test_oracle_adapter_discovers_primary_and_foreign_key_relationships():
    executed_queries: list[str] = []
    rows_by_query = {
        "schemas": [],
        "tables": [],
        "columns": [],
        "primary_keys": [("CRM", "CUSTOMERS", "CUSTOMER_ID", 1)],
        "foreign_keys": [
            ("CRM", "ORDERS", "CUSTOMER_ID", "CRM", "CUSTOMERS", "CUSTOMER_ID")
        ],
    }
    adapter = OracleMetadataDiscoveryAdapter(
        lambda _dsn: OracleDiscoveryConnection(rows_by_query, executed_queries)
    )

    relationships = adapter.list_relationships(sample_oracle_source())

    assert len(relationships) == 2
    assert relationships[0].relationship_type == "primary_key"
    assert relationships[0].source_object_id == "table:source-crm-oracle:CRM.CUSTOMERS"
    assert relationships[0].target_object_id == "column:source-crm-oracle:CRM.CUSTOMERS.CUSTOMER_ID"
    assert relationships[1].relationship_type == "foreign_key"
    assert relationships[1].source_object_id == "column:source-crm-oracle:CRM.ORDERS.CUSTOMER_ID"
    assert relationships[1].target_object_id == "column:source-crm-oracle:CRM.CUSTOMERS.CUSTOMER_ID"
