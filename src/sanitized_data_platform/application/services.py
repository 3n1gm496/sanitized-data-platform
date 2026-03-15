from __future__ import annotations

from sanitized_data_platform.domain.entities import (
    AuditEvent,
    DataSource,
    PolicyCoverageGap,
    PolicyCoverageReport,
    PublishJob,
    SanitizedBaseline,
)
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import (
    MetadataObjectType,
    PolicyCoverageSeverity,
)

from .dto import (
    CreatePublishJobCommand,
    JobView,
    MetadataCatalogView,
    MetadataObjectView,
    PolicyCoverageReportView,
    PolicyListingView,
    SystemSummary,
    TransformationPolicyView,
)
from .ports import (
    AuditEventRepository,
    BaselineRepository,
    ClassificationRepository,
    ClockPort,
    DataSourceRepository,
    DatasetProfileRepository,
    IdGeneratorPort,
    JobQueuePort,
    MetadataCatalogRepository,
    PolicyPort,
    PublishJobRepository,
    SystemRepository,
    TargetEnvironmentRepository,
    TransformationPolicyRepository,
)


class CatalogQueryService:
    def __init__(
        self,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        environments: TargetEnvironmentRepository,
        dataset_profiles: DatasetProfileRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._environments = environments
        self._dataset_profiles = dataset_profiles

    def list_systems(self) -> list[SystemSummary]:
        active_profiles = self._dataset_profiles.list_active()
        summaries: list[SystemSummary] = []

        for system in self._systems.list_active():
            source = self._data_sources.get_active_by_system_id(system.system_id)
            if source is None:
                continue
            profile_count = sum(
                1
                for profile in active_profiles
                if profile.system_id == system.system_id
            )
            summaries.append(
                SystemSummary(
                    system_id=system.system_id,
                    name=system.name,
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
            if source is not None and profile.system_id != source.system_id:
                continue
            if (
                target is not None
                and profile.target_environment_type != target.environment_type
            ):
                continue
            filtered.append(profile)

        return filtered


def resolve_active_source_for_system(
    systems: SystemRepository,
    data_sources: DataSourceRepository,
    system_id: str,
) -> DataSource:
    system = systems.get_by_id(system_id)
    if system is None or not system.active:
        raise DomainError(f"Unknown system: {system_id}")
    source = data_sources.get_active_by_system_id(system_id)
    if source is not None:
        return source
    raise DomainError(f"No active source configured for system: {system_id}")


def resolve_active_system(
    systems: SystemRepository,
    system_id: str,
):
    system = systems.get_by_id(system_id)
    if system is None or not system.active:
        raise DomainError(f"Unknown system: {system_id}")
    return system


class MetadataQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        metadata_catalog: MetadataCatalogRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._metadata_catalog = metadata_catalog

    def list_metadata_objects(self, system_id: str) -> MetadataCatalogView:
        system = resolve_active_system(self._systems, system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            system_id,
        )
        objects = [
            MetadataObjectView.from_metadata_object(item)
            for item in self._metadata_catalog.list_objects(source.source_id)
            if item.active
        ]
        return MetadataCatalogView(
            system_id=source.system_id,
            system_name=system.name,
            source_id=source.source_id,
            items=objects,
        )


class PolicyQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        policies: TransformationPolicyRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._policies = policies

    def list_transformation_policies(
        self,
        *,
        system_id: str | None = None,
        object_name: str | None = None,
        column_name: str | None = None,
    ) -> PolicyListingView:
        filters = {
            key: value
            for key, value in {
                "systemId": system_id,
                "objectName": object_name,
                "columnName": column_name,
            }.items()
            if value is not None
        }

        if system_id is None:
            policies = []
            for system in self._systems.list_active():
                policies.extend(self._policies.list_active_for_system(system.system_id))
        else:
            resolve_active_system(self._systems, system_id)
            policies = self._policies.list_active_for_system(system_id)

        if object_name is not None:
            policies = [policy for policy in policies if policy.object_name == object_name]
        if column_name is not None:
            policies = [policy for policy in policies if policy.column_name == column_name]

        return PolicyListingView(
            filters=filters,
            items=[TransformationPolicyView.from_policy(policy) for policy in policies],
        )


class PolicyCoverageEvaluationService:
    def __init__(
        self,
        *,
        metadata_catalog: MetadataCatalogRepository,
        policies: TransformationPolicyRepository,
        classifications: ClassificationRepository,
        clock: ClockPort,
    ) -> None:
        self._metadata_catalog = metadata_catalog
        self._policies = policies
        self._classifications = classifications
        self._clock = clock

    def evaluate_for_source(self, source: DataSource) -> PolicyCoverageReport:
        columns = [
            item
            for item in self._metadata_catalog.list_objects(
                source.source_id,
                object_type=MetadataObjectType.COLUMN,
            )
            if item.active
        ]
        tags_by_object_id: dict[str, list] = {}
        for tag in self._classifications.list_sensitivity_tags(source.source_id):
            if not tag.active or not tag.approved:
                continue
            tags_by_object_id.setdefault(tag.object_id, []).append(tag)

        policies = self._policies.list_active_for_system(source.system_id)
        gaps: list[PolicyCoverageGap] = []
        covered_object_count = 0

        for column in columns:
            tags = tags_by_object_id.get(column.object_id, [])
            if not tags:
                gaps.append(
                    PolicyCoverageGap(
                        gap_type="missing_classification",
                        metadata_object_id=column.object_id,
                        object_name=column.qualified_name,
                        message="Column has no approved sensitivity classification yet.",
                        severity=PolicyCoverageSeverity.INFORMATIONAL,
                    )
                )
                continue

            if any(policy.active and policy.applies_to(column, tags) for policy in policies):
                covered_object_count += 1
                continue

            gaps.append(
                PolicyCoverageGap(
                    gap_type="missing_transformation_policy",
                    metadata_object_id=column.object_id,
                    object_name=column.qualified_name,
                    message="Sensitive column has no matching transformation policy.",
                    severity=PolicyCoverageSeverity.BLOCKING,
                    sensitivity_tags=tuple(tag.tag_name for tag in tags),
                )
            )

        return PolicyCoverageReport(
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            evaluated_object_count=len(columns),
            covered_object_count=covered_object_count,
            gaps=tuple(gaps),
            evaluated_at=self._clock.now(),
        )


class PublishReadinessValidationService:
    def __init__(self, coverage: PolicyCoverageEvaluationService) -> None:
        self._coverage = coverage

    def assert_publish_ready(self, source: DataSource) -> PolicyCoverageReport:
        report = self._coverage.evaluate_for_source(source)
        if report.blocking_gaps:
            object_names = ", ".join(gap.object_name for gap in report.blocking_gaps[:3])
            raise DomainError(
                "Publish readiness failed because blocking policy coverage gaps exist"
                f" for: {object_names}."
            )
        return report


class BaselineLookupService:
    def __init__(self, baselines: BaselineRepository) -> None:
        self._baselines = baselines

    def list_active_for_system(self, system_id: str) -> list[SanitizedBaseline]:
        return [
            baseline
            for baseline in self._baselines.list_active_for_system(system_id)
            if baseline.is_selectable
        ]


class BaselineSelectionService:
    def __init__(self, baselines: BaselineRepository) -> None:
        self._baselines = baselines

    def select_for_publish(
        self,
        *,
        source: DataSource,
        target,
        profile,
    ) -> SanitizedBaseline:
        candidates = self._baselines.list_active_for_system(source.system_id)
        compatible = [
            baseline
            for baseline in candidates
            if baseline.is_compatible_with(
                source=source,
                target=target,
                profile=profile,
            )
        ]
        if not compatible:
            raise DomainError(
                "No compatible active sanitized baseline is available for the selected"
                " system, profile, and target environment."
            )
        compatible.sort(key=lambda baseline: baseline.refreshed_at, reverse=True)
        return compatible[0]


class PublishSourceResolutionService:
    def __init__(self, baseline_selection: BaselineSelectionService) -> None:
        self._baseline_selection = baseline_selection

    def resolve_for_publish(
        self,
        *,
        source: DataSource,
        target,
        profile,
    ) -> SanitizedBaseline | None:
        if not profile.uses_sanitized_baseline:
            return None
        return self._baseline_selection.select_for_publish(
            source=source,
            target=target,
            profile=profile,
        )


class PolicyCoverageQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        coverage: PolicyCoverageEvaluationService,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._coverage = coverage

    def get_policy_coverage(self, system_id: str) -> PolicyCoverageReportView:
        resolve_active_system(self._systems, system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            system_id,
        )
        report = self._coverage.evaluate_for_source(source)
        return PolicyCoverageReportView.from_report(report)


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
        readiness: PublishReadinessValidationService,
        publish_source_resolution: PublishSourceResolutionService,
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
        self._readiness = readiness
        self._publish_source_resolution = publish_source_resolution
        self._clock = clock
        self._ids = ids

    def create_job(self, command: CreatePublishJobCommand) -> JobView:
        source = self._require_active_source(command.source_id)
        target = self._require_active_target(command.target_environment_id)
        profile = self._require_active_profile(command.dataset_profile_id)

        if profile.system_id != source.system_id:
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
        self._readiness.assert_publish_ready(source)
        selected_baseline = self._publish_source_resolution.resolve_for_publish(
            source=source,
            target=target,
            profile=profile,
        )

        now = self._clock.now()
        job = PublishJob.create(
            job_id=self._ids.new_id("job"),
            source_id=source.source_id,
            sanitized_baseline_id=(
                None if selected_baseline is None else selected_baseline.baseline_id
            ),
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
                    "sanitizedBaselineId": job.sanitized_baseline_id,
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
