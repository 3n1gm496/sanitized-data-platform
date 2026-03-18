from __future__ import annotations

from datetime import timedelta

from sanitized_data_platform.application.ports import (
    AuditEventRepository,
    ClockPort,
    ExtractionArtifactRepository,
    ExtractionJobRepository,
    ExtractionPipelinePort,
    ExtractionPlanSnapshotRepository,
    ExtractionQueuePort,
    IdGeneratorPort,
    LineageRepository,
    ValidationRepository,
)
from sanitized_data_platform.application.services import (
    ExtractionArtifactLifecycleService,
    LineageRecordingService,
    ValidationLookupService,
)
from sanitized_data_platform.domain.entities import AuditEvent, ExtractionArtifact
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import (
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    ExtractionJobStatus,
)


class ExtractionWorker:
    def __init__(
        self,
        *,
        queue: ExtractionQueuePort,
        jobs: ExtractionJobRepository,
        artifacts: ExtractionArtifactRepository,
        plan_snapshots: ExtractionPlanSnapshotRepository,
        pipeline: ExtractionPipelinePort,
        audits: AuditEventRepository,
        lineage: LineageRepository,
        validations: ValidationRepository,
        clock: ClockPort,
        ids: IdGeneratorPort,
        artifact_retention: timedelta = timedelta(hours=24),
    ) -> None:
        self._queue = queue
        self._jobs = jobs
        self._artifacts = artifacts
        self._plan_snapshots = plan_snapshots
        self._pipeline = pipeline
        self._audits = audits
        self._artifact_lifecycle = ExtractionArtifactLifecycleService(
            artifacts=artifacts,
            clock=clock,
            default_retention=artifact_retention,
        )
        self._lineage = LineageRecordingService(
            lineage=lineage,
            validations=ValidationLookupService(validations),
            clock=clock,
            ids=ids,
        )
        self._clock = clock
        self._ids = ids

    def process_next_job(self) -> str | None:
        job_id = self._queue.dequeue()
        if job_id is None:
            return None

        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Queued extraction job not found: {job_id}")

        try:
            running_time = self._clock.now()
            self._queue.heartbeat(job.job_id)
            job = job.transition_to(ExtractionJobStatus.RUNNING, updated_at=running_time)
            self._jobs.save(job)
            self._record_event(job.job_id, "extraction_job_started", job.requested_by, running_time)

            plan_snapshot = self._plan_snapshots.get_by_id(job.plan_snapshot_id)
            if plan_snapshot is None:
                raise DomainError(
                    f"Extraction plan snapshot not found for job {job.job_id}: {job.plan_snapshot_id}"
                )
            plan = plan_snapshot.to_plan()
            summary = self._pipeline.execute(job=job, plan=plan)
            artifact = self._record_artifact(job=job, summary=summary)
            artifact_id = None if artifact is None else artifact.artifact_id

            completed_time = self._clock.now()
            job = job.transition_to(
                ExtractionJobStatus.COMPLETED,
                updated_at=completed_time,
                execution_summary=summary,
                extraction_artifact_id=artifact_id,
            )
            self._jobs.save(job)
            self._lineage.record_extraction_completion(
                job=job,
                plan=plan,
                plan_snapshot=plan_snapshot,
            )
            if artifact is not None:
                self._lineage.record_extraction_artifact_materialization(
                    job=job,
                    artifact=artifact,
                )
            self._record_event(
                job.job_id,
                "extraction_job_completed",
                job.requested_by,
                completed_time,
                details=summary,
            )
            self._queue.complete(job.job_id)
        except Exception as exc:
            failed_time = self._clock.now()
            failed_job = job.transition_to(
                ExtractionJobStatus.FAILED,
                updated_at=failed_time,
                execution_summary={"error": str(exc)},
            )
            self._jobs.save(failed_job)
            self._record_event(
                failed_job.job_id,
                "extraction_job_failed",
                failed_job.requested_by,
                failed_time,
                details={"error": str(exc)},
            )
            self._queue.complete(failed_job.job_id)
            raise

        return job.job_id

    def _record_artifact(
        self,
        *,
        job,
        summary: dict[str, object],
    ) -> ExtractionArtifact | None:
        artifact_path = summary.get("artifactPath")
        artifact_format = summary.get("artifactFormat")
        if not isinstance(artifact_path, str) or not artifact_path:
            return None
        if not isinstance(artifact_format, str):
            return None
        if artifact_format.lower() != ExtractionArtifactFormat.JSONL.value:
            raise DomainError(f"Unsupported extraction artifact format: {artifact_format}")
        row_count = summary.get("materializedRowCount", summary.get("rowSampleCount", 0))
        if not isinstance(row_count, int):
            raise DomainError("Extraction artifact row count must be an integer.")
        file_size_bytes = summary.get("artifactFileSizeBytes")
        if file_size_bytes is not None and not isinstance(file_size_bytes, int):
            raise DomainError("Extraction artifact file size must be an integer when provided.")
        checksum = summary.get("artifactChecksum")
        if checksum is not None and not isinstance(checksum, str):
            raise DomainError("Extraction artifact checksum must be a string when provided.")
        column_count = summary.get("artifactColumnCount")
        if column_count is not None and not isinstance(column_count, int):
            raise DomainError("Extraction artifact column count must be an integer when provided.")
        artifact_kind = summary.get("artifactKind", ExtractionArtifactKind.SAMPLE.value)
        if not isinstance(artifact_kind, str):
            raise DomainError("Extraction artifact kind must be a string when provided.")
        try:
            parsed_artifact_kind = ExtractionArtifactKind(artifact_kind.lower())
        except ValueError as exc:
            raise DomainError(
                f"Unsupported extraction artifact kind: {artifact_kind}"
            ) from exc

        artifact = ExtractionArtifact(
            artifact_id=self._ids.new_id("extraction-artifact"),
            job_id=job.job_id,
            source_id=job.source_id,
            root_object_id=job.root_object_id,
            kind=parsed_artifact_kind,
            artifact_format=ExtractionArtifactFormat.JSONL,
            artifact_path=artifact_path,
            row_count=row_count,
            created_at=self._clock.now(),
            file_size_bytes=file_size_bytes,
            checksum=checksum,
            column_count=column_count,
        )
        artifact = self._artifact_lifecycle.attach_default_expiration(artifact)
        self._artifacts.add(artifact)
        return artifact

    def _record_event(
        self,
        job_id: str,
        event_type: str,
        actor: str,
        created_at,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self._audits.add(
            AuditEvent(
                event_id=self._ids.new_id("audit"),
                event_type=event_type,
                actor=actor,
                subject_type="extraction_job",
                subject_id=job_id,
                details=details or {},
                created_at=created_at,
            )
        )
