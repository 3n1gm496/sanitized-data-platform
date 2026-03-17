from dataclasses import replace
from datetime import timedelta
import tempfile

import pytest

from sanitized_data_platform.adapters.postgres.artifact_publish_pipeline import (
    PostgreSQLArtifactPublishPipelineAdapter,
)
from sanitized_data_platform.application.dto import CreateArtifactPublishJobCommand
from sanitized_data_platform.application.services import (
    ArtifactPublishMonitoringService,
    ArtifactPublishRequestService,
)
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.workers.artifact_publish_worker import ArtifactPublishWorker

from tests.fakes import (
    FakeClock,
    InMemoryArtifactPublishJobRepository,
    InMemoryArtifactPublishQueue,
    InMemoryAuditEventRepository,
    InMemoryExtractionArtifactRepository,
    InMemoryLineageRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    StubArtifactPublishPipeline,
    sample_extraction_artifact,
    sample_target,
)


class FakeInsertCursor:
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


class FakeInsertConnection:
    def __init__(
        self,
        executed: list[tuple[str, tuple[object, ...] | None]],
        table_columns: tuple[str, ...] = ("customer_id", "email"),
    ) -> None:
        self._executed = executed
        self._table_columns = table_columns
        self.committed = False

    def cursor(self) -> FakeInsertCursor:
        return FakeInsertCursor(self._executed, self._table_columns)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        return None


def build_artifact_publish_services():
    artifact_repo = InMemoryExtractionArtifactRepository()
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    job_repo = InMemoryArtifactPublishJobRepository()
    queue = InMemoryArtifactPublishQueue()
    audit_repo = InMemoryAuditEventRepository()
    lineage_repo = InMemoryLineageRepository()
    validation_repo = InMemoryValidationRepository([])
    clock = FakeClock()
    ids = SequentialIdGenerator()
    request = ArtifactPublishRequestService(
        artifacts=artifact_repo,
        environments=target_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        clock=clock,
        ids=ids,
    )
    return (
        request,
        artifact_repo,
        target_repo,
        job_repo,
        queue,
        audit_repo,
        lineage_repo,
        validation_repo,
        clock,
        ids,
    )


def test_artifact_publish_job_creation_and_queue_handoff():
    (
        request,
        artifact_repo,
        _target_repo,
        job_repo,
        queue,
        audit_repo,
        _lineage_repo,
        _validation_repo,
        _clock,
        _ids,
    ) = build_artifact_publish_services()
    artifact_repo.add(sample_extraction_artifact())

    created = request.create_job(
        CreateArtifactPublishJobCommand(
            extraction_artifact_id="extraction-artifact-1",
            target_environment_id="env-dev",
            requested_by="developer@example.internal",
        )
    )

    stored = job_repo.get_by_id(created.job_id)
    audit_events = audit_repo.list_for_subject(created.job_id)

    assert created.job_id == "artifact-publish-job-1"
    assert created.extraction_artifact_id == "extraction-artifact-1"
    assert created.root_object_id == "table:source-crm-replica:public.customers"
    assert created.status == "pending"
    assert stored is not None
    assert queue.dequeue() == created.job_id
    assert [event.event_type for event in audit_events] == [
        "artifact_publish_job_requested"
    ]


def test_artifact_publish_request_rejects_unavailable_artifact():
    request, artifact_repo, *_rest = build_artifact_publish_services()
    artifact = sample_extraction_artifact().expire(
        expired_at=sample_extraction_artifact().created_at + timedelta(hours=1)
    )
    artifact_repo.add(artifact)

    with pytest.raises(DomainError) as exc:
        request.create_job(
            CreateArtifactPublishJobCommand(
                extraction_artifact_id=artifact.artifact_id,
                target_environment_id="env-dev",
                requested_by="developer@example.internal",
            )
        )

    assert "not available for publish" in str(exc.value)


def test_artifact_publish_worker_processes_job_to_completion():
    (
        request,
        artifact_repo,
        target_repo,
        job_repo,
        queue,
        audit_repo,
        lineage_repo,
        validation_repo,
        clock,
        ids,
    ) = build_artifact_publish_services()
    artifact_repo.add(sample_extraction_artifact())
    created = request.create_job(
        CreateArtifactPublishJobCommand(
            extraction_artifact_id="extraction-artifact-1",
            target_environment_id="env-dev",
            requested_by="developer@example.internal",
        )
    )

    worker = ArtifactPublishWorker(
        queue=queue,
        jobs=job_repo,
        artifacts=artifact_repo,
        environments=target_repo,
        pipeline=StubArtifactPublishPipeline(),
        audits=audit_repo,
        lineage=lineage_repo,
        validations=validation_repo,
        clock=clock,
        ids=ids,
    )

    processed_job_id = worker.process_next_job()
    completed = job_repo.get_by_id(created.job_id)
    audit_events = audit_repo.list_for_subject(created.job_id)
    lineage_items = lineage_repo.list_related(
        reference_type="artifact_publish_job",
        reference_id=created.job_id,
    )

    assert processed_job_id == created.job_id
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.execution_summary["deliveryStrategy"] == "artifact-import-stub"
    assert completed.execution_summary["extractionArtifactId"] == "extraction-artifact-1"
    assert completed.execution_summary["targetEnvironmentId"] == "env-dev"
    assert completed.execution_summary["rowsImported"] == 3
    assert [item.event_type for item in lineage_items] == [
        "artifact_publish_from_extraction_artifact",
        "artifact_publish_delivered_to_target_environment",
    ]
    assert lineage_items[0].source_id == "extraction-artifact-1"
    assert lineage_items[1].target_id == "env-dev"
    assert lineage_items[1].details["rootObjectId"] == "table:source-crm-replica:public.customers"
    assert [event.event_type for event in audit_events] == [
        "artifact_publish_job_requested",
        "artifact_publish_job_started",
        "artifact_publish_job_completed",
    ]


def test_artifact_publish_worker_uses_real_postgres_pipeline_adapter():
    (
        request,
        artifact_repo,
        target_repo,
        job_repo,
        queue,
        audit_repo,
        lineage_repo,
        validation_repo,
        clock,
        ids,
    ) = build_artifact_publish_services()
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    connection = FakeInsertConnection(executed)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('{"customer_id": 1, "email": "a@example.internal"}\n')
        handle.write('{"customer_id": 2, "email": "b@example.internal"}\n')
        handle.flush()
        artifact_repo.add(
            replace(
                sample_extraction_artifact(),
                artifact_path=handle.name,
            )
        )
        created = request.create_job(
            CreateArtifactPublishJobCommand(
                extraction_artifact_id="extraction-artifact-1",
                target_environment_id="env-dev",
                requested_by="developer@example.internal",
            )
        )

        worker = ArtifactPublishWorker(
            queue=queue,
            jobs=job_repo,
            artifacts=artifact_repo,
            environments=target_repo,
            pipeline=PostgreSQLArtifactPublishPipelineAdapter(
                connect=lambda _endpoint: connection
            ),
            audits=audit_repo,
            lineage=lineage_repo,
            validations=validation_repo,
            clock=clock,
            ids=ids,
        )

        processed_job_id = worker.process_next_job()

    completed = job_repo.get_by_id(created.job_id)
    assert processed_job_id == created.job_id
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.execution_summary["deliveryStrategy"] == "postgres-jsonl-root-table-import"
    assert completed.execution_summary["targetTable"] == "public.customers"
    assert completed.execution_summary["insertedRowCount"] == 2
    assert completed.execution_summary["rowsImported"] == 2
    assert connection.committed is True
    assert len(executed) == 3


def test_artifact_publish_worker_propagates_real_pipeline_failures():
    (
        request,
        artifact_repo,
        target_repo,
        job_repo,
        queue,
        audit_repo,
        lineage_repo,
        validation_repo,
        clock,
        ids,
    ) = build_artifact_publish_services()
    artifact_repo.add(
        replace(
            sample_extraction_artifact(),
            artifact_path="/tmp/missing-artifact-publish-worker.jsonl",
        )
    )
    created = request.create_job(
        CreateArtifactPublishJobCommand(
            extraction_artifact_id="extraction-artifact-1",
            target_environment_id="env-dev",
            requested_by="developer@example.internal",
        )
    )
    worker = ArtifactPublishWorker(
        queue=queue,
        jobs=job_repo,
        artifacts=artifact_repo,
        environments=target_repo,
        pipeline=PostgreSQLArtifactPublishPipelineAdapter(
            connect=lambda _endpoint: FakeInsertConnection([])
        ),
        audits=audit_repo,
        lineage=lineage_repo,
        validations=validation_repo,
        clock=clock,
        ids=ids,
    )

    with pytest.raises(DomainError) as exc:
        worker.process_next_job()

    failed = job_repo.get_by_id(created.job_id)
    audit_events = audit_repo.list_for_subject(created.job_id)

    assert "artifact file is missing" in str(exc.value)
    assert failed is not None
    assert failed.status.value == "failed"
    assert failed.execution_summary["error"].startswith("Extraction artifact file is missing")
    assert [event.event_type for event in audit_events] == [
        "artifact_publish_job_requested",
        "artifact_publish_job_started",
        "artifact_publish_job_failed",
    ]


def test_artifact_publish_monitoring_lists_and_reads_jobs():
    request, artifact_repo, _target_repo, job_repo, _queue, _audit_repo, *_rest = (
        build_artifact_publish_services()
    )
    artifact_repo.add(sample_extraction_artifact())

    created = request.create_job(
        CreateArtifactPublishJobCommand(
            extraction_artifact_id="extraction-artifact-1",
            target_environment_id="env-dev",
            requested_by="developer@example.internal",
        )
    )
    monitoring = ArtifactPublishMonitoringService(job_repo)

    listed = monitoring.list_jobs()
    detail = monitoring.get_job(created.job_id)

    assert listed[0].job_id == created.job_id
    assert detail.extraction_artifact_id == "extraction-artifact-1"
    assert detail.target_environment_id == "env-dev"
