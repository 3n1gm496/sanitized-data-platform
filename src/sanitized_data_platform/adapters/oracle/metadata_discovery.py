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


class OracleMetadataDiscoveryAdapter:
    _LIST_SCHEMAS_SQL = """
        SELECT username
        FROM all_users
        WHERE username NOT IN ('SYS', 'SYSTEM')
        ORDER BY username
    """

    _LIST_TABLES_SQL = """
        SELECT owner, table_name
        FROM all_tables
        WHERE owner NOT IN ('SYS', 'SYSTEM')
        ORDER BY owner, table_name
    """

    _LIST_COLUMNS_SQL = """
        SELECT owner, table_name, column_name, data_type, data_precision, data_scale, column_id
        FROM all_tab_columns
        WHERE owner NOT IN ('SYS', 'SYSTEM')
        ORDER BY owner, table_name, column_id
    """

    _LIST_PRIMARY_KEYS_SQL = """
        SELECT cols.owner, cols.table_name, cols.column_name, cols.position
        FROM all_constraints cons
        JOIN all_cons_columns cols
          ON cons.owner = cols.owner
         AND cons.constraint_name = cols.constraint_name
        WHERE cons.constraint_type = 'P'
          AND cons.owner NOT IN ('SYS', 'SYSTEM')
        ORDER BY cols.owner, cols.table_name, cols.position
    """

    _LIST_FOREIGN_KEYS_SQL = """
        SELECT
            src.owner,
            src.table_name,
            src.column_name,
            ref.owner AS referenced_owner,
            ref.table_name AS referenced_table_name,
            ref.column_name AS referenced_column_name
        FROM all_constraints fk
        JOIN all_cons_columns src
          ON fk.owner = src.owner
         AND fk.constraint_name = src.constraint_name
        JOIN all_constraints pk
          ON fk.r_owner = pk.owner
         AND fk.r_constraint_name = pk.constraint_name
        JOIN all_cons_columns ref
          ON pk.owner = ref.owner
         AND pk.constraint_name = ref.constraint_name
         AND src.position = ref.position
        WHERE fk.constraint_type = 'R'
          AND fk.owner NOT IN ('SYS', 'SYSTEM')
        ORDER BY src.owner, src.table_name, src.position
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
                name=str(schema_name),
                qualified_name=str(schema_name),
            )
            for (schema_name,) in rows
        ]

    def list_tables(self, source: DataSource) -> list[MetadataObject]:
        self._assert_supported_source(source)
        rows = self._fetch_rows(source, self._LIST_TABLES_SQL)
        return [
            MetadataObject(
                object_id=self._table_id(source.source_id, owner, table_name),
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.TABLE,
                name=str(table_name),
                qualified_name=f"{owner}.{table_name}",
                container_name=str(owner),
                parent_object_id=self._schema_id(source.source_id, owner),
            )
            for owner, table_name in rows
        ]

    def list_columns(self, source: DataSource) -> list[MetadataObject]:
        self._assert_supported_source(source)
        rows = self._fetch_rows(source, self._LIST_COLUMNS_SQL)
        return [
            MetadataObject(
                object_id=self._column_id(source.source_id, owner, table_name, column_name),
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.COLUMN,
                name=str(column_name),
                qualified_name=f"{owner}.{table_name}.{column_name}",
                container_name=f"{owner}.{table_name}",
                parent_object_id=self._table_id(source.source_id, owner, table_name),
                logical_data_type=self.map_oracle_type_to_logical(
                    data_type=str(data_type),
                    data_precision=(
                        None if data_precision is None else int(data_precision)
                    ),
                    data_scale=None if data_scale is None else int(data_scale),
                ),
            )
            for owner, table_name, column_name, data_type, data_precision, data_scale, _column_id in rows
        ]

    def list_relationships(self, source: DataSource) -> list[Relationship]:
        self._assert_supported_source(source)
        primary_key_rows = self._fetch_rows(source, self._LIST_PRIMARY_KEYS_SQL)
        foreign_key_rows = self._fetch_rows(source, self._LIST_FOREIGN_KEYS_SQL)
        primary_keys = [
            Relationship(
                relationship_id=self._primary_key_id(source.source_id, owner, table_name, column_name),
                source_id=source.source_id,
                source_object_id=self._table_id(source.source_id, owner, table_name),
                target_object_id=self._column_id(source.source_id, owner, table_name, column_name),
                relationship_type="primary_key",
                inferred=False,
                confidence=1.0,
            )
            for owner, table_name, column_name, _position in primary_key_rows
        ]
        foreign_keys = [
            Relationship(
                relationship_id=self._foreign_key_id(
                    source.source_id,
                    owner,
                    table_name,
                    column_name,
                    referenced_owner,
                    referenced_table_name,
                    referenced_column_name,
                ),
                source_id=source.source_id,
                source_object_id=self._column_id(source.source_id, owner, table_name, column_name),
                target_object_id=self._column_id(
                    source.source_id,
                    referenced_owner,
                    referenced_table_name,
                    referenced_column_name,
                ),
                relationship_type="foreign_key",
                inferred=False,
                confidence=1.0,
            )
            for (
                owner,
                table_name,
                column_name,
                referenced_owner,
                referenced_table_name,
                referenced_column_name,
            ) in foreign_key_rows
        ]
        return [*primary_keys, *foreign_keys]

    @staticmethod
    def map_oracle_type_to_logical(
        *,
        data_type: str,
        data_precision: int | None = None,
        data_scale: int | None = None,
    ) -> str:
        normalized = data_type.upper()
        if normalized in {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "UROWID", "ROWID"}:
            return "string"
        if normalized in {"CLOB", "NCLOB", "LONG"}:
            return "large_text"
        if normalized == "NUMBER":
            if data_scale in {None, 0}:
                return "integer"
            return "decimal"
        if normalized in {"FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE"}:
            return "decimal"
        if normalized == "DATE":
            return "timestamp"
        if normalized.startswith("TIMESTAMP"):
            return "timestamp"
        if normalized in {"RAW", "LONG RAW", "BLOB"}:
            return "binary"
        if normalized == "JSON":
            return "json"
        return "string"

    def _fetch_rows(self, source: DataSource, query: str) -> list[tuple[Any, ...]]:
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
        if source.engine_type != DatabaseEngine.ORACLE:
            raise DomainError(
                "Oracle metadata discovery adapter can only inspect oracle data sources."
            )

    @staticmethod
    def _schema_id(source_id: str, schema_name: str) -> str:
        return f"schema:{source_id}:{schema_name}"

    @staticmethod
    def _table_id(source_id: str, owner: str, table_name: str) -> str:
        return f"table:{source_id}:{owner}.{table_name}"

    @staticmethod
    def _column_id(source_id: str, owner: str, table_name: str, column_name: str) -> str:
        return f"column:{source_id}:{owner}.{table_name}.{column_name}"

    @staticmethod
    def _primary_key_id(source_id: str, owner: str, table_name: str, column_name: str) -> str:
        return f"pk:{source_id}:{owner}.{table_name}.{column_name}"

    @staticmethod
    def _foreign_key_id(
        source_id: str,
        owner: str,
        table_name: str,
        column_name: str,
        referenced_owner: str,
        referenced_table_name: str,
        referenced_column_name: str,
    ) -> str:
        return (
            "fk:"
            f"{source_id}:{owner}.{table_name}.{column_name}"
            f"->{referenced_owner}.{referenced_table_name}.{referenced_column_name}"
        )
