from __future__ import annotations

from typing import Any, Callable, Protocol

from sanitized_data_platform.domain.entities import DataSource, MetadataObject, Relationship
from sanitized_data_platform.domain.enums import DatabaseEngine, MetadataObjectType
from sanitized_data_platform.domain.errors import DomainError


class CursorLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def close(self) -> None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...
    def close(self) -> None: ...


class PostgreSQLMetadataDiscoveryAdapter:
    """PostgreSQL metadata discovery using system catalog queries via a DB-API-like connection."""

    _LIST_SCHEMAS_SQL = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
          AND schema_name NOT LIKE 'pg_toast%%'
        ORDER BY schema_name
    """

    _LIST_TABLES_SQL = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('information_schema', 'pg_catalog')
          AND table_schema NOT LIKE 'pg_toast%%'
        ORDER BY table_schema, table_name
    """

    _LIST_COLUMNS_SQL = """
        SELECT table_schema, table_name, column_name, data_type, udt_name, ordinal_position
        FROM information_schema.columns
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
          AND table_schema NOT LIKE 'pg_toast%%'
        ORDER BY table_schema, table_name, ordinal_position
    """

    _LIST_PRIMARY_KEYS_SQL = """
        SELECT kcu.table_schema, kcu.table_name, kcu.column_name, kcu.ordinal_position
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND kcu.table_schema NOT IN ('information_schema', 'pg_catalog')
          AND kcu.table_schema NOT LIKE 'pg_toast%%'
        ORDER BY kcu.table_schema, kcu.table_name, kcu.ordinal_position
    """

    _LIST_FOREIGN_KEYS_SQL = """
        SELECT
            kcu.table_schema,
            kcu.table_name,
            kcu.column_name,
            ccu.table_schema AS referenced_table_schema,
            ccu.table_name AS referenced_table_name,
            ccu.column_name AS referenced_column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND kcu.table_schema NOT IN ('information_schema', 'pg_catalog')
          AND kcu.table_schema NOT LIKE 'pg_toast%%'
        ORDER BY kcu.table_schema, kcu.table_name, kcu.ordinal_position
    """

    def __init__(self, connect: Callable[[str], ConnectionLike]) -> None:
        self._connect = connect

    def list_schemas(self, source: DataSource) -> list[MetadataObject]:
        self._assert_supported_source(source)
        rows = self._fetch_rows(source, self._LIST_SCHEMAS_SQL)
        return [
            MetadataObject(
                object_id=self._schema_id(source.source_id, schema_name),
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.SCHEMA,
                name=schema_name,
                qualified_name=schema_name,
            )
            for (schema_name,) in rows
        ]

    def list_tables(self, source: DataSource) -> list[MetadataObject]:
        self._assert_supported_source(source)
        rows = self._fetch_rows(source, self._LIST_TABLES_SQL)
        return [
            MetadataObject(
                object_id=self._table_id(source.source_id, schema_name, table_name),
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.TABLE,
                name=table_name,
                qualified_name=f"{schema_name}.{table_name}",
                container_name=schema_name,
                parent_object_id=self._schema_id(source.source_id, schema_name),
            )
            for schema_name, table_name in rows
        ]

    def list_columns(self, source: DataSource) -> list[MetadataObject]:
        self._assert_supported_source(source)
        rows = self._fetch_rows(source, self._LIST_COLUMNS_SQL)
        return [
            MetadataObject(
                object_id=self._column_id(source.source_id, schema_name, table_name, column_name),
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.COLUMN,
                name=column_name,
                qualified_name=f"{schema_name}.{table_name}.{column_name}",
                container_name=f"{schema_name}.{table_name}",
                parent_object_id=self._table_id(source.source_id, schema_name, table_name),
                logical_data_type=self.map_postgres_type_to_logical(
                    data_type=data_type,
                    udt_name=udt_name,
                ),
            )
            for schema_name, table_name, column_name, data_type, udt_name, _ordinal in rows
        ]

    def list_relationships(self, source: DataSource) -> list[Relationship]:
        self._assert_supported_source(source)
        primary_key_rows = self._fetch_rows(source, self._LIST_PRIMARY_KEYS_SQL)
        foreign_key_rows = self._fetch_rows(source, self._LIST_FOREIGN_KEYS_SQL)

        primary_keys = [
            Relationship(
                relationship_id=self._primary_key_id(source.source_id, schema_name, table_name, column_name),
                source_id=source.source_id,
                source_object_id=self._table_id(source.source_id, schema_name, table_name),
                target_object_id=self._column_id(source.source_id, schema_name, table_name, column_name),
                relationship_type="primary_key",
                inferred=False,
                confidence=1.0,
            )
            for schema_name, table_name, column_name, _ordinal in primary_key_rows
        ]
        foreign_keys = [
            Relationship(
                relationship_id=self._foreign_key_id(
                    source.source_id,
                    schema_name,
                    table_name,
                    column_name,
                    referenced_table_schema,
                    referenced_table_name,
                    referenced_column_name,
                ),
                source_id=source.source_id,
                source_object_id=self._column_id(source.source_id, schema_name, table_name, column_name),
                target_object_id=self._column_id(
                    source.source_id,
                    referenced_table_schema,
                    referenced_table_name,
                    referenced_column_name,
                ),
                relationship_type="foreign_key",
                inferred=False,
                confidence=1.0,
            )
            for (
                schema_name,
                table_name,
                column_name,
                referenced_table_schema,
                referenced_table_name,
                referenced_column_name,
            ) in foreign_key_rows
        ]
        return [*primary_keys, *foreign_keys]

    @staticmethod
    def map_postgres_type_to_logical(*, data_type: str, udt_name: str | None = None) -> str:
        normalized_data_type = data_type.lower()
        normalized_udt_name = None if udt_name is None else udt_name.lower()

        if normalized_data_type == "text":
            return "large_text"
        if normalized_data_type in {"character varying", "character", "uuid"}:
            return "string"
        if normalized_data_type in {"smallint", "integer", "bigint"}:
            return "integer"
        if normalized_data_type in {"numeric", "decimal", "real", "double precision", "money"}:
            return "decimal"
        if normalized_data_type == "boolean":
            return "boolean"
        if normalized_data_type == "date":
            return "date"
        if normalized_data_type.startswith("timestamp"):
            return "timestamp"
        if normalized_data_type in {"json", "jsonb"}:
            return "json"
        if normalized_data_type == "bytea":
            return "binary"

        if normalized_udt_name in {"varchar", "bpchar", "name", "inet", "cidr"}:
            return "string"
        if normalized_udt_name in {"int2", "int4", "int8"}:
            return "integer"
        if normalized_udt_name in {"float4", "float8"}:
            return "decimal"

        return "string"

    def _fetch_rows(
        self,
        source: DataSource,
        query: str,
    ) -> list[tuple[Any, ...]]:
        connection = self._connect(source.endpoint)
        cursor = connection.cursor()
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
        finally:
            cursor.close()
            connection.close()
        return rows

    def _assert_supported_source(self, source: DataSource) -> None:
        if source.engine_type != DatabaseEngine.POSTGRES:
            raise DomainError(
                "PostgreSQL metadata discovery adapter can only inspect postgres data sources."
            )

    @staticmethod
    def _schema_id(source_id: str, schema_name: str) -> str:
        return f"schema:{source_id}:{schema_name}"

    @staticmethod
    def _table_id(source_id: str, schema_name: str, table_name: str) -> str:
        return f"table:{source_id}:{schema_name}.{table_name}"

    @staticmethod
    def _column_id(
        source_id: str,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> str:
        return f"column:{source_id}:{schema_name}.{table_name}.{column_name}"

    @staticmethod
    def _primary_key_id(
        source_id: str,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> str:
        return f"pk:{source_id}:{schema_name}.{table_name}.{column_name}"

    @staticmethod
    def _foreign_key_id(
        source_id: str,
        schema_name: str,
        table_name: str,
        column_name: str,
        referenced_table_schema: str,
        referenced_table_name: str,
        referenced_column_name: str,
    ) -> str:
        return (
            "fk:"
            f"{source_id}:{schema_name}.{table_name}.{column_name}"
            f"->{referenced_table_schema}.{referenced_table_name}.{referenced_column_name}"
        )
