from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from sanitized_data_platform.application.services import (
    BaselineEligibilityExplanationService,
    BaselineQueryService,
    MetadataQueryService,
    PolicyCoverageEvaluationService,
    PolicyCoverageQueryService,
    PolicyQueryService,
    PublishValidationSummaryService,
    PublishReadinessValidationService,
    ValidationLookupService,
)
from sanitized_data_platform.domain.entities import (
    ArtifactPublishJob,
    AuditEvent,
    BaselineTableAsset,
    BaselineRefreshJob,
    BaselineRefreshSchedule,
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
    SensitivityTag,
    System,
    TargetEnvironment,
    TransformationPolicy,
    ValidationCheckResult,
    ValidationReport,
)
from sanitized_data_platform.domain.enums import (
    BaselineStatus,
    BaselineRefreshStatus,
    ClassificationStatus,
    DatabaseEngine,
    DatasetMode,
    EnvironmentType,
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    MetadataObjectType,
    RefreshScheduleStatus,
    TransformationType,
    ValidationSeverity,
    ValidationStatus,
)


class FakeClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 1, 1, tzinfo=timezone.utc)

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
        return [
            item
            for item in self._items.values()
            if item.system_id == system_id and item.active
        ]

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

    def replace_for_baseline(
        self,
        baseline_id: str,
        assets: list[BaselineTableAsset],
    ) -> None:
        self._items[baseline_id] = list(assets)


class InMemoryValidationRepository:
    def __init__(self, items: list[ValidationReport]) -> None:
        self._items = {item.baseline_id: item for item in items}

    def get_latest_for_baseline(self, baseline_id: str) -> ValidationReport | None:
        return self._items.get(baseline_id)


class InMemoryMetadataCatalogRepository:
    def __init__(
        self,
        objects: list[MetadataObject],
        relationships: list[Relationship] | None = None,
    ) -> None:
        self._objects = {item.object_id: item for item in objects}
        self._relationships = {
            item.relationship_id: item for item in (relationships or [])
        }

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
        return [
            item
            for item in self._relationships.values()
            if item.source_id == source_id
        ]


class InMemoryTransformationPolicyRepository:
    def __init__(self, items: list[TransformationPolicy]) -> None:
        self._items = list(items)

    def list_active_for_system(self, system_id: str) -> list[TransformationPolicy]:
        return [
            item
            for item in self._items
            if item.system_id == system_id and item.active
        ]


class InMemoryClassificationRepository:
    def __init__(self, tags: list[SensitivityTag]) -> None:
        self._tags = list(tags)

    def list_sensitivity_tags(self, source_id: str) -> list[SensitivityTag]:
        return [tag for tag in self._tags if tag.source_id == source_id]


class InMemoryPublishJobRepository:
    def __init__(self) -> None:
        self._items: dict[str, PublishJob] = {}

    def add(self, job: PublishJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> PublishJob | None:
        return self._items.get(job_id)

    def save(self, job: PublishJob) -> None:
        self._items[job.job_id] = job


class InMemoryArtifactPublishJobRepository:
    def __init__(self) -> None:
        self._items: dict[str, ArtifactPublishJob] = {}

    def add(self, job: ArtifactPublishJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> ArtifactPublishJob | None:
        return self._items.get(job_id)

    def list_all(self) -> list[ArtifactPublishJob]:
        return list(self._items.values())

    def save(self, job: ArtifactPublishJob) -> None:
        self._items[job.job_id] = job


class InMemoryBaselineRefreshJobRepository:
    def __init__(self) -> None:
        self._items: dict[str, BaselineRefreshJob] = {}

    def add(self, job: BaselineRefreshJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> BaselineRefreshJob | None:
        return self._items.get(job_id)

    def list_all(self) -> list[BaselineRefreshJob]:
        return list(self._items.values())

    def save(self, job: BaselineRefreshJob) -> None:
        self._items[job.job_id] = job


class InMemoryBaselineRefreshScheduleRepository:
    def __init__(self) -> None:
        self._items: dict[str, BaselineRefreshSchedule] = {}

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
    def __init__(self) -> None:
        self._items: dict[str, ExtractionJob] = {}

    def add(self, job: ExtractionJob) -> None:
        self._items[job.job_id] = job

    def get_by_id(self, job_id: str) -> ExtractionJob | None:
        return self._items.get(job_id)

    def list_all(self) -> list[ExtractionJob]:
        return list(self._items.values())

    def save(self, job: ExtractionJob) -> None:
        self._items[job.job_id] = job


class InMemoryExtractionPlanSnapshotRepository:
    def __init__(self) -> None:
        self._items: dict[str, ExtractionPlanSnapshot] = {}

    def add(self, snapshot: ExtractionPlanSnapshot) -> None:
        self._items[snapshot.snapshot_id] = snapshot

    def get_by_id(self, snapshot_id: str) -> ExtractionPlanSnapshot | None:
        return self._items.get(snapshot_id)


class InMemoryExtractionArtifactRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, ExtractionArtifact] = {}
        self._by_job_id: dict[str, ExtractionArtifact] = {}

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
        self._by_id[artifact.artifact_id] = artifact
        self._by_job_id[artifact.job_id] = artifact


class InMemoryAuditEventRepository:
    def __init__(self) -> None:
        self._items: list[AuditEvent] = []

    def add(self, event: AuditEvent) -> None:
        self._items.append(event)

    def list_for_subject(self, subject_id: str) -> list[AuditEvent]:
        return [event for event in self._items if event.subject_id == subject_id]


class InMemoryLineageRepository:
    def __init__(self) -> None:
        self._items: list[LineageRecord] = []

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
        if not self._items:
            return None
        return self._items.popleft()


class InMemoryBaselineRefreshQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        self._items.append(job_id)

    def dequeue(self) -> str | None:
        if not self._items:
            return None
        return self._items.popleft()


class InMemoryExtractionQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        self._items.append(job_id)

    def dequeue(self) -> str | None:
        if not self._items:
            return None
        return self._items.popleft()


class InMemoryArtifactPublishQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        self._items.append(job_id)

    def dequeue(self) -> str | None:
        if not self._items:
            return None
        return self._items.popleft()


class AllowAllPolicy:
    def assert_publish_allowed(self, **kwargs) -> None:
        return None


class StubPublishPipeline:
    def execute(self, **kwargs) -> dict[str, object]:
        baseline = kwargs.get("baseline")
        return {
            "baselineStrategy": "selected_active_baseline",
            "baselineId": None if baseline is None else baseline.baseline_id,
            "rowsPublished": 0,
            "validationStatus": "pending-real-implementation",
        }


class StubBaselineRefreshPipeline:
    def __init__(
        self,
        *,
        version: str = "2026.01.02.1",
        baseline_assets: list[dict[str, object]] | None = None,
    ) -> None:
        self._version = version
        self._baseline_assets = [] if baseline_assets is None else list(baseline_assets)

    def execute(self, **kwargs) -> dict[str, object]:
        existing_baseline = kwargs.get("existing_baseline")
        return {
            "refreshStrategy": "stubbed-refresh",
            "version": self._version,
            "reusedBaseline": existing_baseline is not None,
            "baselineAssets": list(self._baseline_assets),
        }


class StubExtractionPipeline:
    def execute(self, **kwargs) -> dict[str, object]:
        plan = kwargs["plan"]
        return {
            "extractionStrategy": "stubbed-extraction",
            "artifactKind": plan.root.artifact_kind.value,
            "artifactPath": "/tmp/stub-extraction-artifact.jsonl",
            "artifactFormat": "jsonl",
            "materializedRowCount": len(plan.selected_object_ids),
            "artifactFileSizeBytes": 128,
            "artifactChecksum": "stub-checksum",
            "artifactColumnCount": len(plan.root.selected_columns),
            "selectedObjectCount": len(plan.selected_object_ids),
            "selectedRelationshipCount": len(plan.selected_relationship_ids),
        }


class StubArtifactPublishPipeline:
    def execute(self, **kwargs) -> dict[str, object]:
        artifact = kwargs["artifact"]
        target = kwargs["target"]
        return {
            "deliveryStrategy": "artifact-import-stub",
            "extractionArtifactId": artifact.artifact_id,
            "targetEnvironmentId": target.environment_id,
            "rootObjectId": artifact.root_object_id,
            "rowsImported": artifact.row_count,
            "artifactFormat": artifact.artifact_format.value,
        }


class StubTokenVault:
    def tokenize(self, *, domain_id: str, value: object) -> str:
        return f"tok::{domain_id}::{value}"


def sample_source() -> DataSource:
    return DataSource(
        source_id="source-crm-replica",
        system_id="crm",
        system_name="CRM",
        engine_type=DatabaseEngine.POSTGRES,
        endpoint="postgresql://crm-replica.local",
        database_name="crm",
    )


def sample_system() -> System:
    return System(system_id="crm", name="CRM")


def sample_target() -> TargetEnvironment:
    return TargetEnvironment(
        environment_id="env-dev",
        name="Development",
        environment_type=EnvironmentType.DEV,
        engine_type=DatabaseEngine.POSTGRES,
        target_endpoint="postgresql://crm-dev.local",
    )


def sample_profile() -> DatasetProfile:
    return DatasetProfile(
        profile_id="profile-full-sanitized",
        system_id="crm",
        name="full_sanitized_clone",
        system_name="CRM",
        dataset_mode=DatasetMode.FULL_CLONE,
        target_environment_type=EnvironmentType.DEV,
    )


def sample_metadata_objects() -> list[MetadataObject]:
    source = sample_source()
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
    ]


def sample_relationships() -> list[Relationship]:
    source = sample_source()
    return [
        Relationship(
            relationship_id="pk:source-crm-replica:crm.customers.customer_id",
            source_id=source.source_id,
            source_object_id="table-customers",
            target_object_id="column-customers-email",
            relationship_type="primary_key",
            inferred=False,
            confidence=1.0,
        ),
        Relationship(
            relationship_id="fk:source-crm-replica:crm.orders.customer_id->crm.customers.customer_id",
            source_id=source.source_id,
            source_object_id="column-orders-customer-id",
            target_object_id="column-customers-email",
            relationship_type="foreign_key",
            inferred=False,
            confidence=1.0,
        ),
    ]


def sample_baseline() -> SanitizedBaseline:
    source = sample_source()
    target = sample_target()
    profile = sample_profile()
    refreshed_at = datetime(2026, 1, 1, 6, tzinfo=timezone.utc)
    return SanitizedBaseline(
        baseline_id="baseline-crm-dev-v1",
        system_id=source.system_id,
        system_name=source.system_name,
        source_id=source.source_id,
        dataset_profile_id=profile.profile_id,
        target_environment_type=target.environment_type,
        engine_type=source.engine_type,
        version="2026.01.01.1",
        status=BaselineStatus.ACTIVE,
        created_at=refreshed_at,
        refreshed_at=refreshed_at,
    )


def sample_extraction_artifact(
    *,
    artifact_id: str = "extraction-artifact-1",
    job_id: str = "extraction-1",
) -> ExtractionArtifact:
    source = sample_source()
    created_at = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    return ExtractionArtifact(
        artifact_id=artifact_id,
        job_id=job_id,
        source_id=source.source_id,
        root_object_id="table:source-crm-replica:public.customers",
        kind=ExtractionArtifactKind.FULL,
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/extraction-artifact-1.jsonl",
        row_count=3,
        created_at=created_at,
        file_size_bytes=256,
        checksum="artifact-checksum-1",
        column_count=2,
    )


def sample_validation_report(
    *,
    status: ValidationStatus = ValidationStatus.PASSED,
) -> ValidationReport:
    baseline = sample_baseline()
    created_at = datetime(2026, 1, 1, 7, tzinfo=timezone.utc)
    checks: tuple[ValidationCheckResult, ...]
    if status == ValidationStatus.PASSED:
        checks = (
            ValidationCheckResult(
                check_name="referential_integrity",
                severity=ValidationSeverity.INFO,
                passed=True,
                message="All checks passed.",
            ),
        )
    elif status == ValidationStatus.PASSED_WITH_WARNINGS:
        checks = (
            ValidationCheckResult(
                check_name="row_count_variance",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Minor row count variance detected.",
            ),
        )
    elif status == ValidationStatus.FAILED:
        checks = (
            ValidationCheckResult(
                check_name="referential_integrity",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Foreign key violations detected.",
            ),
        )
    else:
        checks = ()

    return ValidationReport(
        report_id=f"validation-{baseline.baseline_id}",
        baseline_id=baseline.baseline_id,
        status=status,
        checks=checks,
        created_at=created_at,
    )


def sample_baseline_asset(
    *,
    asset_id: str = "baseline-asset-1",
    baseline_id: str = "baseline-crm-dev-v1",
    import_order: int = 0,
) -> BaselineTableAsset:
    source = sample_source()
    created_at = datetime(2026, 1, 1, 6, 30, tzinfo=timezone.utc)
    return BaselineTableAsset(
        asset_id=asset_id,
        baseline_id=baseline_id,
        source_id=source.source_id,
        root_object_id="table:source-crm-replica:public.customers",
        artifact_format=ExtractionArtifactFormat.JSONL,
        artifact_path="/tmp/baseline-asset-1.jsonl",
        row_count=2,
        created_at=created_at,
        checksum="baseline-asset-checksum-1",
        column_count=2,
        import_order=import_order,
    )


def sample_refresh_schedule() -> BaselineRefreshSchedule:
    now = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    return BaselineRefreshSchedule(
        schedule_id="refresh-schedule-1",
        system_id="crm",
        dataset_profile_id="profile-full-sanitized",
        target_environment_type=EnvironmentType.DEV,
        interval_minutes=60,
        status=RefreshScheduleStatus.ENABLED,
        created_by="steward@example.internal",
        created_at=now,
        updated_at=now,
        next_run_at=now,
        last_dispatched_at=None,
    )


def sample_sensitivity_tags() -> list[SensitivityTag]:
    source = sample_source()
    return [
        SensitivityTag(
            tag_id="tag-email",
            source_id=source.source_id,
            object_id="column-customers-email",
            tag_name="pii.email",
            assigned_by="manual-review",
            classification_status=ClassificationStatus.SENSITIVE,
        )
    ]


def sample_classification_tags() -> list[SensitivityTag]:
    source = sample_source()
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
        SensitivityTag(
            tag_id="tag-email-review",
            source_id=source.source_id,
            object_id="column-customers-email",
            tag_name="pii.email",
            assigned_by="classifier",
            classification_status=ClassificationStatus.NEEDS_REVIEW,
            approved=False,
        ),
    ]


def sample_transformation_policies() -> list[TransformationPolicy]:
    source = sample_source()
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


def build_readiness_service(
    *,
    metadata_objects: list[MetadataObject] | None = None,
    relationships: list[Relationship] | None = None,
    sensitivity_tags: list[SensitivityTag] | None = None,
    transformation_policies: list[TransformationPolicy] | None = None,
    clock: FakeClock | None = None,
) -> PublishReadinessValidationService:
    service_clock = clock or FakeClock()
    coverage = PolicyCoverageEvaluationService(
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects() if metadata_objects is None else metadata_objects,
            [] if relationships is None else relationships,
        ),
        policies=InMemoryTransformationPolicyRepository(
            sample_transformation_policies()
            if transformation_policies is None
            else transformation_policies
        ),
        classifications=InMemoryClassificationRepository(
            sample_sensitivity_tags() if sensitivity_tags is None else sensitivity_tags
        ),
        clock=service_clock,
    )
    return PublishReadinessValidationService(coverage)


def build_coverage_evaluation_service(
    *,
    metadata_objects: list[MetadataObject] | None = None,
    relationships: list[Relationship] | None = None,
    sensitivity_tags: list[SensitivityTag] | None = None,
    transformation_policies: list[TransformationPolicy] | None = None,
    clock: FakeClock | None = None,
) -> PolicyCoverageEvaluationService:
    service_clock = clock or FakeClock()
    return PolicyCoverageEvaluationService(
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects() if metadata_objects is None else metadata_objects,
            [] if relationships is None else relationships,
        ),
        policies=InMemoryTransformationPolicyRepository(
            sample_transformation_policies()
            if transformation_policies is None
            else transformation_policies
        ),
        classifications=InMemoryClassificationRepository(
            sample_sensitivity_tags() if sensitivity_tags is None else sensitivity_tags
        ),
        clock=service_clock,
    )


def build_metadata_query_service() -> MetadataQueryService:
    return MetadataQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        metadata_catalog=InMemoryMetadataCatalogRepository(sample_metadata_objects()),
    )


def build_policy_query_service() -> PolicyQueryService:
    return PolicyQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        policies=InMemoryTransformationPolicyRepository(sample_transformation_policies()),
    )


def build_policy_coverage_query_service(
    *,
    clock: FakeClock | None = None,
) -> PolicyCoverageQueryService:
    coverage_clock = clock or FakeClock()
    return PolicyCoverageQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        coverage=build_coverage_evaluation_service(clock=coverage_clock),
    )


def build_baseline_query_service() -> BaselineQueryService:
    return BaselineQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        baselines=InMemoryBaselineRepository([sample_baseline()]),
        baseline_assets=InMemoryBaselineAssetRepository([sample_baseline_asset()]),
        validations=ValidationLookupService(
            InMemoryValidationRepository([sample_validation_report()])
        ),
        validation_summary=PublishValidationSummaryService(),
        eligibility=BaselineEligibilityExplanationService(),
    )


def build_publish_source_resolution_service(
    *,
    baselines: list[SanitizedBaseline] | None = None,
    baseline_assets: list[BaselineTableAsset] | None = None,
    validation_reports: list[ValidationReport] | None = None,
):
    from sanitized_data_platform.application.services import (
        BaselineSelectionService,
        BaselineStorageReadinessService,
        BaselineValidationEligibilityService,
        PublishSourceResolutionService,
        ValidationLookupService,
    )

    return PublishSourceResolutionService(
        BaselineSelectionService(
            InMemoryBaselineRepository(
                [sample_baseline()] if baselines is None else baselines
            ),
            BaselineStorageReadinessService(
                InMemoryBaselineAssetRepository(
                    [sample_baseline_asset()]
                    if baseline_assets is None
                    else baseline_assets
                )
            ),
            BaselineValidationEligibilityService(
                ValidationLookupService(
                    InMemoryValidationRepository(
                        [sample_validation_report()]
                        if validation_reports is None
                        else validation_reports
                    )
                )
            )
        )
    )
