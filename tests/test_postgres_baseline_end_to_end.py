from datetime import datetime, timezone
import json
import tempfile

from sanitized_data_platform.adapters.postgres.baseline_publish_pipeline import (
    PostgreSQLBaselinePublishPipelineAdapter,
)
from sanitized_data_platform.adapters.postgres.baseline_refresh_pipeline import (
    PostgreSQLBaselineRefreshPipelineAdapter,
)
from sanitized_data_platform.application.dto import (
    CreateBaselineRefreshJobCommand,
    CreatePublishJobCommand,
)
from sanitized_data_platform.application.services import (
    BaselineRefreshRequestService,
    BaselineSelectionService,
    BaselineStorageReadinessService,
    BaselineValidationEligibilityService,
    PublishRequestService,
    PublishSourceResolutionService,
    ValidationLookupService,
)
from sanitized_data_platform.domain.entities import MetadataObject, Relationship
from sanitized_data_platform.domain.enums import (
    BaselineRefreshStatus,
    MetadataObjectType,
)
from sanitized_data_platform.workers.baseline_refresh_worker import BaselineRefreshWorker
from sanitized_data_platform.workers.publish_worker import PublishWorker

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineAssetRepository,
    InMemoryBaselineRefreshJobRepository,
    InMemoryBaselineRefreshQueue,
    InMemoryBaselineRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryJobQueue,
    InMemoryLineageRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryPublishJobRepository,
    InMemorySystemRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    build_readiness_service,
    sample_baseline,
    sample_profile,
    sample_source,
    sample_system,
    sample_target,
    sample_validation_report,
)


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


class SourceCursor:
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
        self._current_table = self._resolve_table(query, params)
        self._row_offset = 0

    def fetchone(self) -> tuple[object, ...]:
        assert self._current_table is not None
        return (self._table_config[self._current_table]["row_count"],)

    def fetchall(self) -> list[tuple[object, ...]]:
        if "information_schema.columns" in self._last_query:
            assert self._last_params is not None
            table_key = f"{self._last_params[0]}.{self._last_params[1]}"
            return [(column,) for column in self._table_config[table_key]["columns"]]
        if "constraint_type = 'PRIMARY KEY'" in self._last_query:
            assert self._last_params is not None
            table_key = f"{self._last_params[0]}.{self._last_params[1]}"
            return [(column,) for column in self._table_config[table_key]["pk_columns"]]
        return []

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        if self._current_table is None:
            return []
        rows = self._table_config[self._current_table]["rows"]
        assert isinstance(rows, list)
        start = self._row_offset
        end = min(start + size, len(rows))
        self._row_offset = end
        return list(rows[start:end])

    @property
    def description(self):
        if self._current_table is None:
            return None
        columns = self._table_config[self._current_table]["columns"]
        assert isinstance(columns, tuple)
        return tuple((column_name,) for column_name in columns)

    def close(self) -> None:
        return None

    def _resolve_table(self, query: str, params) -> str | None:
        if "information_schema.columns" in query or "constraint_type = 'PRIMARY KEY'" in query:
            return None
        if 'FROM "' not in query:
            return None
        after_from = query.split('FROM "', 1)[1]
        schema_name, remainder = after_from.split('"."', 1)
        table_name = remainder.split('"', 1)[0]
        return f"{schema_name}.{table_name}"


class SourceConnection:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_config: dict[str, dict[str, object]],
    ) -> None:
        self._executed = executed
        self._table_config = table_config

    def cursor(self) -> SourceCursor:
        return SourceCursor(self._executed, self._table_config)

    def close(self) -> None:
        return None


class TargetCursor:
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
        table_key = f"{self._last_params[0]}.{self._last_params[1]}"
        return [(column_name, "text", "text", "YES") for column_name in self._table_columns[table_key]]

    def close(self) -> None:
        return None


class TargetConnection:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: dict[str, tuple[str, ...]],
    ) -> None:
        self._executed = executed
        self._table_columns = table_columns
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> TargetCursor:
        return TargetCursor(self._executed, self._table_columns)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


def test_postgres_baseline_refresh_to_publish_flow_is_coherent():
    source_table_config = {
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
    target_columns = {
        "public.customers": ("customer_id", "email"),
        "public.orders": ("order_id", "customer_id"),
    }
    source_executed: list[tuple[str, tuple[object, ...] | None]] = []
    target_executed: list[tuple[str, tuple[object, ...] | None]] = []

    with tempfile.TemporaryDirectory() as artifact_dir:
        system_repo = InMemorySystemRepository([sample_system()])
        source_repo = InMemoryDataSourceRepository([sample_source()])
        target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
        profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
        baseline_repo = InMemoryBaselineRepository([sample_baseline()])
        baseline_asset_repo = InMemoryBaselineAssetRepository()
        refresh_job_repo = InMemoryBaselineRefreshJobRepository()
        refresh_queue = InMemoryBaselineRefreshQueue()
        publish_job_repo = InMemoryPublishJobRepository()
        publish_queue = InMemoryJobQueue()
        audit_repo = InMemoryAuditEventRepository()
        lineage_repo = InMemoryLineageRepository()
        validation_repo = InMemoryValidationRepository([sample_validation_report()])
        clock = FakeClock()
        ids = SequentialIdGenerator()

        refresh_request = BaselineRefreshRequestService(
            systems=system_repo,
            data_sources=source_repo,
            dataset_profiles=profile_repo,
            refresh_jobs=refresh_job_repo,
            refresh_queue=refresh_queue,
            audits=audit_repo,
            clock=clock,
            ids=ids,
        )
        refresh_job = refresh_request.create_job(
            CreateBaselineRefreshJobCommand(
                system_id="crm",
                dataset_profile_id="profile-full-sanitized",
                target_environment_type="dev",
                requested_by="steward@example.internal",
            )
        )

        refresh_worker = BaselineRefreshWorker(
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
                connect=lambda _endpoint: SourceConnection(source_executed, source_table_config),
                artifact_dir=artifact_dir,
                clock=clock,
            ),
            audits=audit_repo,
            lineage=lineage_repo,
            validations=validation_repo,
            clock=clock,
            ids=ids,
        )

        assert refresh_worker.process_next_job() == refresh_job.job_id

        publish_requests = PublishRequestService(
            data_sources=source_repo,
            environments=target_repo,
            dataset_profiles=profile_repo,
            jobs=publish_job_repo,
            audits=audit_repo,
            queue=publish_queue,
            policy=AllowAllPolicy(),
            readiness=build_readiness_service(clock=clock),
            publish_source_resolution=PublishSourceResolutionService(
                BaselineSelectionService(
                    baseline_repo,
                    BaselineStorageReadinessService(baseline_asset_repo),
                    BaselineValidationEligibilityService(
                        ValidationLookupService(validation_repo)
                    ),
                )
            ),
            clock=clock,
            ids=ids,
        )
        publish_job = publish_requests.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-replica",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )

        publish_worker = PublishWorker(
            queue=publish_queue,
            jobs=publish_job_repo,
            baselines=baseline_repo,
            data_sources=source_repo,
            environments=target_repo,
            dataset_profiles=profile_repo,
            pipeline=PostgreSQLBaselinePublishPipelineAdapter(
                baseline_assets=baseline_asset_repo,
                connect=lambda _endpoint: TargetConnection(target_executed, target_columns),
            ),
            audits=audit_repo,
            lineage=lineage_repo,
            validations=validation_repo,
            clock=clock,
            ids=ids,
        )

        assert publish_worker.process_next_job() == publish_job.job_id

        refreshed = refresh_job_repo.get_by_id(refresh_job.job_id)
        published = publish_job_repo.get_by_id(publish_job.job_id)
        assets = baseline_asset_repo.list_for_baseline("baseline-crm-dev-v1")
        with open(assets[0].artifact_path, encoding="utf-8") as handle:
            first_asset_rows = [json.loads(line) for line in handle if line.strip()]

    assert refreshed is not None
    assert refreshed.status == BaselineRefreshStatus.COMPLETED
    assert refreshed.result_summary["materializedTableCount"] == 2
    assert len(assets) == 2
    assert published is not None
    assert published.status.value == "completed"
    assert published.execution_summary["baselineStrategy"] == "postgres-materialized-baseline"
    assert published.execution_summary["rowsPublished"] == 3
    assert published.execution_summary["importedTables"] == [
        "public.customers",
        "public.orders",
    ]
    assert len(source_executed) > 0
    assert len(target_executed) == 5
    assert len(first_asset_rows) == 2
