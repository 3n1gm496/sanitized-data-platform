from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sanitized_data_platform.adapters.registry import AdapterRegistry
from sanitized_data_platform.application.services import (
    ArtifactPublishMonitoringService,
    ArtifactPublishRequestService,
    AuditQueryService,
    BaselineEligibilityExplanationService,
    BaselineQueryService,
    BaselineRefreshMonitoringService,
    BaselineRefreshRequestService,
    CatalogQueryService,
    ClassificationQueryService,
    EngineCapabilityQueryService,
    ExtractionArtifactLifecycleService,
    ExtractionArtifactQueryService,
    ExtractionJobMonitoringService,
    ExtractionJobRequestService,
    ExtractionPlanPreviewService,
    ExtractionPlanSnapshotQueryService,
    ExtractionPlanningService,
    GovernanceSummaryQueryService,
    JobMonitoringService,
    LineageQueryService,
    MetadataQueryService,
    PolicyCoverageEvaluationService,
    PolicyCoverageQueryService,
    PolicyQueryService,
    PublishReadinessValidationService,
    PublishRequestService,
    PublishSourceResolutionService,
    PublishValidationSummaryService,
    RefreshScheduleService,
    RelationshipQueryService,
    ValidationLookupService,
    ValidationQueryService,
    BaselineSelectionService,
    BaselineStorageReadinessService,
    BaselineValidationEligibilityService,
)
from sanitized_data_platform.domain.entities import (
    ArtifactPublishJob,
    AuditEvent,
    BaselineRefreshJob,
    BaselineRefreshSchedule,
    BaselineTableAsset,
    DataSource,
    DatasetProfile,
    ExtractionArtifact,
    ExtractionJob,
    ExtractionPlanSnapshot,
    LineageRecord,
    MetadataObject,
    PublishJob,
    Relationship,
    SanitizedBaseline,
    SelectionCriteria,
    SensitivityTag,
    System,
    TargetEnvironment,
    TransformationPolicy,
    ValidationCheckResult,
    ValidationReport,
)
from sanitized_data_platform.domain.enums import (
    BaselineRefreshStatus,
    BaselineStatus,
    ClassificationStatus,
    DatabaseEngine,
    DatasetMode,
    EnvironmentType,
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    ExtractionJobStatus,
    MetadataObjectType,
    RefreshScheduleStatus,
    TransformationType,
    ValidationSeverity,
    ValidationStatus,
)
from sanitized_data_platform.interfaces.api.app import ApiApp
from sanitized_data_platform.interfaces.http.fastapi_app import create_fastapi_app


@dataclass(frozen=True, slots=True)
class DemoRuntime:
    api_app: ApiApp
    ready_probe: Callable[[], dict[str, object]]
    metrics_provider: Callable[[], dict[str, object]]


class DemoClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)

    def now(self) -> datetime:
        current = self._current
        self._current = current + timedelta(minutes=1)
        return current


class SequentialIdGenerator:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]}"


class InMemorySystemRepository:
    def __init__(self, items: list[System]) -> None:
        self._items = {item.system_id: item for item in items}

    def list_active(self) -> list[System]:
        return [item for item in self._items.values() if item.active]

    def get_by_id(self, system_id: str) -> System | None:
        return self._items.get(system_id)


class InMemoryDataSourceRepository:
    def __init__(self, items: list[DataSource]) -> None:
        self._items = {item.source_id: item for item in items}

    def list_active(self) -> list[DataSource]:
        return [item for item in self._items.values() if item.active]

    def get_by_id(self, source_id: str) -> DataSource | None:
        return self._items.get(source_id)

    def get_active_by_system_id(self, system_id: str) -> DataSource | None:
        for item in self._items.values():
            if item.system_id == system_id and item.active:
                return item
        return None


class InMemoryTargetEnvironmentRepository:
    def __init__(self, items: list[TargetEnvironment]) -> None:
        self._items = {item.environment_id: item for item in items}

    def list_active(self) -> list[TargetEnvironment]:
        return [item for item in self._items.values() if item.active]

    def get_by_id(self, environment_id: str) -> TargetEnvironment | None:
        return self._items.get(environment_id)


class InMemoryDatasetProfileRepository:
    def __init__(self, items: list[DatasetProfile]) -> None:
        self._items = {item.profile_id: item for item in items}

    def list_active(self) -> list[DatasetProfile]:
        return [item for item in self._items.values() if item.active]

    def get_by_id(self, profile_id: str) -> DatasetProfile | None:
        return self._items.get(profile_id)


class InMemoryBaselineRepository:
    def __init__(self, items: list[SanitizedBaseline]) -> None:
        self._items = {item.baseline_id: item for item in items}

    def list_active_for_system(self, system_id: str) -> list[SanitizedBaseline]:
        return [item for item in self._items.values() if item.system_id == system_id and item.active]

    def list_for_system(self, system_id: str) -> list[SanitizedBaseline]:
        return [item for item in self._items.values() if item.system_id == system_id]

    def get_by_id(self, baseline_id: str) -> SanitizedBaseline | None:
        return self._items.get(baseline_id)

    def add(self, baseline: SanitizedBaseline) -> None:
        self._items[baseline.baseline_id] = baseline

    def save(self, baseline: SanitizedBaseline) -> None:
        self._items[baseline.baseline_id] = baseline


class InMemoryBaselineAssetRepository:
    def __init__(self, items: list[BaselineTableAsset] | None = None) -> None:
        self._items: dict[str, list[BaselineTableAsset]] = {}
        for item in items or []:
            self._items.setdefault(item.baseline_id, []).append(item)

    def list_for_baseline(self, baseline_id: str) -> list[BaselineTableAsset]:
        return list(self._items.get(baseline_id, []))

    def replace_for_baseline(self, baseline_id: str, assets: list[BaselineTableAsset]) -> None:
        self._items[baseline_id] = list(assets)


class InMemoryValidationRepository:
    def __init__(self, items: list[ValidationReport]) -> None:
        self._items = {item.baseline_id: item for item in items}

    def get_latest_for_baseline(self, baseline_id: str) -> ValidationReport | None:
        return self._items.get(baseline_id)


class InMemoryMetadataCatalogRepository:
    def __init__(self, objects: list[MetadataObject], relationships: list[Relationship] | None = None) -> None:
        self._objects = {item.object_id: item for item in objects}
        self._relationships = {item.relationship_id: item for item in (relationships or [])}

    def list_objects(self, source_id: str, *, object_type=None) -> list[MetadataObject]:
        items = [item for item in self._objects.values() if item.source_id == source_id]
        if object_type is not None:
            items = [item for item in items if item.object_type == object_type]
        return items

    def upsert_objects(self, objects: list[MetadataObject]) -> None:
        for item in objects:
            self._objects[item.object_id] = item

    def upsert_relationships(self, relationships: list[Relationship]) -> None:
        for item in relationships:
            self._relationships[item.relationship_id] = item

    def list_relationships(self, source_id: str) -> list[Relationship]:
        return [item for item in self._relationships.values() if item.source_id == source_id]


class InMemoryTransformationPolicyRepository:
    def __init__(self, items: list[TransformationPolicy]) -> None:
        self._items = list(items)

    def list_active_for_system(self, system_id: str) -> list[TransformationPolicy]:
        return [item for item in self._items if item.system_id == system_id and item.active]


class InMemoryClassificationRepository:
    def __init__(self, tags: list[SensitivityTag]) -> None:
        self._tags = list(tags)

    def list_sensitivity_tags(self, source_id: str) -> list[SensitivityTag]:
        return [tag for tag in self._tags if tag.source_id == source_id]


class InMemoryPublishJobRepository:
    def __init__(self, items: list[PublishJob] | None = None) -> None:
        self._items = {item.job_id: item for item in items or []}

    def add(self, job: PublishJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> PublishJob | None:
        return self._items.get(job_id)

    def list_all(self) -> list[PublishJob]:
        return list(self._items.values())

    def save(self, job: PublishJob) -> None:
        self._items[job.job_id] = job


class InMemoryArtifactPublishJobRepository:
    def __init__(self, items: list[ArtifactPublishJob] | None = None) -> None:
        self._items = {item.job_id: item for item in items or []}

    def add(self, job: ArtifactPublishJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> ArtifactPublishJob | None:
        return self._items.get(job_id)

    def list_all(self) -> list[ArtifactPublishJob]:
        return list(self._items.values())

    def save(self, job: ArtifactPublishJob) -> None:
        self._items[job.job_id] = job


class InMemoryBaselineRefreshJobRepository:
    def __init__(self, items: list[BaselineRefreshJob] | None = None) -> None:
        self._items = {item.job_id: item for item in items or []}

    def add(self, job: BaselineRefreshJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> BaselineRefreshJob | None:
        return self._items.get(job_id)

    def list_all(self) -> list[BaselineRefreshJob]:
        return list(self._items.values())

    def save(self, job: BaselineRefreshJob) -> None:
        self._items[job.job_id] = job


class InMemoryBaselineRefreshScheduleRepository:
    def __init__(self, items: list[BaselineRefreshSchedule] | None = None) -> None:
        self._items = {item.schedule_id: item for item in items or []}

    def add(self, schedule: BaselineRefreshSchedule) -> None:
        self._items[schedule.schedule_id] = schedule

    def get_by_id(self, schedule_id: str) -> BaselineRefreshSchedule | None:
        return self._items.get(schedule_id)

    def list_all(self) -> list[BaselineRefreshSchedule]:
        return list(self._items.values())

    def list_enabled(self) -> list[BaselineRefreshSchedule]:
        return [item for item in self._items.values() if item.enabled]

    def save(self, schedule: BaselineRefreshSchedule) -> None:
        self._items[schedule.schedule_id] = schedule


class InMemoryExtractionJobRepository:
    def __init__(self, items: list[ExtractionJob] | None = None) -> None:
        self._items = {item.job_id: item for item in items or []}

    def add(self, job: ExtractionJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> ExtractionJob | None:
        return self._items.get(job_id)

    def list_all(self) -> list[ExtractionJob]:
        return list(self._items.values())

    def save(self, job: ExtractionJob) -> None:
        self._items[job.job_id] = job


class InMemoryExtractionPlanSnapshotRepository:
    def __init__(self, items: list[ExtractionPlanSnapshot] | None = None) -> None:
        self._items = {item.snapshot_id: item for item in items or []}

    def add(self, snapshot: ExtractionPlanSnapshot) -> None:
        self._items[snapshot.snapshot_id] = snapshot

    def get_by_id(self, snapshot_id: str) -> ExtractionPlanSnapshot | None:
        return self._items.get(snapshot_id)


class InMemoryExtractionArtifactRepository:
    def __init__(self, items: list[ExtractionArtifact] | None = None) -> None:
        self._by_id: dict[str, ExtractionArtifact] = {}
        self._by_job_id: dict[str, ExtractionArtifact] = {}
        for item in items or []:
            self.add(item)

    def add(self, artifact: ExtractionArtifact) -> None:
        self._by_id[artifact.artifact_id] = artifact
        self._by_job_id[artifact.job_id] = artifact

    def get_by_id(self, artifact_id: str) -> ExtractionArtifact | None:
        return self._by_id.get(artifact_id)

    def get_by_job_id(self, job_id: str) -> ExtractionArtifact | None:
        return self._by_job_id.get(job_id)

    def list_all(self) -> list[ExtractionArtifact]:
        return list(self._by_id.values())

    def save(self, artifact: ExtractionArtifact) -> None:
        self.add(artifact)


class InMemoryAuditEventRepository:
    def __init__(self, items: list[AuditEvent] | None = None) -> None:
        self._items = list(items or [])

    def add(self, event: AuditEvent) -> None:
        self._items.append(event)

    def list_for_subject(self, subject_id: str) -> list[AuditEvent]:
        return [event for event in self._items if event.subject_id == subject_id]


class InMemoryLineageRepository:
    def __init__(self, items: list[LineageRecord] | None = None) -> None:
        self._items = list(items or [])

    def add(self, record: LineageRecord) -> None:
        self._items.append(record)

    def list_related(self, *, reference_type: str, reference_id: str) -> list[LineageRecord]:
        return [
            item
            for item in self._items
            if (item.source_type == reference_type and item.source_id == reference_id)
            or (item.target_type == reference_type and item.target_id == reference_id)
        ]


class InMemoryJobQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        self._items.append(job_id)

    def dequeue(self) -> str | None:
        return None if not self._items else self._items.popleft()

    def heartbeat(self, job_id: str) -> None:
        return None

    def complete(self, job_id: str) -> None:
        return None


class InMemoryBaselineRefreshQueue(InMemoryJobQueue):
    pass


class InMemoryExtractionQueue(InMemoryJobQueue):
    pass


class InMemoryArtifactPublishQueue(InMemoryJobQueue):
    pass


class AllowAllPolicy:
    def assert_publish_allowed(self, **kwargs) -> None:
        return None


def _sample_system() -> System:
    return System(system_id="crm", name="CRM")


def _sample_source() -> DataSource:
    return DataSource(
        source_id="source-crm-replica",
        system_id="crm",
        system_name="CRM",
        engine_type=DatabaseEngine.POSTGRES,
        endpoint="postgresql://crm-replica.local",
        database_name="crm",
    )


def _sample_target() -> TargetEnvironment:
    return TargetEnvironment(
        environment_id="env-dev",
        name="Development",
        environment_type=EnvironmentType.DEV,
        engine_type=DatabaseEngine.POSTGRES,
        target_endpoint="postgresql://crm-dev.local",
    )


def _sample_profile() -> DatasetProfile:
    return DatasetProfile(
        profile_id="profile-full-sanitized",
        system_id="crm",
        name="full_sanitized_clone",
        system_name="CRM",
        dataset_mode=DatasetMode.FULL_CLONE,
        target_environment_type=EnvironmentType.DEV,
    )


def _sample_baseline() -> SanitizedBaseline:
    refreshed_at = datetime(2026, 1, 1, 6, tzinfo=timezone.utc)
    return SanitizedBaseline(
        baseline_id="baseline-crm-dev-v1",
        system_id="crm",
        system_name="CRM",
        source_id="source-crm-replica",
        dataset_profile_id="profile-full-sanitized",
        target_environment_type=EnvironmentType.DEV,
        engine_type=DatabaseEngine.POSTGRES,
        version="2026.01.01.1",
        status=BaselineStatus.ACTIVE,
        created_at=refreshed_at,
        refreshed_at=refreshed_at,
    )


def _sample_validation_report() -> ValidationReport:
    return ValidationReport(
        report_id="validation-baseline-crm-dev-v1",
        baseline_id="baseline-crm-dev-v1",
        status=ValidationStatus.PASSED,
        checks=(
            ValidationCheckResult(
                check_name="referential_integrity",
                severity=ValidationSeverity.INFO,
                passed=True,
                message="All checks passed.",
            ),
        ),
        created_at=datetime(2026, 1, 1, 7, tzinfo=timezone.utc),
    )


def _sample_baseline_asset() -> BaselineTableAsset:
    return BaselineTableAsset(
        asset_id="baseline-asset-1",
        baseline_id="baseline-crm-dev-v1",
        source_id="source-crm-replica",
        root_object_id="table:source-crm-replica:public.customers",
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/baseline-asset-1.jsonl",
        row_count=2,
        created_at=datetime(2026, 1, 1, 6, 30, tzinfo=timezone.utc),
        checksum="baseline-asset-checksum-1",
        column_count=2,
        import_order=0,
    )


def _sample_refresh_schedule() -> BaselineRefreshSchedule:
    now = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    return BaselineRefreshSchedule(
        schedule_id="refresh-schedule-1",
        system_id="crm",
        dataset_profile_id="profile-full-sanitized",
        target_environment_type=EnvironmentType.DEV,
        interval_minutes=1440,
        status=RefreshScheduleStatus.ENABLED,
        created_by="steward@example.internal",
        created_at=now,
        updated_at=now,
        next_run_at=now + timedelta(days=1),
        last_dispatched_at=None,
    )


def _sample_metadata_objects() -> list[MetadataObject]:
    source = _sample_source()
    return [
        MetadataObject(
            object_id="table-customers",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="customers",
            qualified_name="crm.customers",
        ),
        MetadataObject(
            object_id="table-orders",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="orders",
            qualified_name="crm.orders",
        ),
        MetadataObject(
            object_id="column-customers-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.customers.customer_id",
            container_name="crm.customers",
            parent_object_id="table-customers",
            logical_data_type="integer",
        ),
        MetadataObject(
            object_id="column-customers-email",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="email",
            qualified_name="crm.customers.email",
            container_name="crm.customers",
            parent_object_id="table-customers",
            logical_data_type="string",
        ),
        MetadataObject(
            object_id="column-customers-status",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="status",
            qualified_name="crm.customers.status",
            container_name="crm.customers",
            parent_object_id="table-customers",
            logical_data_type="string",
        ),
        MetadataObject(
            object_id="column-orders-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.orders.customer_id",
            container_name="crm.orders",
            parent_object_id="table-orders",
            logical_data_type="integer",
        ),
    ]


def _sample_preview_metadata_objects() -> list[MetadataObject]:
    source = _sample_source()
    return [
        MetadataObject(
            object_id="table-customers",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="customers",
            qualified_name="crm.customers",
        ),
        MetadataObject(
            object_id="table-orders",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="orders",
            qualified_name="crm.orders",
        ),
        MetadataObject(
            object_id="column-customers-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.customers.customer_id",
            container_name="crm.customers",
            parent_object_id="table-customers",
            logical_data_type="integer",
        ),
        MetadataObject(
            object_id="column-orders-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.orders.customer_id",
            container_name="crm.orders",
            parent_object_id="table-orders",
            logical_data_type="integer",
        ),
    ]


def _sample_relationships() -> list[Relationship]:
    source = _sample_source()
    return [
        Relationship(
            relationship_id="fk:orders.customer_id->customers.customer_id",
            source_id=source.source_id,
            source_object_id="column-orders-customer-id",
            target_object_id="column-customers-customer-id",
            relationship_type="foreign_key",
            inferred=False,
            confidence=1.0,
        )
    ]


def _sample_sensitivity_tags() -> list[SensitivityTag]:
    source = _sample_source()
    return [
        SensitivityTag(
            tag_id="tag-email",
            source_id=source.source_id,
            object_id="column-customers-email",
            tag_name="pii.email",
            assigned_by="manual-review",
            classification_status=ClassificationStatus.SENSITIVE,
        ),
        SensitivityTag(
            tag_id="tag-status",
            source_id=source.source_id,
            object_id="column-customers-status",
            tag_name="classification.non_sensitive",
            assigned_by="manual-review",
            classification_status=ClassificationStatus.NON_SENSITIVE,
        ),
    ]


def _sample_transformation_policies() -> list[TransformationPolicy]:
    source = _sample_source()
    return [
        TransformationPolicy(
            policy_id="policy-customers-email",
            system_id=source.system_id,
            system_name=source.system_name,
            object_name="crm.customers",
            column_name="email",
            sensitivity_tag="pii.email",
            transformation_type=TransformationType.DETERMINISTIC_PSEUDONYMIZATION,
        )
    ]


def _build_readiness_service(clock: DemoClock) -> PublishReadinessValidationService:
    coverage = PolicyCoverageEvaluationService(
        metadata_catalog=InMemoryMetadataCatalogRepository(_sample_metadata_objects(), _sample_relationships()),
        policies=InMemoryTransformationPolicyRepository(_sample_transformation_policies()),
        classifications=InMemoryClassificationRepository(_sample_sensitivity_tags()),
        clock=clock,
    )
    return PublishReadinessValidationService(coverage)


def _build_publish_source_resolution_service() -> PublishSourceResolutionService:
    return PublishSourceResolutionService(
        BaselineSelectionService(
            InMemoryBaselineRepository([_sample_baseline()]),
            BaselineStorageReadinessService(InMemoryBaselineAssetRepository([_sample_baseline_asset()])),
            BaselineValidationEligibilityService(
                ValidationLookupService(
                    InMemoryValidationRepository([_sample_validation_report()])
                )
            ),
        )
    )


def build_demo_api_app() -> ApiApp:
    clock = DemoClock()
    ids = SequentialIdGenerator()

    system_repo = InMemorySystemRepository([_sample_system()])
    source_repo = InMemoryDataSourceRepository([_sample_source()])
    target_repo = InMemoryTargetEnvironmentRepository([_sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([_sample_profile()])
    baseline_repo = InMemoryBaselineRepository([_sample_baseline()])
    baseline_asset_repo = InMemoryBaselineAssetRepository([_sample_baseline_asset()])
    refresh_schedule_repo = InMemoryBaselineRefreshScheduleRepository([_sample_refresh_schedule()])
    refresh_job_repo = InMemoryBaselineRefreshJobRepository(
        [
            BaselineRefreshJob.create(
                job_id="baseline-refresh-1",
                system_id="crm",
                dataset_profile_id="profile-full-sanitized",
                target_environment_type=EnvironmentType.DEV,
                requested_by="steward@example.internal",
                created_at=clock.now(),
                trigger_type="scheduled",
                refresh_schedule_id="refresh-schedule-1",
            ).transition_to(
                BaselineRefreshStatus.COMPLETED,
                updated_at=clock.now(),
                baseline_id="baseline-crm-dev-v1",
                result_summary={"refreshStrategy": "demo-baseline-refresh"},
            )
        ]
    )
    extraction_job_repo = InMemoryExtractionJobRepository(
        [
            ExtractionJob.create(
                job_id="extraction-existing",
                source_id="source-crm-replica",
                system_id="crm",
                plan_snapshot_id="extraction-plan-snapshot-existing",
                root_object_id="table-customers",
                criteria=(
                    SelectionCriteria(field_name="customer_id", operator="eq", value="42"),
                ),
                include_related=False,
                max_depth=1,
                requested_by="developer@example.internal",
                created_at=clock.now(),
            ).transition_to(
                status=ExtractionJobStatus.COMPLETED,
                updated_at=clock.now(),
                execution_summary={"artifactKind": "sample", "selectedObjectCount": 1},
                extraction_artifact_id="extraction-artifact-existing",
            )
        ]
    )
    extraction_snapshot_repo = InMemoryExtractionPlanSnapshotRepository()
    extraction_artifact_repo = InMemoryExtractionArtifactRepository(
        [
            ExtractionArtifact(
                artifact_id="extraction-artifact-existing",
                job_id="extraction-existing",
                source_id="source-crm-replica",
                root_object_id="table:source-crm-replica:public.customers",
                kind=ExtractionArtifactKind.SAMPLE,
                artifact_format=ExtractionArtifactFormat.JSONL,
                artifact_path="/tmp/extraction-existing.jsonl",
                row_count=2,
                created_at=clock.now(),
                file_size_bytes=256,
                checksum="api-artifact-checksum",
                column_count=2,
            )
        ]
    )
    artifact_publish_job_repo = InMemoryArtifactPublishJobRepository(
        [
            ArtifactPublishJob.create(
                job_id="artifact-publish-job-1",
                extraction_artifact_id="extraction-artifact-existing",
                source_id="source-crm-replica",
                root_object_id="table:source-crm-replica:public.customers",
                target_environment_id="env-dev",
                requested_by="developer@example.internal",
                created_at=clock.now(),
            )
        ]
    )
    publish_job_repo = InMemoryPublishJobRepository(
        [
            PublishJob.create(
                job_id="job-1",
                source_id="source-crm-replica",
                sanitized_baseline_id="baseline-crm-dev-v1",
                baseline_validation_status=ValidationStatus.PASSED,
                baseline_validation_warning_count=0,
                baseline_validation_error_count=0,
                baseline_validated_at=datetime(2026, 1, 1, 7, tzinfo=timezone.utc),
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
                created_at=clock.now(),
            )
        ]
    )
    refresh_queue = InMemoryBaselineRefreshQueue()
    extraction_queue = InMemoryExtractionQueue()
    artifact_publish_queue = InMemoryArtifactPublishQueue()
    publish_queue = InMemoryJobQueue()
    audit_repo = InMemoryAuditEventRepository(
        [
            AuditEvent(
                event_id="audit-publish-1",
                event_type="publish_job_requested",
                actor="developer@example.internal",
                subject_type="publish_job",
                subject_id="job-1",
                details={"sourceId": "source-crm-replica"},
                created_at=clock.now(),
            ),
            AuditEvent(
                event_id="audit-artifact-1",
                event_type="extraction_artifact_expired",
                actor="system",
                subject_type="extraction_artifact",
                subject_id="extraction-artifact-existing",
                details={"runId": "artifact-retention-run-1"},
                created_at=clock.now(),
            ),
        ]
    )
    lineage_repo = InMemoryLineageRepository(
        [
            LineageRecord(
                record_id="lineage-1",
                source_type="sanitized_baseline",
                source_id="baseline-crm-dev-v1",
                target_type="publish_job",
                target_id="job-1",
                event_type="baseline_published",
                created_at=clock.now(),
                details={"baselineVersion": "2026.01.01.1"},
            ),
            LineageRecord(
                record_id="lineage-2",
                source_type="extraction_job",
                source_id="extraction-existing",
                target_type="extraction_artifact",
                target_id="extraction-artifact-existing",
                event_type="extraction_materialized_artifact",
                created_at=clock.now(),
                details={"artifactKind": "sample"},
            ),
            LineageRecord(
                record_id="lineage-3",
                source_type="extraction_artifact",
                source_id="extraction-artifact-existing",
                target_type="artifact_publish_job",
                target_id="artifact-publish-job-1",
                event_type="artifact_publish_from_extraction_artifact",
                created_at=clock.now(),
                details={"rootObjectId": "table:source-crm-replica:public.customers"},
            ),
        ]
    )

    metadata_catalog = InMemoryMetadataCatalogRepository(_sample_metadata_objects(), _sample_relationships())
    classifications = InMemoryClassificationRepository(_sample_sensitivity_tags())
    policies = InMemoryTransformationPolicyRepository(_sample_transformation_policies())
    validations = ValidationLookupService(InMemoryValidationRepository([_sample_validation_report()]))

    adapter_registry = AdapterRegistry()
    adapter_registry.register(
        engine_type=DatabaseEngine.POSTGRES,
        metadata_discovery=object(),
        extraction_pipeline=object(),
        artifact_publish_pipeline=object(),
        baseline_refresh_pipeline=object(),
        baseline_publish_pipeline=object(),
    )
    adapter_registry.register(
        engine_type=DatabaseEngine.ORACLE,
        metadata_discovery=object(),
        extraction_pipeline=object(),
        artifact_publish_pipeline=object(),
        baseline_refresh_pipeline=object(),
        baseline_publish_pipeline=object(),
    )

    catalog = CatalogQueryService(system_repo, source_repo, target_repo, profile_repo)
    coverage = PolicyCoverageEvaluationService(
        metadata_catalog=metadata_catalog,
        policies=policies,
        classifications=classifications,
        clock=clock,
    )

    return ApiApp(
        artifact_publish_monitoring=ArtifactPublishMonitoringService(artifact_publish_job_repo),
        artifact_publish_requests=ArtifactPublishRequestService(
            artifacts=extraction_artifact_repo,
            environments=target_repo,
            jobs=artifact_publish_job_repo,
            audits=audit_repo,
            queue=artifact_publish_queue,
            clock=clock,
            ids=ids,
        ),
        audit_queries=AuditQueryService(audit_repo),
        baselines=BaselineQueryService(
            systems=system_repo,
            baselines=baseline_repo,
            baseline_assets=baseline_asset_repo,
            validations=validations,
            validation_summary=PublishValidationSummaryService(),
            eligibility=BaselineEligibilityExplanationService(),
        ),
        baseline_refresh_monitoring=BaselineRefreshMonitoringService(refresh_job_repo),
        baseline_refresh_requests=BaselineRefreshRequestService(
            systems=system_repo,
            data_sources=source_repo,
            dataset_profiles=profile_repo,
            refresh_jobs=refresh_job_repo,
            refresh_queue=refresh_queue,
            audits=audit_repo,
            clock=clock,
            ids=ids,
        ),
        catalog=catalog,
        classification_queries=ClassificationQueryService(
            systems=system_repo,
            data_sources=source_repo,
            classifications=classifications,
        ),
        engine_capabilities=EngineCapabilityQueryService(adapter_registry),
        extraction_job_monitoring=ExtractionJobMonitoringService(extraction_job_repo),
        extraction_job_requests=ExtractionJobRequestService(
            data_sources=source_repo,
            extraction_jobs=extraction_job_repo,
            extraction_plan_snapshots=extraction_snapshot_repo,
            extraction_queue=extraction_queue,
            planning=ExtractionPlanningService(
                InMemoryMetadataCatalogRepository(
                    _sample_preview_metadata_objects(),
                    _sample_relationships(),
                )
            ),
            audits=audit_repo,
            clock=clock,
            ids=ids,
        ),
        extraction_artifacts=ExtractionArtifactQueryService(
            jobs=extraction_job_repo,
            artifacts=extraction_artifact_repo,
            lifecycle=ExtractionArtifactLifecycleService(
                artifacts=extraction_artifact_repo,
                clock=clock,
            ),
        ),
        extraction_plan_previews=ExtractionPlanPreviewService(
            ExtractionPlanningService(
                InMemoryMetadataCatalogRepository(
                    _sample_preview_metadata_objects(),
                    _sample_relationships(),
                )
            )
        ),
        extraction_plan_snapshots=ExtractionPlanSnapshotQueryService(extraction_snapshot_repo),
        governance_summary_queries=GovernanceSummaryQueryService(
            systems=system_repo,
            data_sources=source_repo,
            metadata_catalog=metadata_catalog,
            classifications=classifications,
            policies=policies,
            coverage=coverage,
        ),
        lineage_queries=LineageQueryService(lineage_repo),
        metadata_queries=MetadataQueryService(
            systems=system_repo,
            data_sources=source_repo,
            metadata_catalog=metadata_catalog,
        ),
        relationship_queries=RelationshipQueryService(
            systems=system_repo,
            data_sources=source_repo,
            metadata_catalog=metadata_catalog,
        ),
        policy_queries=PolicyQueryService(
            systems=system_repo,
            data_sources=source_repo,
            policies=policies,
        ),
        policy_coverage_queries=PolicyCoverageQueryService(
            systems=system_repo,
            data_sources=source_repo,
            coverage=coverage,
        ),
        publish_requests=PublishRequestService(
            data_sources=source_repo,
            environments=target_repo,
            dataset_profiles=profile_repo,
            jobs=publish_job_repo,
            audits=audit_repo,
            queue=publish_queue,
            policy=AllowAllPolicy(),
            readiness=_build_readiness_service(clock),
            publish_source_resolution=_build_publish_source_resolution_service(),
            clock=clock,
            ids=ids,
        ),
        refresh_schedules=RefreshScheduleService(
            systems=system_repo,
            dataset_profiles=profile_repo,
            schedules=refresh_schedule_repo,
            clock=clock,
            ids=ids,
        ),
        validation_queries=ValidationQueryService(
            baselines=baseline_repo,
            validations=validations,
        ),
        job_monitoring=JobMonitoringService(publish_job_repo, audit_repo),
    )


def build_demo_runtime() -> DemoRuntime:
    api_app = build_demo_api_app()

    def ready_probe() -> dict[str, object]:
        return {
            "status": "ok",
            "environment": "demo",
            "service": "Sanitized Data Platform Demo",
            "dependencies": [
                {"name": "seeded-control-plane", "status": "ok", "details": {"mode": "in-memory"}},
                {"name": "http-transport", "status": "ok", "details": {}},
            ],
        }

    def metrics_provider() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "Sanitized Data Platform Demo",
            "environment": "demo",
            "metrics": {
                "publishJobCount": len(api_app.handle("GET", "/api/v1/jobs").body),
                "extractionJobCount": len(api_app.handle("GET", "/api/v1/extraction-jobs").body),
                "artifactPublishJobCount": len(
                    api_app.handle("GET", "/api/v1/artifact-publish-jobs").body
                ),
                "baselineCount": len(api_app.handle("GET", "/api/v1/baselines").body),
                "baselineRefreshJobCount": len(
                    api_app.handle("GET", "/api/v1/baseline-refresh-jobs").body
                ),
            },
        }

    return DemoRuntime(
        api_app=api_app,
        ready_probe=ready_probe,
        metrics_provider=metrics_provider,
    )


def create_demo_fastapi_app():
    runtime = build_demo_runtime()
    return create_fastapi_app(
        runtime.api_app,
        service_name="Sanitized Data Platform Demo",
        ready_probe=runtime.ready_probe,
        metrics_provider=runtime.metrics_provider,
    )
