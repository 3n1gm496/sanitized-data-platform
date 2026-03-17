from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from typing import Any, Callable, Protocol

from sanitized_data_platform.application.ports import (
    DataSourceRepository,
    TokenVaultPort,
    TransformationPolicyRepository,
)
from sanitized_data_platform.application.services import RowTransformationService
from sanitized_data_platform.domain.entities import (
    ExtractionJob,
    ExtractionPlan,
    TransformationPolicy,
)
from sanitized_data_platform.domain.enums import DatabaseEngine, ExtractionArtifactKind
from sanitized_data_platform.domain.errors import DomainError


class CursorLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def fetchmany(self, size: int) -> list[tuple[Any, ...]]: ...
    @property
    def description(self) -> tuple[tuple[Any, ...], ...] | None: ...
    def close(self) -> None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...
    def close(self) -> None: ...


class PostgreSQLExtractionPipelineAdapter:
    """Minimal real extraction execution for PostgreSQL table-root plans."""

    _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _STREAM_BATCH_SIZE = 1000
    _OPERATORS = {
        "eq": "=",
        "ne": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "like": "LIKE",
        "ilike": "ILIKE",
    }
    _LIST_TABLE_COLUMNS_SQL = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
    """
    _LIST_PRIMARY_KEY_COLUMNS_SQL = """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND kcu.table_schema = %s
          AND kcu.table_name = %s
        ORDER BY kcu.ordinal_position
    """

    def __init__(
        self,
        *,
        data_sources: DataSourceRepository,
        connect: Callable[[str], ConnectionLike],
        policies: TransformationPolicyRepository | None = None,
        transformations: RowTransformationService | None = None,
        token_vault: TokenVaultPort | None = None,
        sample_limit: int = 10,
        artifact_dir: str | None = None,
    ) -> None:
        self._data_sources = data_sources
        self._connect = connect
        self._policies = policies
        self._transformations = transformations or RowTransformationService(
            token_vault=token_vault
        )
        self._sample_limit = sample_limit
        self._artifact_dir = artifact_dir

    def execute(
        self,
        *,
        job: ExtractionJob,
        plan: ExtractionPlan,
    ) -> dict[str, object]:
        source = self._data_sources.get_by_id(job.source_id)
        if source is None or not source.active:
            raise DomainError(f"Unknown or inactive data source: {job.source_id}")
        if source.engine_type != DatabaseEngine.POSTGRES:
            raise DomainError(
                "PostgreSQL extraction pipeline adapter can only execute postgres data sources."
            )

        schema_name, table_name = self._parse_table_root(source.source_id, plan.root.object_id)
        available_columns = self._list_table_columns(source.endpoint, schema_name, table_name)
        selected_columns = self._resolve_selected_columns(
            plan=plan,
            available_columns=available_columns,
        )
        deterministic_ordering = self._list_primary_key_columns(
            source.endpoint,
            schema_name,
            table_name,
        )
        where_sql, params = self._build_where_clause(
            plan,
            allowed_columns=available_columns,
        )
        count_query = f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"{where_sql}'
        row_count = self._execute_count(source.endpoint, count_query, params)
        active_policies = self._list_active_policies(source.system_id)

        if plan.root.artifact_kind == ExtractionArtifactKind.FULL:
            materialization_result = self._stream_rows_to_jsonl(
                endpoint=source.endpoint,
                object_id=plan.root.object_id,
                object_name=f"{schema_name}.{table_name}",
                schema_name=schema_name,
                table_name=table_name,
                selected_columns=selected_columns,
                ordering_columns=deterministic_ordering,
                where_sql=where_sql,
                where_params=params,
                policies=active_policies,
            )
            preview_rows = materialization_result["previewRows"]
            preview_limit: int | None = self._sample_limit
            artifact_contains_full_result = True
            artifact_path = str(materialization_result["artifactPath"])
            materialized_row_count = int(materialization_result["materializedRowCount"])
            artifact_metadata = {
                "fileSizeBytes": materialization_result["fileSizeBytes"],
                "checksum": materialization_result["checksum"],
                "columnCount": len(selected_columns),
            }
            transformation_summary = materialization_result["transformationSummary"]
        else:
            materialized_rows = self._execute_rows(
                source.endpoint,
                schema_name,
                table_name,
                selected_columns,
                deterministic_ordering,
                where_sql,
                params,
                self._sample_limit,
            )
            transformed_rows, transformation_summary = self._apply_transformations(
                object_id=plan.root.object_id,
                object_name=f"{schema_name}.{table_name}",
                rows=materialized_rows,
                policies=active_policies,
            )
            artifact_path = self._materialize_jsonl(transformed_rows)
            artifact_metadata = self._collect_artifact_metadata(
                artifact_path=artifact_path,
                column_count=len(selected_columns),
            )
            preview_rows = transformed_rows
            preview_limit = self._sample_limit
            artifact_contains_full_result = False
            materialized_row_count = len(transformed_rows)

        summary: dict[str, object] = {
            "extractionStrategy": "postgres-table-root",
            "rootObjectId": plan.root.object_id,
            "rootTable": f"{schema_name}.{table_name}",
            "artifactKind": plan.root.artifact_kind.value,
            "appliedCriteria": [
                {
                    "fieldName": item.field_name,
                    "operator": item.operator,
                    "value": item.value,
                }
                for item in plan.root.criteria
            ],
            "selectedColumns": selected_columns,
            "sampleOrderedBy": deterministic_ordering if deterministic_ordering else None,
            "sampleOrderingDeterministic": bool(deterministic_ordering),
            "rowCount": row_count,
            "rowSampleLimit": preview_limit,
            "rowSampleCount": len(preview_rows),
            "rowSample": preview_rows,
            "artifactContainsFullResult": artifact_contains_full_result,
            "artifactPath": artifact_path,
            "artifactFormat": "jsonl",
            "materializedRowCount": materialized_row_count,
            "artifactFileSizeBytes": artifact_metadata["fileSizeBytes"],
            "artifactChecksum": artifact_metadata["checksum"],
            "artifactColumnCount": artifact_metadata["columnCount"],
            "selectedObjectCount": len(plan.selected_object_ids),
            "selectedRelationshipCount": len(plan.selected_relationship_ids),
            "transformationsApplied": transformation_summary["applied"],
            "transformedColumns": transformation_summary["transformedColumns"],
            "transformedValueCount": transformation_summary["transformedValueCount"],
            "unsupportedTransformationTypes": transformation_summary[
                "unsupportedTransformationTypes"
            ],
        }
        if plan.traversal_rule.include_related:
            summary["notes"] = [
                "include_related is planned but related-table execution is not implemented yet; only root table extracted."
            ]
        if not deterministic_ordering:
            summary.setdefault("notes", []).append(
                "Deterministic sample ordering not available for this table; sample order may vary."
            )
        unsupported_types = transformation_summary["unsupportedTransformationTypes"]
        if unsupported_types:
            summary.setdefault("notes", []).append(
                "Unsupported transformation types were skipped: "
                + ", ".join(str(value) for value in unsupported_types)
            )
        if artifact_contains_full_result:
            summary.setdefault("notes", []).append(
                "Full extraction artifact contains all matching rows; inline rowSample is a bounded preview only."
            )
        return summary

    def _collect_artifact_metadata(
        self,
        *,
        artifact_path: str,
        column_count: int,
    ) -> dict[str, object]:
        with open(artifact_path, "rb") as artifact_file:
            content = artifact_file.read()
        return {
            "fileSizeBytes": os.path.getsize(artifact_path),
            "checksum": hashlib.sha256(content).hexdigest(),
            "columnCount": column_count,
        }

    def _apply_transformations(
        self,
        *,
        object_id: str,
        object_name: str,
        rows: list[dict[str, Any]],
        policies: list[TransformationPolicy],
    ) -> tuple[list[dict[str, Any]], dict[str, object]]:
        if not policies:
            return (
                [dict(row) for row in rows],
                {
                    "applied": False,
                    "transformedColumns": [],
                    "transformedValueCount": 0,
                    "unsupportedTransformationTypes": [],
                },
            )
        return self._transformations.apply_to_rows(
            object_id=object_id,
            object_name=object_name,
            rows=rows,
            policies=policies,
        )

    def _list_active_policies(self, system_id: str) -> list[TransformationPolicy]:
        if self._policies is None:
            return []
        return self._policies.list_active_for_system(system_id)

    def _build_where_clause(
        self,
        plan: ExtractionPlan,
        *,
        allowed_columns: list[str] | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        if not plan.root.criteria:
            return "", ()

        clauses: list[str] = []
        params: list[Any] = []
        known_columns = set(allowed_columns or [])
        for criterion in plan.root.criteria:
            field_name = criterion.field_name
            if not self._SAFE_IDENTIFIER.fullmatch(field_name):
                raise DomainError(f"Unsupported extraction field name: {field_name}")
            if allowed_columns is not None and field_name not in known_columns:
                raise DomainError(
                    f"Extraction criterion references an unknown column for table root: {field_name}"
                )
            sql_operator = self._OPERATORS.get(criterion.operator.lower())
            if sql_operator is None:
                raise DomainError(
                    f"Unsupported extraction operator for postgres execution: {criterion.operator}"
                )
            clauses.append(f'"{field_name}" {sql_operator} %s')
            params.append(criterion.value)

        return f" WHERE {' AND '.join(clauses)}", tuple(params)

    def _execute_count(
        self,
        endpoint: str,
        query: str,
        params: tuple[Any, ...],
    ) -> int:
        connection = self._connect(endpoint)
        cursor = connection.cursor()
        try:
            cursor.execute(query, params)
            result = cursor.fetchone()
        finally:
            cursor.close()
            connection.close()

        if result is None:
            return 0
        return int(result[0])

    def _execute_rows(
        self,
        endpoint: str,
        schema_name: str,
        table_name: str,
        selected_columns: list[str],
        ordering_columns: list[str],
        where_sql: str,
        where_params: tuple[Any, ...],
        row_limit: int | None,
    ) -> list[dict[str, Any]]:
        query, params = self._build_select_query(
            schema_name=schema_name,
            table_name=table_name,
            selected_columns=selected_columns,
            ordering_columns=ordering_columns,
            where_sql=where_sql,
            where_params=where_params,
            row_limit=row_limit,
        )
        connection = self._connect(endpoint)
        cursor = connection.cursor()
        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            description = cursor.description or ()
        finally:
            cursor.close()
            connection.close()

        column_names = [str(item[0]) for item in description]
        return [
            {column_names[index]: value for index, value in enumerate(row)}
            for row in rows
        ]

    def _stream_rows_to_jsonl(
        self,
        *,
        endpoint: str,
        object_id: str,
        object_name: str,
        schema_name: str,
        table_name: str,
        selected_columns: list[str],
        ordering_columns: list[str],
        where_sql: str,
        where_params: tuple[Any, ...],
        policies: list[TransformationPolicy],
    ) -> dict[str, object]:
        query, params = self._build_select_query(
            schema_name=schema_name,
            table_name=table_name,
            selected_columns=selected_columns,
            ordering_columns=ordering_columns,
            where_sql=where_sql,
            where_params=where_params,
            row_limit=None,
        )
        connection = self._connect(endpoint)
        cursor = connection.cursor()
        fd, artifact_path = tempfile.mkstemp(
            prefix="extraction-artifact-",
            suffix=".jsonl",
            dir=self._artifact_dir,
        )
        preview_rows: list[dict[str, Any]] = []
        checksum = hashlib.sha256()
        file_size_bytes = 0
        materialized_row_count = 0
        transformed_columns: set[str] = set()
        unsupported_types: set[str] = set()
        transformed_value_count = 0
        try:
            cursor.execute(query, params)
            description = cursor.description or ()
            column_names = [str(item[0]) for item in description]
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                while True:
                    batch_rows = cursor.fetchmany(self._STREAM_BATCH_SIZE)
                    if not batch_rows:
                        break
                    mapped_rows = [
                        {
                            column_names[index]: value
                            for index, value in enumerate(row)
                        }
                        for row in batch_rows
                    ]
                    transformed_batch, batch_summary = self._apply_transformations(
                        object_id=object_id,
                        object_name=object_name,
                        rows=mapped_rows,
                        policies=policies,
                    )
                    transformed_columns.update(
                        str(value) for value in batch_summary["transformedColumns"]
                    )
                    unsupported_types.update(
                        str(value)
                        for value in batch_summary["unsupportedTransformationTypes"]
                    )
                    transformed_value_count += int(batch_summary["transformedValueCount"])
                    for row in transformed_batch:
                        if len(preview_rows) < self._sample_limit:
                            preview_rows.append(dict(row))
                        line = json.dumps(row) + "\n"
                        encoded_line = line.encode("utf-8")
                        handle.write(line)
                        checksum.update(encoded_line)
                        file_size_bytes += len(encoded_line)
                        materialized_row_count += 1
        except Exception:
            os.unlink(artifact_path)
            raise
        finally:
            cursor.close()
            connection.close()

        return {
            "artifactPath": artifact_path,
            "previewRows": preview_rows,
            "materializedRowCount": materialized_row_count,
            "fileSizeBytes": file_size_bytes,
            "checksum": checksum.hexdigest(),
            "transformationSummary": {
                "applied": transformed_value_count > 0,
                "transformedColumns": sorted(transformed_columns),
                "transformedValueCount": transformed_value_count,
                "unsupportedTransformationTypes": sorted(unsupported_types),
            },
        }

    def _build_select_query(
        self,
        *,
        schema_name: str,
        table_name: str,
        selected_columns: list[str],
        ordering_columns: list[str],
        where_sql: str,
        where_params: tuple[Any, ...],
        row_limit: int | None,
    ) -> tuple[str, tuple[Any, ...]]:
        projected_columns = ", ".join(f'"{name}"' for name in selected_columns)
        order_sql = ""
        if ordering_columns:
            order_sql = " ORDER BY " + ", ".join(f'"{name}" ASC' for name in ordering_columns)
        limit_sql = ""
        params: tuple[Any, ...]
        if row_limit is None:
            params = where_params
        else:
            limit_sql = " LIMIT %s"
            params = (*where_params, row_limit)
        query = (
            f'SELECT {projected_columns} FROM "{schema_name}"."{table_name}"'
            f"{where_sql}{order_sql}{limit_sql}"
        )
        return query, params

    def _list_table_columns(
        self,
        endpoint: str,
        schema_name: str,
        table_name: str,
    ) -> list[str]:
        rows = self._fetch_rows(
            endpoint,
            self._LIST_TABLE_COLUMNS_SQL,
            (schema_name, table_name),
        )
        columns = [str(row[0]) for row in rows]
        if not columns:
            raise DomainError(
                f"No columns available for postgres extraction root table: {schema_name}.{table_name}"
            )
        for name in columns:
            if not self._SAFE_IDENTIFIER.fullmatch(name):
                raise DomainError(f"Unsupported column name in table projection: {name}")
        return columns

    def _list_primary_key_columns(
        self,
        endpoint: str,
        schema_name: str,
        table_name: str,
    ) -> list[str]:
        rows = self._fetch_rows(
            endpoint,
            self._LIST_PRIMARY_KEY_COLUMNS_SQL,
            (schema_name, table_name),
        )
        columns = [str(row[0]) for row in rows]
        for name in columns:
            if not self._SAFE_IDENTIFIER.fullmatch(name):
                raise DomainError(f"Unsupported primary key column in ordering strategy: {name}")
        return columns

    def _resolve_selected_columns(
        self,
        *,
        plan: ExtractionPlan,
        available_columns: list[str],
    ) -> list[str]:
        if not plan.root.selected_columns:
            return available_columns
        unknown_columns = [
            column_name
            for column_name in plan.root.selected_columns
            if column_name not in available_columns
        ]
        if unknown_columns:
            raise DomainError(
                "Extraction plan references unknown projected columns for table root: "
                + ", ".join(unknown_columns)
            )
        return list(plan.root.selected_columns)

    def _fetch_rows(
        self,
        endpoint: str,
        query: str,
        params: tuple[Any, ...],
    ) -> list[tuple[Any, ...]]:
        connection = self._connect(endpoint)
        cursor = connection.cursor()
        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()
        finally:
            cursor.close()
            connection.close()
        return rows

    def _parse_table_root(self, source_id: str, root_object_id: str) -> tuple[str, str]:
        prefix = f"table:{source_id}:"
        if not root_object_id.startswith(prefix):
            raise DomainError(
                "PostgreSQL extraction pipeline currently supports only table-root object ids from canonical metadata discovery."
            )
        qualified_name = root_object_id.removeprefix(prefix)
        if "." not in qualified_name:
            raise DomainError(f"Invalid table root object id: {root_object_id}")
        schema_name, table_name = qualified_name.split(".", 1)
        if not self._SAFE_IDENTIFIER.fullmatch(schema_name):
            raise DomainError(f"Unsupported schema name in root object id: {schema_name}")
        if not self._SAFE_IDENTIFIER.fullmatch(table_name):
            raise DomainError(f"Unsupported table name in root object id: {table_name}")
        return schema_name, table_name

    def _materialize_jsonl(self, rows: list[dict[str, Any]]) -> str:
        fd, artifact_path = tempfile.mkstemp(
            prefix="extraction-artifact-",
            suffix=".jsonl",
            dir=self._artifact_dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row))
                    handle.write("\n")
        except Exception:
            os.unlink(artifact_path)
            raise
        return artifact_path
