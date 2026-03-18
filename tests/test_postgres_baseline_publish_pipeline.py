from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import tempfile

import pytest

from sanitized_data_platform.adapters.postgres.baseline_publish_pipeline import (
    PostgreSQLBaselinePublishPipelineAdapter,
)
from sanitized_data_platform.domain.entities import PublishJob
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import (
    InMemoryBaselineAssetRepository,
    sample_baseline,
    sample_baseline_asset,
    sample_profile,
    sample_source,
    sample_target,
)


class FakeCursor:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: dict[str, tuple[str, ...]],
    ) -> None:
        self._executed = executed
        self._table_columns = table_columns
        self._last_query = ""
        self._last_params: tuple[object, ...] | None = None

    def execute(self, query: str, params=None) -> None:
        self._executed.append((query, params))
        self._last_query = query
        self._last_params = params

    def fetchall(self) -> list[tuple[object, ...]]:
        if "information_schema.columns" not in self._last_query:
            return []
        assert self._last_params is not None
        schema_name = str(self._last_params[0])
        table_name = str(self._last_params[1])
        columns = self._table_columns[f"{schema_name}.{table_name}"]
        return [(column_name, "text", "text", "YES") for column_name in columns]

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._executed = executed
        self._table_columns = (
            {"public.customers": ("customer_id", "email")}
            if table_columns is None
            else table_columns
        )
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


def publish_job() -> PublishJob:
    return PublishJob.create(
        job_id="job-1",
        source_id="source-crm-replica",
        sanitized_baseline_id="baseline-crm-dev-v1",
        baseline_validation_status=None,
        baseline_validation_warning_count=0,
        baseline_validation_error_count=0,
        baseline_validated_at=None,
        target_environment_id="env-dev",
        dataset_profile_id="profile-full-sanitized",
        requested_by="developer@example.internal",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_postgres_baseline_publish_pipeline_imports_materialized_baseline_assets():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    connection = FakeConnection(executed)
    payload = (
        '{"customer_id": "1", "email": "a@example.internal"}\n'
        '{"customer_id": "2", "email": "b@example.internal"}\n'
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write(payload)
        handle.flush()
        baseline_assets = InMemoryBaselineAssetRepository(
            [
                replace(
                    sample_baseline_asset(),
                    artifact_path=handle.name,
                    row_count=2,
                    checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                )
            ]
        )
        adapter = PostgreSQLBaselinePublishPipelineAdapter(
            baseline_assets=baseline_assets,
            connect=lambda _endpoint: connection,
        )

        summary = adapter.execute(
            job=publish_job(),
            source=sample_source(),
            baseline=sample_baseline(),
            target=sample_target(),
            profile=sample_profile(),
        )

    assert summary["baselineStrategy"] == "postgres-materialized-baseline"
    assert summary["baselineId"] == "baseline-crm-dev-v1"
    assert summary["baselineVersion"] == "2026.01.01.1"
    assert summary["targetEnvironmentId"] == "env-dev"
    assert summary["importedTableCount"] == 1
    assert summary["importedTables"] == ["public.customers"]
    assert summary["rowsPublished"] == 2
    assert connection.committed is True
    assert executed == [
        (
            adapter._LIST_TABLE_COLUMNS_SQL,
            ("public", "customers"),
        ),
        (
            'INSERT INTO "public"."customers" ("customer_id", "email") VALUES (%s, %s)',
            ("1", "a@example.internal"),
        ),
        (
            'INSERT INTO "public"."customers" ("customer_id", "email") VALUES (%s, %s)',
            ("2", "b@example.internal"),
        ),
    ]


def test_postgres_baseline_publish_pipeline_rejects_missing_materialized_assets():
    adapter = PostgreSQLBaselinePublishPipelineAdapter(
        baseline_assets=InMemoryBaselineAssetRepository(),
        connect=lambda _endpoint: FakeConnection([]),
    )

    with pytest.raises(DomainError) as exc:
        adapter.execute(
            job=publish_job(),
            source=sample_source(),
            baseline=sample_baseline(),
            target=sample_target(),
            profile=sample_profile(),
        )

    assert "No materialized baseline assets are available" in str(exc.value)


def test_postgres_baseline_publish_pipeline_rejects_checksum_mismatch_before_commit():
    connection = FakeConnection([])
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('{"customer_id": "1", "email": "a@example.internal"}\n')
        handle.flush()
        adapter = PostgreSQLBaselinePublishPipelineAdapter(
            baseline_assets=InMemoryBaselineAssetRepository(
                [
                    replace(
                        sample_baseline_asset(),
                        artifact_path=handle.name,
                        row_count=1,
                        checksum="wrong-checksum",
                    )
                ]
            ),
            connect=lambda _endpoint: connection,
        )

        with pytest.raises(DomainError) as exc:
            adapter.execute(
                job=publish_job(),
                source=sample_source(),
                baseline=sample_baseline(),
                target=sample_target(),
                profile=sample_profile(),
            )

    assert "Baseline asset checksum verification failed before commit" in str(exc.value)
    assert connection.committed is False
    assert connection.rolled_back is True
