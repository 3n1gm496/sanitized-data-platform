from __future__ import annotations

from dataclasses import replace
import re
from typing import Any

from sanitized_data_platform.domain.entities import (
    SanitizedBaseline,
    DataSource,
    MetadataObject,
    Relationship,
    TargetEnvironment,
)
from sanitized_data_platform.domain.enums import (
    BaselineStatus,
    DatabaseEngine,
    EnvironmentType,
    MetadataObjectType,
)

from tests.fakes import sample_baseline, sample_source, sample_target


def sample_oracle_source() -> DataSource:
    source = sample_source()
    return replace(
        source,
        source_id="source-crm-oracle",
        engine_type=DatabaseEngine.ORACLE,
        endpoint="oracle://crm-replica.local/CRM",
        database_name="CRM",
    )


def sample_oracle_target() -> TargetEnvironment:
    target = sample_target()
    return replace(
        target,
        engine_type=DatabaseEngine.ORACLE,
        target_endpoint="oracle://crm-dev.local/CRM",
    )


def sample_oracle_baseline() -> SanitizedBaseline:
    baseline = sample_baseline()
    source = sample_oracle_source()
    target = sample_oracle_target()
    return replace(
        baseline,
        source_id=source.source_id,
        target_environment_type=target.environment_type,
        engine_type=DatabaseEngine.ORACLE,
        status=BaselineStatus.ACTIVE,
    )


def oracle_metadata_objects() -> list[MetadataObject]:
    source = sample_oracle_source()
    return [
        MetadataObject(
            object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="CUSTOMERS",
            qualified_name="CRM.CUSTOMERS",
            container_name="CRM",
            parent_object_id="schema:source-crm-oracle:CRM",
        ),
        MetadataObject(
            object_id="table:source-crm-oracle:CRM.ORDERS",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="ORDERS",
            qualified_name="CRM.ORDERS",
            container_name="CRM",
            parent_object_id="schema:source-crm-oracle:CRM",
        ),
        MetadataObject(
            object_id="column:source-crm-oracle:CRM.CUSTOMERS.CUSTOMER_ID",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="CUSTOMER_ID",
            qualified_name="CRM.CUSTOMERS.CUSTOMER_ID",
            container_name="CRM.CUSTOMERS",
            parent_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            logical_data_type="integer",
        ),
        MetadataObject(
            object_id="column:source-crm-oracle:CRM.CUSTOMERS.EMAIL",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="EMAIL",
            qualified_name="CRM.CUSTOMERS.EMAIL",
            container_name="CRM.CUSTOMERS",
            parent_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            logical_data_type="string",
        ),
        MetadataObject(
            object_id="column:source-crm-oracle:CRM.ORDERS.ORDER_ID",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="ORDER_ID",
            qualified_name="CRM.ORDERS.ORDER_ID",
            container_name="CRM.ORDERS",
            parent_object_id="table:source-crm-oracle:CRM.ORDERS",
            logical_data_type="integer",
        ),
        MetadataObject(
            object_id="column:source-crm-oracle:CRM.ORDERS.CUSTOMER_ID",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="CUSTOMER_ID",
            qualified_name="CRM.ORDERS.CUSTOMER_ID",
            container_name="CRM.ORDERS",
            parent_object_id="table:source-crm-oracle:CRM.ORDERS",
            logical_data_type="integer",
        ),
    ]


def oracle_relationships() -> list[Relationship]:
    source = sample_oracle_source()
    return [
        Relationship(
            relationship_id="fk:source-crm-oracle:CRM.ORDERS.CUSTOMER_ID->CRM.CUSTOMERS.CUSTOMER_ID",
            source_id=source.source_id,
            source_object_id="column:source-crm-oracle:CRM.ORDERS.CUSTOMER_ID",
            target_object_id="column:source-crm-oracle:CRM.CUSTOMERS.CUSTOMER_ID",
            relationship_type="foreign_key",
            inferred=False,
            confidence=1.0,
        )
    ]


class OracleDiscoveryCursor:
    def __init__(
        self,
        rows_by_query: dict[str, list[tuple[object, ...]]],
        executed_queries: list[str],
    ) -> None:
        self._rows_by_query = rows_by_query
        self._executed_queries = executed_queries
        self._current_rows: list[tuple[object, ...]] = []

    def execute(self, query: str, params=None) -> None:
        self._executed_queries.append(query)
        normalized = query.upper()
        if "FROM ALL_USERS" in normalized:
            self._current_rows = self._rows_by_query["schemas"]
        elif "FROM ALL_TABLES" in normalized:
            self._current_rows = self._rows_by_query["tables"]
        elif "FROM ALL_TAB_COLUMNS" in normalized:
            self._current_rows = self._rows_by_query["columns"]
        elif "CONSTRAINT_TYPE = 'P'" in normalized:
            self._current_rows = self._rows_by_query["primary_keys"]
        elif "CONSTRAINT_TYPE = 'R'" in normalized:
            self._current_rows = self._rows_by_query["foreign_keys"]
        else:
            self._current_rows = []

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._current_rows)

    def close(self) -> None:
        return None


class OracleDiscoveryConnection:
    def __init__(
        self,
        rows_by_query: dict[str, list[tuple[object, ...]]],
        executed_queries: list[str],
    ) -> None:
        self._rows_by_query = rows_by_query
        self._executed_queries = executed_queries

    def cursor(self) -> OracleDiscoveryCursor:
        return OracleDiscoveryCursor(self._rows_by_query, self._executed_queries)

    def close(self) -> None:
        return None


class OracleExtractionCursor:
    def __init__(
        self,
        *,
        row_count: int,
        sample_rows: list[tuple[object, ...]],
        sample_columns: tuple[str, ...],
        table_columns: tuple[str, ...],
        pk_columns: tuple[str, ...],
        executed: list[tuple[str, tuple[object, ...] | None]],
    ) -> None:
        self._row_count = row_count
        self._sample_rows = sample_rows
        self._sample_columns = sample_columns
        self._table_columns = table_columns
        self._pk_columns = pk_columns
        self._executed = executed
        self._last_query = ""
        self._row_offset = 0

    def execute(self, query: str, params=None) -> None:
        self._executed.append((query, params))
        self._last_query = query
        self._row_offset = 0

    def fetchone(self) -> tuple[object, ...]:
        return (self._row_count,)

    def fetchall(self) -> list[tuple[object, ...]]:
        normalized = self._last_query.upper()
        if "FROM ALL_TAB_COLUMNS" in normalized:
            return [(column,) for column in self._table_columns]
        if "CONSTRAINT_TYPE = 'P'" in normalized:
            return [(column,) for column in self._pk_columns]
        if normalized.strip().startswith("SELECT "):
            return list(self._sample_rows)
        return []

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        normalized = self._last_query.upper()
        if not normalized.strip().startswith("SELECT "):
            return []
        start = self._row_offset
        end = min(start + size, len(self._sample_rows))
        self._row_offset = end
        return list(self._sample_rows[start:end])

    @property
    def description(self):
        normalized = self._last_query.upper()
        if not normalized.strip().startswith("SELECT "):
            return None
        return tuple((column_name,) for column_name in self._sample_columns)

    def close(self) -> None:
        return None


class OracleExtractionConnection:
    def __init__(
        self,
        *,
        row_count: int,
        sample_rows: list[tuple[object, ...]],
        sample_columns: tuple[str, ...],
        table_columns: tuple[str, ...],
        pk_columns: tuple[str, ...],
        executed: list[tuple[str, tuple[object, ...] | None]],
    ) -> None:
        self._row_count = row_count
        self._sample_rows = sample_rows
        self._sample_columns = sample_columns
        self._table_columns = table_columns
        self._pk_columns = pk_columns
        self._executed = executed

    def cursor(self) -> OracleExtractionCursor:
        return OracleExtractionCursor(
            row_count=self._row_count,
            sample_rows=self._sample_rows,
            sample_columns=self._sample_columns,
            table_columns=self._table_columns,
            pk_columns=self._pk_columns,
            executed=self._executed,
        )

    def close(self) -> None:
        return None


class OraclePublishCursor:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: dict[str, tuple[str, ...]],
        column_specs: dict[str, dict[str, tuple[str, str, int | None, int | None]]] | None = None,
    ) -> None:
        self._executed = executed
        self._table_columns = table_columns
        self._column_specs = column_specs or {
            table_key: {
                column_name: (
                    "NUMBER" if column_name.endswith("_ID") else "VARCHAR2",
                    "Y",
                    38 if column_name.endswith("_ID") else None,
                    0 if column_name.endswith("_ID") else None,
                )
                for column_name in columns
            }
            for table_key, columns in table_columns.items()
        }
        self._last_query = ""
        self._last_params: tuple[object, ...] | None = None

    def execute(self, query: str, params=None) -> None:
        self._executed.append((query, params))
        self._last_query = query
        self._last_params = params

    def fetchall(self) -> list[tuple[object, ...]]:
        normalized = self._last_query.upper()
        if "FROM ALL_TAB_COLUMNS" not in normalized:
            return []
        assert self._last_params is not None
        owner = str(self._last_params[0])
        table_name = str(self._last_params[1])
        table_key = f"{owner}.{table_name}"
        return [
            (
                column_name,
                self._column_specs[table_key][column_name][0],
                self._column_specs[table_key][column_name][1],
                self._column_specs[table_key][column_name][2],
                self._column_specs[table_key][column_name][3],
            )
            for column_name in self._table_columns[table_key]
        ]

    def close(self) -> None:
        return None


class OraclePublishConnection:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: dict[str, tuple[str, ...]],
        column_specs: dict[str, dict[str, tuple[str, str, int | None, int | None]]] | None = None,
    ) -> None:
        self._executed = executed
        self._table_columns = table_columns
        self._column_specs = column_specs
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> OraclePublishCursor:
        return OraclePublishCursor(
            self._executed,
            self._table_columns,
            self._column_specs,
        )

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


def parse_from_quoted_from_clause(query: str) -> str | None:
    match = re.search(r'FROM\s+"([^"]+)"\."([^"]+)"', query)
    if match is None:
        return None
    return f"{match.group(1)}.{match.group(2)}"
