from datetime import datetime, timezone
import json
import os
import tempfile

import pytest

from sanitized_data_platform.adapters.postgres.baseline_refresh_pipeline import (
    PostgreSQLBaselineRefreshPipelineAdapter,
)
from sanitized_data_platform.application.dto import CreateBaselineRefreshJobCommand
from sanitized_data_platform.application.services import BaselineRefreshRequestService
from sanitized_data_platform.domain.entities import (
    BaselineRefreshJob,
    MetadataObject,
    Relationship,
)
from sanitized_data_platform.domain.enums import (
    BaselineRefreshStatus,
    DatabaseEngine,
    MetadataObjectType,
)
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import (
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineAssetRepository,
    InMemoryBaselineRefreshJobRepository,
    InMemoryBaselineRefreshQueue,
    InMemoryBaselineRepository,
    InMemoryDataSourceRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryDatasetProfileRepository,
    InMemoryLineageRepository,
    InMemorySystemRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    sample_baseline,
    sample_profile,
    sample_source,
    sample_system,
    sample_validation_report,
)
from sanitized_data_platform.workers.baseline_refresh_worker import BaselineRefreshWorker


def canonical_metadata_objects() -> list[MetadataObject]:
    source = sample_source()
    return [
        MetadataObject(
            object_id="table:source-crm-replica:public.customers",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="customers",
            qualified_name="public.customers",
        ),
        MetadataObject(
            object_id="table:source-crm-replica:public.orders",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="orders",
            qualified_name="public.orders",
        ),
        MetadataObject(
            object_id="column-customers-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="public.customers.customer_id",
            parent_object_id="table:source-crm-replica:public.customers",
        ),
        MetadataObject(
            object_id="column-customers-email",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="email",
            qualified_name="public.customers.email",
            parent_object_id="table:source-crm-replica:public.customers",
        ),
        MetadataObject(
            object_id="column-orders-order-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="order_id",
            qualified_name="public.orders.order_id",
            parent_object_id="table:source-crm-replica:public.orders",
        ),
        MetadataObject(
            object_id="column-orders-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="public.orders.customer_id",
            parent_object_id="table:source-crm-replica:public.orders",
        ),
    ]


def canonical_relationships() -> list[Relationship]:
    source = sample_source()
    return [
        Relationship(
            relationship_id="fk:orders.customer_id->customers.customer_id",
            source_id=source.source_id,
            source_object_id="column-orders-customer-id",
            target_object_id="column-customers-customer-id",
            relationship_type="foreign_key",
            inferred=False,
            confidence=1.0,
        )
    ]


class FakeCursor:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_config: dict[str, dict[str, object]],
    ) -> None:
        self._executed = executed
        self._table_config = table_config
        self._last_query = ""
        self._last_params: tuple[object, ...] | None = None
        self._current_table: str | None = None
        self._row_offset = 0

    def execute(self, query: str, params=None) -> None:
        self._executed.append((query, params))
        self._last_query = query
        self._last_params = params
        self._row_offset = 0
        self._current_table = self._resolve_table(query, params)

    def fetchone(self) -> tuple[object, ...]:
        assert self._current_table is not None
        return (self._table_config[self._current_table]["row_count"],)

    def fetchall(self) -> list[tuple[object, ...]]:
        if "information_schema.columns" in self._last_query:
            assert self._last_params is not None
            schema_name = str(self._last_params[0])
            table_name = str(self._last_params[1])
            table_key = f"{schema_name}.{table_name}"
            return [(column,) for column in self._table_config[table_key]["columns"]]
        if "constraint_type = 'PRIMARY KEY'" in self._last_query:
            assert self._last_params is not None
            schema_name = str(self._last_params[0])
            table_name = str(self._last_params[1])
            table_key = f"{schema_name}.{table_name}"
            return [(column,) for column in self._table_config[table_key]["pk_columns"]]
        return []

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        if self._current_table is None or "SELECT " not in self._last_query:
            return []
        rows = self._table_config[self._current_table]["rows"]
        assert isinstance(rows, list)
        start = self._row_offset
        end = min(start + size, len(rows))
        self._row_offset = end
        return list(rows[start:end])

    @property
    def description(self):
        if self._current_table is None or "SELECT " not in self._last_query:
            return None
        columns = self._table_config[self._current_table]["columns"]
        assert isinstance(columns, tuple)
        return tuple((column_name,) for column_name in columns)

    def close(self) -> None:
        return None

    def _resolve_table(self, query: str, params) -> str | None:
        if "information_schema.columns" in query or "constraint_type = 'PRIMARY KEY'" in query:
            return None
        marker = 'FROM "'
        if marker not in query:
            return None
        after_from = query.split(marker, 1)[1]
        schema_name, remainder = after_from.split('"."', 1)
        table_name = remainder.split('"', 1)[0]
        return f"{schema_name}.{table_name}"


class FakeConnection:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_config: dict[str, dict[str, object]],
    ) -> None:
        self._executed = executed
        self._table_config = table_config

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._executed, self._table_config)

    def close(self) -> None:
        return None


def refresh_job() -> BaselineRefreshJob:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BaselineRefreshJob(
        job_id="baseline-refresh-1",
        system_id="crm",
        dataset_profile_id="profile-full-sanitized",
        target_environment_type=sample_profile().target_environment_type,
        requested_by="steward@example.internal",
        trigger_type="manual",
        refresh_schedule_id=None,
        status=BaselineRefreshStatus.RUNNING,
        baseline_id=None,
        created_at=created_at,
        updated_at=created_at,
        result_summary={},
    )


def test_postgres_baseline_refresh_pipeline_materializes_catalog_tables_in_fk_order():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    table_config = {
        "public.customers": {
            "columns": ("customer_id", "email"),
            "pk_columns": ("customer_id",),
            "rows": [(1, "a@example.internal"), (2, "b@example.internal")],
            "row_count": 2,
        },
        "public.orders": {
            "columns": ("order_id", "customer_id"),
            "pk_columns": ("order_id",),
            "rows": [(10, 1)],
            "row_count": 1,
        },
    }
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = PostgreSQLBaselineRefreshPipelineAdapter(
            metadata_catalog=InMemoryMetadataCatalogRepository(
                canonical_metadata_objects(),
                canonical_relationships(),
            ),
            data_sources=InMemoryDataSourceRepository([sample_source()]),
            connect=lambda _endpoint: FakeConnection(executed, table_config),
            artifact_dir=artifact_dir,
            clock=FakeClock(),
        )

        summary = adapter.execute(
            job=refresh_job(),
            source=sample_source(),
            profile=sample_profile(),
            existing_baseline=None,
        )

        assert summary["refreshStrategy"] == "postgres-materialized-baseline"
        assert summary["version"] == "2026.01.01.0000"
        assert summary["reusedBaseline"] is False
        assert summary["materializedTableCount"] == 2
        assert summary["rowsMaterialized"] == 3
        assert [item["rootObjectId"] for item in summary["baselineAssets"]] == [
            "table:source-crm-replica:public.customers",
            "table:source-crm-replica:public.orders",
        ]
        assert [item["importOrder"] for item in summary["baselineAssets"]] == [0, 1]
        for asset in summary["baselineAssets"]:
            assert os.path.exists(asset["artifactPath"])
            with open(asset["artifactPath"], encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
            assert len(rows) == asset["rowCount"]


def test_postgres_baseline_refresh_pipeline_rejects_missing_catalog_tables():
    adapter = PostgreSQLBaselineRefreshPipelineAdapter(
        metadata_catalog=InMemoryMetadataCatalogRepository(objects=[], relationships=[]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        connect=lambda _endpoint: FakeConnection([], {}),
        clock=FakeClock(),
    )

    with pytest.raises(DomainError) as exc:
        adapter.execute(
            job=refresh_job(),
            source=sample_source(),
            profile=sample_profile(),
            existing_baseline=None,
        )

    assert "No materializable catalog tables are available" in str(exc.value)


def test_postgres_baseline_refresh_pipeline_rejects_non_postgres_sources():
    adapter = PostgreSQLBaselineRefreshPipelineAdapter(
        metadata_catalog=InMemoryMetadataCatalogRepository(
            canonical_metadata_objects(),
            canonical_relationships(),
        ),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        connect=lambda _endpoint: FakeConnection([], {}),
        clock=FakeClock(),
    )
    source = sample_source()
    non_postgres_source = type(source)(
        source_id=source.source_id,
        system_id=source.system_id,
        system_name=source.system_name,
        engine_type=DatabaseEngine.MYSQL,
        endpoint=source.endpoint,
        database_name=source.database_name,
        access_mode=source.access_mode,
        replica_preferred=source.replica_preferred,
        active=source.active,
    )

    with pytest.raises(DomainError) as exc:
        adapter.execute(
            job=refresh_job(),
            source=non_postgres_source,
            profile=sample_profile(),
            existing_baseline=None,
        )

    assert "can only execute postgres data sources" in str(exc.value)


def test_baseline_refresh_worker_uses_real_postgres_refresh_pipeline():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    table_config = {
        "public.customers": {
            "columns": ("customer_id", "email"),
            "pk_columns": ("customer_id",),
            "rows": [(1, "a@example.internal"), (2, "b@example.internal")],
            "row_count": 2,
        },
        "public.orders": {
            "columns": ("order_id", "customer_id"),
            "pk_columns": ("order_id",),
            "rows": [(10, 1)],
            "row_count": 1,
        },
    }
    with tempfile.TemporaryDirectory() as artifact_dir:
        system_repo = InMemorySystemRepository([sample_system()])
        source_repo = InMemoryDataSourceRepository([sample_source()])
        profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
        baseline_repo = InMemoryBaselineRepository([sample_baseline()])
        baseline_asset_repo = InMemoryBaselineAssetRepository()
        refresh_job_repo = InMemoryBaselineRefreshJobRepository()
        refresh_queue = InMemoryBaselineRefreshQueue()
        audit_repo = InMemoryAuditEventRepository()
        lineage_repo = InMemoryLineageRepository()
        clock = FakeClock()
        ids = SequentialIdGenerator()

        request = BaselineRefreshRequestService(
            systems=system_repo,
            data_sources=source_repo,
            dataset_profiles=profile_repo,
            refresh_jobs=refresh_job_repo,
            refresh_queue=refresh_queue,
            audits=audit_repo,
            clock=clock,
            ids=ids,
        )
        created = request.create_job(
            CreateBaselineRefreshJobCommand(
                system_id="crm",
                dataset_profile_id="profile-full-sanitized",
                target_environment_type="dev",
                requested_by="steward@example.internal",
            )
        )

        worker = BaselineRefreshWorker(
            systems=system_repo,
            refresh_queue=refresh_queue,
            refresh_jobs=refresh_job_repo,
            baselines=baseline_repo,
            baseline_assets=baseline_asset_repo,
            data_sources=source_repo,
            dataset_profiles=profile_repo,
            pipeline=PostgreSQLBaselineRefreshPipelineAdapter(
                metadata_catalog=InMemoryMetadataCatalogRepository(
                    canonical_metadata_objects(),
                    canonical_relationships(),
                ),
                data_sources=source_repo,
                connect=lambda _endpoint: FakeConnection(executed, table_config),
                artifact_dir=artifact_dir,
                clock=clock,
            ),
            audits=audit_repo,
            lineage=lineage_repo,
            validations=InMemoryValidationRepository([sample_validation_report()]),
            clock=clock,
            ids=ids,
        )

        processed_job_id = worker.process_next_job()
        refreshed_job = refresh_job_repo.get_by_id(created.job_id)
        assets = baseline_asset_repo.list_for_baseline("baseline-crm-dev-v1")

    assert processed_job_id == created.job_id
    assert refreshed_job is not None
    assert refreshed_job.status.value == "completed"
    assert refreshed_job.result_summary["refreshStrategy"] == "postgres-materialized-baseline"
    assert refreshed_job.result_summary["materializedTableCount"] == 2
    assert refreshed_job.result_summary["rowsMaterialized"] == 3
    assert len(assets) == 2
    assert [asset.root_object_id for asset in assets] == [
        "table:source-crm-replica:public.customers",
        "table:source-crm-replica:public.orders",
    ]
