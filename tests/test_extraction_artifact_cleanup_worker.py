from datetime import datetime, timezone
import os
import tempfile

from sanitized_data_platform.application.services import ExtractionArtifactCleanupService
from sanitized_data_platform.domain.entities import ExtractionArtifact
from sanitized_data_platform.domain.enums import (
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    ExtractionArtifactStatus,
)
from sanitized_data_platform.workers.extraction_artifact_cleanup_worker import (
    ExtractionArtifactCleanupWorker,
)

from tests.fakes import FakeClock, InMemoryExtractionArtifactRepository
from tests.fakes import InMemoryAuditEventRepository, SequentialIdGenerator


def test_cleanup_worker_removes_expired_artifact_file_and_marks_deleted():
    artifact_repo = InMemoryExtractionArtifactRepository()
    clock = FakeClock()
    audit_repo = InMemoryAuditEventRepository()
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write('{"customer_id": 1}\n')
        artifact_path = handle.name

    try:
        artifact_repo.add(
            ExtractionArtifact(
                artifact_id="artifact-cleanup-1",
                job_id="extraction-1",
                source_id="source-crm-replica",
                root_object_id="table-customers",
                kind=ExtractionArtifactKind.SAMPLE,
                artifact_format=ExtractionArtifactFormat.JSONL,
                artifact_path=artifact_path,
                row_count=1,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                status=ExtractionArtifactStatus.EXPIRED,
                expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )

        worker = ExtractionArtifactCleanupWorker(
            cleanup=ExtractionArtifactCleanupService(
                artifacts=artifact_repo,
                clock=clock,
            ),
            artifacts=artifact_repo,
            clock=clock,
            audits=audit_repo,
            ids=SequentialIdGenerator(),
        )

        summary = worker.run_once()
        stored = artifact_repo.get_by_id("artifact-cleanup-1")
        audit_events = audit_repo.list_for_subject("artifact-cleanup-run-1")
        artifact_audit_events = audit_repo.list_for_subject("artifact-cleanup-1")

        assert summary["runId"] == "artifact-cleanup-run-1"
        assert summary["evaluatedArtifactCount"] == 1
        assert summary["deletedArtifactCount"] == 1
        assert summary["missingFileCount"] == 0
        assert summary["failedArtifactCount"] == 0
        assert not os.path.exists(artifact_path)
        assert stored is not None
        assert stored.status == ExtractionArtifactStatus.DELETED
        assert stored.deleted_at is not None
        assert [event.event_type for event in audit_events] == [
            "extraction_artifact_cleanup_completed"
        ]
        assert audit_events[0].details == {
            "evaluatedArtifactCount": 1,
            "deletedArtifactCount": 1,
            "missingFileCount": 0,
            "failedArtifactCount": 0,
        }
        assert [event.event_type for event in artifact_audit_events] == [
            "extraction_artifact_deleted"
        ]
        assert artifact_audit_events[0].details["physicalFileMissing"] is False
    finally:
        if os.path.exists(artifact_path):
            os.unlink(artifact_path)


def test_cleanup_worker_handles_missing_file_idempotently_and_marks_deleted():
    artifact_repo = InMemoryExtractionArtifactRepository()
    missing_path = os.path.join(tempfile.gettempdir(), "artifact-missing-cleanup.jsonl")
    if os.path.exists(missing_path):
        os.unlink(missing_path)

    artifact_repo.add(
        ExtractionArtifact(
            artifact_id="artifact-cleanup-2",
            job_id="extraction-2",
            source_id="source-crm-replica",
            root_object_id="table-customers",
            kind=ExtractionArtifactKind.SAMPLE,
            artifact_format=ExtractionArtifactFormat.JSONL,
            artifact_path=missing_path,
            row_count=1,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status=ExtractionArtifactStatus.EXPIRED,
            expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )

    worker = ExtractionArtifactCleanupWorker(
        cleanup=ExtractionArtifactCleanupService(
            artifacts=artifact_repo,
            clock=FakeClock(),
        ),
        artifacts=artifact_repo,
        clock=FakeClock(),
    )

    summary = worker.run_once()
    stored = artifact_repo.get_by_id("artifact-cleanup-2")

    assert summary["evaluatedArtifactCount"] == 1
    assert summary["deletedArtifactCount"] == 1
    assert summary["missingFileCount"] == 1
    assert summary["failedArtifactCount"] == 0
    assert stored is not None
    assert stored.status == ExtractionArtifactStatus.DELETED
    assert stored.deleted_at is not None
