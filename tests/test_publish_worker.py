from dataclasses import replace
import hashlib
import tempfile

from sanitized_data_platform.adapters.postgres.baseline_publish_pipeline import (
    PostgreSQLBaselinePublishPipelineAdapter,
)
from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import PublishRequestService
from sanitized_data_platform.workers.publish_worker import PublishWorker

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineAssetRepository,
    InMemoryBaselineRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryJobQueue,
    InMemoryLineageRepository,
    InMemoryPublishJobRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    StubPublishPipeline,
    build_publish_source_resolution_service,
    build_readiness_service,
    sample_baseline,
    sample_baseline_asset,
    sample_profile,
    sample_source,
    sample_target,
    sample_validation_report,
)


class FakeBaselinePublishCursor:
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


class FakeBaselinePublishConnection:
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

    def cursor(self) -> FakeBaselinePublishCursor:
        return FakeBaselinePublishCursor(self._executed, self._table_columns)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


def test_worker_processes_enqueued_job_to_completion():
    source_repo = InMemoryDataSourceRepository([sample_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_baseline()])
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    lineage_repo = InMemoryLineageRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()

    request_service = PublishRequestService(
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(clock=clock),
        publish_source_resolution=build_publish_source_resolution_service(),
        clock=clock,
        ids=ids,
    )
    created = request_service.create_job(
        CreatePublishJobCommand(
            source_id="source-crm-replica",
            target_environment_id="env-dev",
            dataset_profile_id="profile-full-sanitized",
            requested_by="developer@example.internal",
        )
    )

    worker = PublishWorker(
        queue=queue,
        jobs=job_repo,
        baselines=baseline_repo,
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        pipeline=StubPublishPipeline(),
        audits=audit_repo,
        lineage=lineage_repo,
        validations=InMemoryValidationRepository([sample_validation_report()]),
        clock=clock,
        ids=ids,
    )

    processed_job_id = worker.process_next_job()
    completed_job = job_repo.get_by_id(created.job_id)
    audit_events = audit_repo.list_for_subject(created.job_id)
    lineage_records = lineage_repo.list_related(
        reference_type="publish_job",
        reference_id=created.job_id,
    )

    assert processed_job_id == created.job_id
    assert completed_job is not None
    assert completed_job.status.value == "completed"
    assert completed_job.sanitized_baseline_id == "baseline-crm-dev-v1"
    assert completed_job.baseline_validation_status.value == "passed"
    assert completed_job.execution_summary["baselineId"] == "baseline-crm-dev-v1"
    assert completed_job.execution_summary["validationStatus"] == "pending-real-implementation"
    assert [record.event_type for record in lineage_records] == [
        "baseline_published",
        "publish_used_validated_baseline",
    ]
    assert [event.event_type for event in audit_events] == [
        "publish_job_requested",
        "publish_job_started",
        "publish_job_completed",
    ]


def test_worker_uses_real_postgres_baseline_publish_pipeline():
    source_repo = InMemoryDataSourceRepository([sample_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_baseline()])
    baseline_asset_repo = InMemoryBaselineAssetRepository()
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    lineage_repo = InMemoryLineageRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    connection = FakeBaselinePublishConnection(executed)

    request_service = PublishRequestService(
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(clock=clock),
        publish_source_resolution=build_publish_source_resolution_service(),
        clock=clock,
        ids=ids,
    )
    payload = (
        '{"customer_id": "1", "email": "a@example.internal"}\n'
        '{"customer_id": "2", "email": "b@example.internal"}\n'
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write(payload)
        handle.flush()
        baseline_asset_repo.replace_for_baseline(
            "baseline-crm-dev-v1",
            [
                replace(
                    sample_baseline_asset(),
                    artifact_path=handle.name,
                    row_count=2,
                    checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                )
            ],
        )
        created = request_service.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-replica",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )

        worker = PublishWorker(
            queue=queue,
            jobs=job_repo,
            baselines=baseline_repo,
            data_sources=source_repo,
            environments=target_repo,
            dataset_profiles=profile_repo,
            pipeline=PostgreSQLBaselinePublishPipelineAdapter(
                baseline_assets=baseline_asset_repo,
                connect=lambda _endpoint: connection,
            ),
            audits=audit_repo,
            lineage=lineage_repo,
            validations=InMemoryValidationRepository([sample_validation_report()]),
            clock=clock,
            ids=ids,
        )

        processed_job_id = worker.process_next_job()

    completed_job = job_repo.get_by_id(created.job_id)

    assert processed_job_id == created.job_id
    assert completed_job is not None
    assert completed_job.status.value == "completed"
    assert completed_job.execution_summary["baselineStrategy"] == "postgres-materialized-baseline"
    assert completed_job.execution_summary["baselineId"] == "baseline-crm-dev-v1"
    assert completed_job.execution_summary["baselineVersion"] == "2026.01.01.1"
    assert completed_job.execution_summary["targetEnvironmentId"] == "env-dev"
    assert completed_job.execution_summary["importedTableCount"] == 1
    assert completed_job.execution_summary["importedTables"] == ["public.customers"]
    assert completed_job.execution_summary["rowsPublished"] == 2
    assert completed_job.execution_summary["validationStatus"] == "passed"
    assert connection.committed is True
    assert len(executed) == 3
