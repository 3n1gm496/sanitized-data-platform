from datetime import datetime, timezone

from sanitized_data_platform.application.services import (
    ExtractionArtifactLifecycleService,
    ExtractionArtifactQueryService,
)
from sanitized_data_platform.domain.entities import ExtractionArtifact, ExtractionJob
from sanitized_data_platform.domain.enums import (
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    ExtractionArtifactStatus,
    ExtractionJobStatus,
)
from sanitized_data_platform.workers.extraction_artifact_retention_worker import (
    ExtractionArtifactRetentionWorker,
)

from tests.fakes import (
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryExtractionArtifactRepository,
    InMemoryExtractionJobRepository,
    SequentialIdGenerator,
)


def _completed_job(job_id: str, artifact_id: str) -> ExtractionJob:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ExtractionJob.create(
        job_id=job_id,
        source_id="source-crm-replica",
        system_id="crm",
        plan_snapshot_id=f"plan-{job_id}",
        root_object_id="table-customers",
        criteria=(),
        include_related=False,
        max_depth=1,
        requested_by="developer@example.internal",
        created_at=created_at,
    ).transition_to(
        status=ExtractionJobStatus.COMPLETED,
        updated_at=created_at,
        extraction_artifact_id=artifact_id,
    )


def test_retention_worker_expires_due_artifacts_and_keeps_non_due_available():
    artifact_repo = InMemoryExtractionArtifactRepository()
    audit_repo = InMemoryAuditEventRepository()
    due_artifact = ExtractionArtifact(
        artifact_id="artifact-due",
        job_id="extraction-due",
        source_id="source-crm-replica",
        root_object_id="table-customers",
        kind=ExtractionArtifactKind.SAMPLE,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/due.jsonl",
        row_count=2,
        created_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
        expires_at=datetime(2025, 12, 31, 1, tzinfo=timezone.utc),
    )
    non_due_artifact = ExtractionArtifact(
        artifact_id="artifact-fresh",
        job_id="extraction-fresh",
        source_id="source-crm-replica",
        root_object_id="table-customers",
        kind=ExtractionArtifactKind.SAMPLE,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/fresh.jsonl",
        row_count=1,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    artifact_repo.add(due_artifact)
    artifact_repo.add(non_due_artifact)

    clock = FakeClock()
    worker = ExtractionArtifactRetentionWorker(
        lifecycle=ExtractionArtifactLifecycleService(
            artifacts=artifact_repo,
            clock=clock,
        ),
        artifacts=artifact_repo,
        clock=clock,
        audits=audit_repo,
        ids=SequentialIdGenerator(),
    )

    summary = worker.run_once()

    stored_due = artifact_repo.get_by_id("artifact-due")
    stored_non_due = artifact_repo.get_by_id("artifact-fresh")
    audit_events = audit_repo.list_for_subject("artifact-retention-run-1")
    artifact_audit_events = audit_repo.list_for_subject("artifact-due")
    assert summary["evaluatedArtifactCount"] == 2
    assert summary["expiredArtifactCount"] == 1
    assert summary["runId"] == "artifact-retention-run-1"
    assert stored_due is not None
    assert stored_due.status == ExtractionArtifactStatus.EXPIRED
    assert stored_non_due is not None
    assert stored_non_due.status == ExtractionArtifactStatus.AVAILABLE
    assert [event.event_type for event in audit_events] == [
        "extraction_artifact_retention_completed"
    ]
    assert audit_events[0].details == {
        "evaluatedArtifactCount": 2,
        "expiredArtifactCount": 1,
    }
    assert [event.event_type for event in artifact_audit_events] == [
        "extraction_artifact_expired"
    ]
    assert artifact_audit_events[0].subject_type == "extraction_artifact"
    assert artifact_audit_events[0].details["runId"] == "artifact-retention-run-1"


def test_retention_worker_leaves_non_due_artifacts_available_for_query():
    job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    job_repo.add(_completed_job("extraction-1", "artifact-1"))
    artifact_repo.add(
        ExtractionArtifact(
            artifact_id="artifact-1",
            job_id="extraction-1",
            source_id="source-crm-replica",
            root_object_id="table-customers",
            kind=ExtractionArtifactKind.SAMPLE,
            artifact_format=ExtractionArtifactFormat.JSONL,
            artifact_path="/tmp/artifact-1.jsonl",
            row_count=1,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        )
    )
    clock = FakeClock()
    lifecycle = ExtractionArtifactLifecycleService(
        artifacts=artifact_repo,
        clock=clock,
    )
    worker = ExtractionArtifactRetentionWorker(
        lifecycle=lifecycle,
        artifacts=artifact_repo,
        clock=clock,
    )

    summary = worker.run_once()
    result = ExtractionArtifactQueryService(
        jobs=job_repo,
        artifacts=artifact_repo,
        lifecycle=lifecycle,
    ).get_artifact_for_job("extraction-1")

    assert summary["expiredArtifactCount"] == 0
    assert result.status == "available"
    assert result.available is True
