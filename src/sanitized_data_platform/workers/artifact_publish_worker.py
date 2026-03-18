from __future__ import annotations

from sanitized_data_platform.application.ports import (
    ArtifactPublishJobRepository,
    ArtifactPublishPipelinePort,
    ArtifactPublishQueuePort,
    AuditEventRepository,
    ClockPort,
    ExtractionArtifactRepository,
    IdGeneratorPort,
    LineageRepository,
    TargetEnvironmentRepository,
    ValidationRepository,
)
from sanitized_data_platform.application.services import (
    ExtractionArtifactLifecycleService,
    LineageRecordingService,
    ValidationLookupService,
)
from sanitized_data_platform.domain.entities import AuditEvent
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import JobStatus


class ArtifactPublishWorker:
    def __init__(
        self,
        *,
        queue: ArtifactPublishQueuePort,
        jobs: ArtifactPublishJobRepository,
        artifacts: ExtractionArtifactRepository,
        environments: TargetEnvironmentRepository,
        pipeline: ArtifactPublishPipelinePort,
        audits: AuditEventRepository,
        lineage: LineageRepository,
        validations: ValidationRepository,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._queue = queue
        self._jobs = jobs
        self._artifacts = artifacts
        self._environments = environments
        self._pipeline = pipeline
        self._audits = audits
        self._clock = clock
        self._ids = ids
        self._artifact_lifecycle = ExtractionArtifactLifecycleService(
            artifacts=artifacts,
            clock=clock,
        )
        self._lineage = LineageRecordingService(
            lineage=lineage,
            validations=ValidationLookupService(validations),
            clock=clock,
            ids=ids,
        )

    def process_next_job(self) -> str | None:
        job_id = self._queue.dequeue()
        if job_id is None:
            return None

        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Queued artifact publish job not found: {job_id}")

        artifact = self._artifacts.get_by_id(job.extraction_artifact_id)
        target = self._environments.get_by_id(job.target_environment_id)
        if artifact is None or target is None:
            raise DomainError("Artifact publish job references a missing artifact or target.")
        artifact = self._artifact_lifecycle.evaluate_availability(artifact)
        if not artifact.is_available:
            raise DomainError(
                f"Extraction artifact is not available for publish: {artifact.artifact_id}"
            )

        try:
            started_at = self._clock.now()
            self._queue.heartbeat(job.job_id)
            job = job.transition_to(JobStatus.PUBLISHING, updated_at=started_at)
            self._jobs.save(job)
            self._record_event(
                job.job_id,
                "artifact_publish_job_started",
                job.requested_by,
                started_at,
            )

            summary = self._pipeline.execute(
                job=job,
                artifact=artifact,
                target=target,
            )

            completed_at = self._clock.now()
            job = job.transition_to(
                JobStatus.COMPLETED,
                updated_at=completed_at,
                execution_summary=summary,
            )
            self._jobs.save(job)
            self._lineage.record_artifact_publish_completion(
                job=job,
                artifact=artifact,
            )
            self._record_event(
                job.job_id,
                "artifact_publish_job_completed",
                job.requested_by,
                completed_at,
                details=summary,
            )
            self._queue.complete(job.job_id)
        except Exception as exc:
            failed_at = self._clock.now()
            failed_job = job.transition_to(
                JobStatus.FAILED,
                updated_at=failed_at,
                execution_summary={"error": str(exc)},
            )
            self._jobs.save(failed_job)
            self._record_event(
                failed_job.job_id,
                "artifact_publish_job_failed",
                failed_job.requested_by,
                failed_at,
                details={"error": str(exc)},
            )
            self._queue.complete(failed_job.job_id)
            raise

        return job.job_id

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
                subject_type="artifact_publish_job",
                subject_id=job_id,
                details=details or {},
                created_at=created_at,
            )
        )
