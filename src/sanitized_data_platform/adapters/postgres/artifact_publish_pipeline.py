from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Callable, Protocol

from sanitized_data_platform.application.ports import ArtifactPublishPipelinePort
from sanitized_data_platform.domain.entities import ArtifactPublishJob, ExtractionArtifact, TargetEnvironment
from sanitized_data_platform.domain.enums import DatabaseEngine, ExtractionArtifactFormat
from sanitized_data_platform.domain.errors import DomainError


class CursorLike(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def close(self) -> None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class PostgreSQLArtifactPublishPipelineAdapter(ArtifactPublishPipelinePort):
    _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _LIST_TABLE_COLUMNS_SQL = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
    """

    def __init__(self, *, connect: Callable[[str], ConnectionLike]) -> None:
        self._connect = connect

    def execute(
        self,
        *,
        job: ArtifactPublishJob,
        artifact: ExtractionArtifact,
        target: TargetEnvironment,
    ) -> dict[str, object]:
        if target.engine_type != DatabaseEngine.POSTGRES:
            raise DomainError(
                "PostgreSQL artifact publish pipeline adapter can only execute postgres targets."
            )
        if artifact.artifact_format != ExtractionArtifactFormat.JSONL:
            raise DomainError(
                "PostgreSQL artifact publish pipeline currently supports only JSONL artifacts."
            )
        if not artifact.root_object_id.startswith("table:"):
            raise DomainError(
                "PostgreSQL artifact publish pipeline currently supports only root-table artifacts."
            )
        if not os.path.exists(artifact.artifact_path):
            raise DomainError(
                f"Extraction artifact file is missing: {artifact.artifact_path}"
            )

        schema_name, table_name = self._parse_root_table(artifact.root_object_id)
        inserted_row_count = 0
        connection = self._connect(target.target_endpoint)
        cursor = connection.cursor()
        try:
            checksum = hashlib.sha256()
            with open(artifact.artifact_path, encoding="utf-8") as artifact_file:
                column_names: list[str] | None = None
                insert_sql: str | None = None
                for raw_line in artifact_file:
                    checksum.update(raw_line.encode("utf-8"))
                    line = raw_line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise DomainError("Artifact publish expects JSONL rows as JSON objects.")
                    if column_names is None:
                        column_names = [str(name) for name in row.keys()]
                        self._validate_columns(column_names)
                        self._validate_target_table_projection(
                            cursor=cursor,
                            schema_name=schema_name,
                            table_name=table_name,
                            column_names=column_names,
                        )
                        insert_sql = self._build_insert_sql(
                            schema_name=schema_name,
                            table_name=table_name,
                            column_names=column_names,
                        )
                    elif [str(name) for name in row.keys()] != column_names:
                        raise DomainError(
                            "Artifact publish requires a consistent JSONL column projection."
                        )
                    assert insert_sql is not None
                    values = tuple(row[column_name] for column_name in column_names)
                    cursor.execute(insert_sql, values)
                    inserted_row_count += 1
            actual_checksum = checksum.hexdigest()
            if artifact.checksum is not None and actual_checksum != artifact.checksum:
                raise DomainError(
                    "Artifact publish checksum verification failed before commit."
                )
            if artifact.row_count != inserted_row_count:
                raise DomainError(
                    "Artifact publish row count verification failed before commit."
                )
            connection.commit()
        except Exception:
            if hasattr(connection, "rollback"):
                connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

        return {
            "deliveryStrategy": "postgres-jsonl-root-table-import",
            "extractionArtifactId": artifact.artifact_id,
            "artifactPath": artifact.artifact_path,
            "targetTable": f"{schema_name}.{table_name}",
            "insertedRowCount": inserted_row_count,
            "rowsImported": inserted_row_count,
            "artifactChecksumVerified": True,
            "artifactRowCountVerified": True,
        }

    def _parse_root_table(self, root_object_id: str) -> tuple[str, str]:
        parts = root_object_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "table":
            raise DomainError(f"Invalid root-table artifact object id: {root_object_id}")
        qualified_name = parts[2]
        if "." not in qualified_name:
            raise DomainError(f"Invalid root-table artifact object id: {root_object_id}")
        schema_name, table_name = qualified_name.split(".", 1)
        if not self._SAFE_IDENTIFIER.fullmatch(schema_name):
            raise DomainError(f"Unsupported schema name in artifact root object id: {schema_name}")
        if not self._SAFE_IDENTIFIER.fullmatch(table_name):
            raise DomainError(f"Unsupported table name in artifact root object id: {table_name}")
        return schema_name, table_name

    def _validate_columns(self, column_names: list[str]) -> None:
        if not column_names:
            raise DomainError("Artifact publish requires at least one projected column.")
        for column_name in column_names:
            if not self._SAFE_IDENTIFIER.fullmatch(column_name):
                raise DomainError(
                    f"Unsupported column name in artifact publish projection: {column_name}"
                )

    def _validate_target_table_projection(
        self,
        *,
        cursor: CursorLike,
        schema_name: str,
        table_name: str,
        column_names: list[str],
    ) -> None:
        cursor.execute(
            self._LIST_TABLE_COLUMNS_SQL,
            (schema_name, table_name),
        )
        available_columns = [str(row[0]) for row in cursor.fetchall()]
        if not available_columns:
            raise DomainError(
                f"Target table is not available for artifact publish: {schema_name}.{table_name}"
            )
        missing_columns = [
            column_name for column_name in column_names if column_name not in available_columns
        ]
        if missing_columns:
            raise DomainError(
                "Artifact publish projection does not match target table columns: "
                + ", ".join(missing_columns)
            )

    def _build_insert_sql(
        self,
        *,
        schema_name: str,
        table_name: str,
        column_names: list[str],
    ) -> str:
        projected_columns = ", ".join(f'"{column_name}"' for column_name in column_names)
        placeholders = ", ".join("%s" for _ in column_names)
        return (
            f'INSERT INTO "{schema_name}"."{table_name}" ({projected_columns}) '
            f"VALUES ({placeholders})"
        )
