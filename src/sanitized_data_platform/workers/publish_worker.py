from __future__ import annotations

from sanitized_data_platform.application.ports import (
    AuditEventRepository,
    ClockPort,
    DataSourceRepository,
    DatasetProfileRepository,
    IdGeneratorPort,
    JobQueuePort,
    PublishJobRepository,
    PublishPipelinePort,
    TargetEnvironmentRepository,
)
from sanitized_data_platform.domain.entities import AuditEvent
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import JobStatus


class PublishWorker:
    def __init__(
        self,
        *,
        queue: JobQueuePort,
        jobs: PublishJobRepository,
        data_sources: DataSourceRepository,
        environments: TargetEnvironmentRepository,
        dataset_profiles: DatasetProfileRepository,
        pipeline: PublishPipelinePort,
        audits: AuditEventRepository,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._queue = queue
        self._jobs = jobs
        self._data_sources = data_sources
        self._environments = environments
        self._dataset_profiles = dataset_profiles
        self._pipeline = pipeline
        self._audits = audits
        self._clock = clock
        self._ids = ids

    def process_next_job(self) -> str | None:
        job_id = self._queue.dequeue()
        if job_id is None:
            return None

        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Queued publish job not found: {job_id}")

        source = self._data_sources.get_by_id(job.source_id)
        target = self._environments.get_by_id(job.target_environment_id)
        profile = self._dataset_profiles.get_by_id(job.dataset_profile_id)
        if source is None or target is None or profile is None:
            raise DomainError("Publish job references missing source, target, or profile.")

        try:
            planning_time = self._clock.now()
            job = job.transition_to(JobStatus.PLANNING, updated_at=planning_time)
            self._jobs.save(job)
            self._record_event(job.job_id, "publish_job_started", job.requested_by, planning_time)

            summary = self._pipeline.execute(
                job=job,
                source=source,
                target=target,
                profile=profile,
            )

            completed_time = self._clock.now()
            job = job.transition_to(
                JobStatus.COMPLETED,
                updated_at=completed_time,
                execution_summary=summary,
            )
            self._jobs.save(job)
            self._record_event(
                job.job_id,
                "publish_job_completed",
                job.requested_by,
                completed_time,
                details=summary,
            )
        except Exception as exc:
            failed_time = self._clock.now()
            failed_job = job.transition_to(
                JobStatus.FAILED,
                updated_at=failed_time,
                execution_summary={"error": str(exc)},
            )
            self._jobs.save(failed_job)
            self._record_event(
                failed_job.job_id,
                "publish_job_failed",
                failed_job.requested_by,
                failed_time,
                details={"error": str(exc)},
            )
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
                subject_type="publish_job",
                subject_id=job_id,
                details=details or {},
                created_at=created_at,
            )
        )
