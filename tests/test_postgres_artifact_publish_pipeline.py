from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import tempfile

import pytest

from sanitized_data_platform.adapters.postgres.artifact_publish_pipeline import (
    PostgreSQLArtifactPublishPipelineAdapter,
)
from sanitized_data_platform.domain.entities import ArtifactPublishJob
from sanitized_data_platform.domain.enums import DatabaseEngine, ExtractionArtifactFormat
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import sample_extraction_artifact, sample_target


class FakeCursor:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: tuple[str, ...],
    ) -> None:
        self._executed = executed
        self._table_columns = table_columns
        self._last_query = ""

    def execute(self, query: str, params=None) -> None:
        self._executed.append((query, params))
        self._last_query = query

    def fetchall(self) -> list[tuple[object, ...]]:
        if "information_schema.columns" in self._last_query:
            return [(column_name,) for column_name in self._table_columns]
        return []

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: tuple[str, ...] = ("customer_id", "email"),
    ) -> None:
        self._executed = executed
        self._table_columns = table_columns
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._executed, self._table_columns)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


def artifact_publish_job() -> ArtifactPublishJob:
    return ArtifactPublishJob.create(
        job_id="artifact-publish-job-1",
        extraction_artifact_id="extraction-artifact-1",
        source_id="source-crm-replica",
        root_object_id="table:source-crm-replica:public.customers",
        target_environment_id="env-dev",
        requested_by="developer@example.internal",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_postgres_artifact_publish_pipeline_imports_jsonl_into_target_table():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    connection = FakeConnection(executed)
    adapter = PostgreSQLArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: connection
    )
    payload = (
        '{"customer_id": 1, "email": "a@example.internal"}\n'
        '{"customer_id": 2, "email": "b@example.internal"}\n'
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write(payload)
        handle.flush()
        artifact = replace(
            sample_extraction_artifact(),
            artifact_path=handle.name,
            row_count=2,
            checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )

        summary = adapter.execute(
            job=artifact_publish_job(),
            artifact=artifact,
            target=sample_target(),
        )

    assert summary["deliveryStrategy"] == "postgres-jsonl-root-table-import"
    assert summary["extractionArtifactId"] == "extraction-artifact-1"
    assert summary["artifactPath"] == artifact.artifact_path
    assert summary["targetTable"] == "public.customers"
    assert summary["insertedRowCount"] == 2
    assert summary["rowsImported"] == 2
    assert summary["artifactChecksumVerified"] is True
    assert summary["artifactRowCountVerified"] is True
    assert connection.committed is True
    assert executed == [
        (
            adapter._LIST_TABLE_COLUMNS_SQL,
            ("public", "customers"),
        ),
        (
            'INSERT INTO "public"."customers" ("customer_id", "email") VALUES (%s, %s)',
            (1, "a@example.internal"),
        ),
        (
            'INSERT INTO "public"."customers" ("customer_id", "email") VALUES (%s, %s)',
            (2, "b@example.internal"),
        ),
    ]


def test_postgres_artifact_publish_pipeline_rejects_missing_artifact_file():
    adapter = PostgreSQLArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: FakeConnection([])
    )
    artifact = replace(
        sample_extraction_artifact(),
        artifact_path="/tmp/missing-artifact-publish.jsonl",
    )

    with pytest.raises(DomainError) as exc:
        adapter.execute(
            job=artifact_publish_job(),
            artifact=artifact,
            target=sample_target(),
        )

    assert "artifact file is missing" in str(exc.value)


def test_postgres_artifact_publish_pipeline_rejects_non_object_jsonl_rows():
    adapter = PostgreSQLArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: FakeConnection([])
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('["not", "an", "object"]\n')
        handle.flush()
        artifact = replace(
            sample_extraction_artifact(),
            artifact_path=handle.name,
        )

        with pytest.raises(DomainError) as exc:
            adapter.execute(
                job=artifact_publish_job(),
                artifact=artifact,
                target=sample_target(),
            )

    assert "expects JSONL rows as JSON objects" in str(exc.value)


def test_postgres_artifact_publish_pipeline_rejects_unsupported_artifact_format():
    adapter = PostgreSQLArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: FakeConnection([])
    )
    artifact = replace(
        sample_extraction_artifact(),
        artifact_format=ExtractionArtifactFormat.CSV,
    )

    with pytest.raises(DomainError) as exc:
        adapter.execute(
            job=artifact_publish_job(),
            artifact=artifact,
            target=sample_target(),
        )

    assert "supports only JSONL artifacts" in str(exc.value)


def test_postgres_artifact_publish_pipeline_rejects_unsupported_target_engine():
    adapter = PostgreSQLArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: FakeConnection([])
    )
    target = replace(sample_target(), engine_type=DatabaseEngine.SQLSERVER)

    with pytest.raises(DomainError) as exc:
        adapter.execute(
            job=artifact_publish_job(),
            artifact=sample_extraction_artifact(),
            target=target,
        )

    assert "can only execute postgres targets" in str(exc.value)


def test_postgres_artifact_publish_pipeline_rejects_missing_target_columns():
    adapter = PostgreSQLArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: FakeConnection([], table_columns=("customer_id",))
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('{"customer_id": 1, "email": "a@example.internal"}\n')
        handle.flush()
        artifact = replace(
            sample_extraction_artifact(),
            artifact_path=handle.name,
        )

        with pytest.raises(DomainError) as exc:
            adapter.execute(
                job=artifact_publish_job(),
                artifact=artifact,
                target=sample_target(),
            )

    assert "projection does not match target table columns: email" in str(exc.value)


def test_postgres_artifact_publish_pipeline_rejects_checksum_mismatch_before_commit():
    connection = FakeConnection([])
    adapter = PostgreSQLArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: connection
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('{"customer_id": 1, "email": "a@example.internal"}\n')
        handle.flush()
        artifact = replace(
            sample_extraction_artifact(),
            artifact_path=handle.name,
            row_count=1,
            checksum="wrong-checksum",
        )

        with pytest.raises(DomainError) as exc:
            adapter.execute(
                job=artifact_publish_job(),
                artifact=artifact,
                target=sample_target(),
            )

    assert "checksum verification failed before commit" in str(exc.value)
    assert connection.committed is False
    assert connection.rolled_back is True
