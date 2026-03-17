from datetime import datetime, timezone
from datetime import timedelta

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

from tests.fakes import (
    FakeClock,
    InMemoryExtractionArtifactRepository,
    InMemoryExtractionJobRepository,
)


def test_extraction_artifact_query_service_reads_artifact_for_job():
    job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = ExtractionJob.create(
        job_id="extraction-1",
        source_id="source-crm-replica",
        system_id="crm",
        plan_snapshot_id="extraction-plan-snapshot-1",
        root_object_id="table-customers",
        criteria=(),
        include_related=False,
        max_depth=1,
        requested_by="developer@example.internal",
        created_at=created_at,
    ).transition_to(
        status=ExtractionJobStatus.COMPLETED,
        updated_at=created_at,
        extraction_artifact_id="extraction-artifact-1",
    )
    artifact = ExtractionArtifact(
        artifact_id="extraction-artifact-1",
        job_id=job.job_id,
        source_id=job.source_id,
        root_object_id=job.root_object_id,
        kind=ExtractionArtifactKind.SAMPLE,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/extraction-1.jsonl",
        row_count=2,
        created_at=created_at,
        file_size_bytes=128,
        checksum="artifact-checksum-1",
        column_count=2,
    )
    job_repo.add(job)
    artifact_repo.add(artifact)

    lifecycle = ExtractionArtifactLifecycleService(
        artifacts=artifact_repo,
        clock=FakeClock(),
    )
    service = ExtractionArtifactQueryService(
        jobs=job_repo,
        artifacts=artifact_repo,
        lifecycle=lifecycle,
    )
    result = service.get_artifact_for_job("extraction-1")

    assert result.artifact_id == "extraction-artifact-1"
    assert result.job_id == "extraction-1"
    assert result.kind == "sample"
    assert result.artifact_format == "jsonl"
    assert result.file_size_bytes == 128
    assert result.checksum == "artifact-checksum-1"
    assert result.column_count == 2
    assert result.status == "available"
    assert result.available is True


def test_extraction_artifact_query_service_reads_artifact_by_id():
    job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    artifact = ExtractionArtifact(
        artifact_id="extraction-artifact-1",
        job_id="extraction-1",
        source_id="source-crm-replica",
        root_object_id="table-customers",
        kind=ExtractionArtifactKind.FULL,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/extraction-1.jsonl",
        row_count=10,
        created_at=created_at,
        file_size_bytes=256,
        checksum="artifact-checksum-1",
        column_count=3,
    )
    artifact_repo.add(artifact)

    service = ExtractionArtifactQueryService(
        jobs=job_repo,
        artifacts=artifact_repo,
        lifecycle=ExtractionArtifactLifecycleService(
            artifacts=artifact_repo,
            clock=FakeClock(),
        ),
    )
    result = service.get_artifact_by_id("extraction-artifact-1")

    assert result.artifact_id == "extraction-artifact-1"
    assert result.kind == "full"
    assert result.row_count == 10
    assert result.file_size_bytes == 256


def test_extraction_artifact_lifecycle_expires_due_artifacts():
    artifact_repo = InMemoryExtractionArtifactRepository()
    clock = FakeClock()
    created_at = datetime(2025, 12, 31, tzinfo=timezone.utc)
    artifact = ExtractionArtifact(
        artifact_id="extraction-artifact-1",
        job_id="extraction-1",
        source_id="source-crm-replica",
        root_object_id="table-customers",
        kind=ExtractionArtifactKind.SAMPLE,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/extraction-1.jsonl",
        row_count=2,
        created_at=created_at,
        expires_at=datetime(2025, 12, 31, 1, tzinfo=timezone.utc),
    )
    artifact_repo.add(artifact)

    lifecycle = ExtractionArtifactLifecycleService(
        artifacts=artifact_repo,
        clock=clock,
        default_retention=timedelta(hours=24),
    )
    expired_count = lifecycle.expire_due_artifacts()
    stored = artifact_repo.get_by_id("extraction-artifact-1")

    assert expired_count == 1
    assert stored is not None
    assert stored.status == ExtractionArtifactStatus.EXPIRED
    assert stored.is_available is False


def test_extraction_artifact_query_service_surfaces_expired_state():
    job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = ExtractionJob.create(
        job_id="extraction-2",
        source_id="source-crm-replica",
        system_id="crm",
        plan_snapshot_id="extraction-plan-snapshot-2",
        root_object_id="table-customers",
        criteria=(),
        include_related=False,
        max_depth=1,
        requested_by="developer@example.internal",
        created_at=created_at,
    ).transition_to(
        status=ExtractionJobStatus.COMPLETED,
        updated_at=created_at,
        extraction_artifact_id="extraction-artifact-2",
    )
    artifact = ExtractionArtifact(
        artifact_id="extraction-artifact-2",
        job_id=job.job_id,
        source_id=job.source_id,
        root_object_id=job.root_object_id,
        kind=ExtractionArtifactKind.SAMPLE,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/extraction-2.jsonl",
        row_count=1,
        created_at=created_at,
        status=ExtractionArtifactStatus.EXPIRED,
        expires_at=created_at,
    )
    job_repo.add(job)
    artifact_repo.add(artifact)

    service = ExtractionArtifactQueryService(
        jobs=job_repo,
        artifacts=artifact_repo,
        lifecycle=ExtractionArtifactLifecycleService(
            artifacts=artifact_repo,
            clock=FakeClock(),
        ),
    )
    result = service.get_artifact_for_job("extraction-2")

    assert result.artifact_id == "extraction-artifact-2"
    assert result.status == "expired"
    assert result.available is False


def test_extraction_artifact_query_service_surfaces_deleted_state():
    job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deleted_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    job = ExtractionJob.create(
        job_id="extraction-3",
        source_id="source-crm-replica",
        system_id="crm",
        plan_snapshot_id="extraction-plan-snapshot-3",
        root_object_id="table-customers",
        criteria=(),
        include_related=False,
        max_depth=1,
        requested_by="developer@example.internal",
        created_at=created_at,
    ).transition_to(
        status=ExtractionJobStatus.COMPLETED,
        updated_at=created_at,
        extraction_artifact_id="extraction-artifact-3",
    )
    artifact = ExtractionArtifact(
        artifact_id="extraction-artifact-3",
        job_id=job.job_id,
        source_id=job.source_id,
        root_object_id=job.root_object_id,
        kind=ExtractionArtifactKind.SAMPLE,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/extraction-3.jsonl",
        row_count=1,
        created_at=created_at,
        status=ExtractionArtifactStatus.DELETED,
        expires_at=created_at,
        deleted_at=deleted_at,
    )
    job_repo.add(job)
    artifact_repo.add(artifact)

    service = ExtractionArtifactQueryService(
        jobs=job_repo,
        artifacts=artifact_repo,
        lifecycle=ExtractionArtifactLifecycleService(
            artifacts=artifact_repo,
            clock=FakeClock(),
        ),
    )
    result = service.get_artifact_for_job("extraction-3")

    assert result.artifact_id == "extraction-artifact-3"
    assert result.status == "deleted"
    assert result.available is False
    assert result.deleted_at == deleted_at
