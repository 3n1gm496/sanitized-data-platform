from __future__ import annotations

from sanitized_data_platform.domain.entities import AuditEvent, PublishJob
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import JobStatus

from .dto import CreatePublishJobCommand, JobView, SystemSummary
from .ports import (
    AuditEventRepository,
    ClockPort,
    DataSourceRepository,
    DatasetProfileRepository,
    IdGeneratorPort,
    JobQueuePort,
    PolicyPort,
    PublishJobRepository,
    TargetEnvironmentRepository,
)


class CatalogQueryService:
    def __init__(
        self,
        data_sources: DataSourceRepository,
        environments: TargetEnvironmentRepository,
        dataset_profiles: DatasetProfileRepository,
    ) -> None:
        self._data_sources = data_sources
        self._environments = environments
        self._dataset_profiles = dataset_profiles

    def list_systems(self) -> list[SystemSummary]:
        active_profiles = self._dataset_profiles.list_active()
        summaries: list[SystemSummary] = []

        for source in self._data_sources.list_active():
            profile_count = sum(
                1
                for profile in active_profiles
                if profile.system_name == source.system_name
            )
            summaries.append(
                SystemSummary(
                    system_id=source.system_name.lower(),
                    name=source.system_name,
                    source_engine=source.engine_type,
                    available_profiles=profile_count,
                )
            )

        return summaries

    def list_environments(self):
        return self._environments.list_active()

    def list_dataset_profiles(
        self,
        *,
        source_id: str | None = None,
        target_environment_id: str | None = None,
    ):
        profiles = self._dataset_profiles.list_active()

        if source_id is None and target_environment_id is None:
            return profiles

        source = (
            self._data_sources.get_by_id(source_id) if source_id is not None else None
        )
        target = (
            self._environments.get_by_id(target_environment_id)
            if target_environment_id is not None
            else None
        )

        filtered = []
        for profile in profiles:
            if source is not None and profile.system_name != source.system_name:
                continue
            if (
                target is not None
                and profile.target_environment_type != target.environment_type
            ):
                continue
            filtered.append(profile)

        return filtered


class PublishRequestService:
    def __init__(
        self,
        *,
        data_sources: DataSourceRepository,
        environments: TargetEnvironmentRepository,
        dataset_profiles: DatasetProfileRepository,
        jobs: PublishJobRepository,
        audits: AuditEventRepository,
        queue: JobQueuePort,
        policy: PolicyPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._data_sources = data_sources
        self._environments = environments
        self._dataset_profiles = dataset_profiles
        self._jobs = jobs
        self._audits = audits
        self._queue = queue
        self._policy = policy
        self._clock = clock
        self._ids = ids

    def create_job(self, command: CreatePublishJobCommand) -> JobView:
        source = self._require_active_source(command.source_id)
        target = self._require_active_target(command.target_environment_id)
        profile = self._require_active_profile(command.dataset_profile_id)

        if profile.system_name != source.system_name:
            raise DomainError("Dataset profile does not belong to the selected system.")
        if profile.target_environment_type != target.environment_type:
            raise DomainError(
                "Dataset profile is not approved for the selected target environment."
            )
        if source.engine_type != target.engine_type:
            raise DomainError(
                "Source and target database engines must match in the first implementation."
            )

        self._policy.assert_publish_allowed(
            source=source,
            target=target,
            profile=profile,
            requested_by=command.requested_by,
        )

        now = self._clock.now()
        job = PublishJob.create(
            job_id=self._ids.new_id("job"),
            source_id=source.source_id,
            target_environment_id=target.environment_id,
            dataset_profile_id=profile.profile_id,
            requested_by=command.requested_by,
            created_at=now,
        )
        self._jobs.add(job)
        self._queue.enqueue(job.job_id)

        self._audits.add(
            AuditEvent(
                event_id=self._ids.new_id("audit"),
                event_type="publish_job_requested",
                actor=command.requested_by,
                subject_type="publish_job",
                subject_id=job.job_id,
                details={
                    "sourceId": source.source_id,
                    "targetEnvironmentId": target.environment_id,
                    "datasetProfileId": profile.profile_id,
                },
                created_at=now,
            )
        )
        return JobView.from_job(job)

    def get_job(self, job_id: str) -> JobView:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Unknown publish job: {job_id}")
        return JobView.from_job(job)

    def _require_active_source(self, source_id: str):
        source = self._data_sources.get_by_id(source_id)
        if source is None or not source.active:
            raise DomainError(f"Unknown or inactive source: {source_id}")
        return source

    def _require_active_target(self, environment_id: str):
        target = self._environments.get_by_id(environment_id)
        if target is None or not target.active:
            raise DomainError(f"Unknown or inactive target environment: {environment_id}")
        return target

    def _require_active_profile(self, profile_id: str):
        profile = self._dataset_profiles.get_by_id(profile_id)
        if profile is None or not profile.active:
            raise DomainError(f"Unknown or inactive dataset profile: {profile_id}")
        return profile


class JobMonitoringService:
    def __init__(
        self,
        jobs: PublishJobRepository,
        audits: AuditEventRepository,
    ) -> None:
        self._jobs = jobs
        self._audits = audits

    def get_job(self, job_id: str) -> JobView:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Unknown publish job: {job_id}")
        return JobView.from_job(job)

    def list_audit_events(self, subject_id: str):
        return self._audits.list_for_subject(subject_id)
