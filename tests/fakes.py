from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from sanitized_data_platform.application.services import (
    MetadataQueryService,
    PolicyCoverageEvaluationService,
    PolicyCoverageQueryService,
    PolicyQueryService,
    PublishReadinessValidationService,
)
from sanitized_data_platform.domain.entities import (
    AuditEvent,
    DataSource,
    DatasetProfile,
    MetadataObject,
    PublishJob,
    Relationship,
    SanitizedBaseline,
    SensitivityTag,
    System,
    TargetEnvironment,
    TransformationPolicy,
)
from sanitized_data_platform.domain.enums import (
    BaselineStatus,
    DatabaseEngine,
    DatasetMode,
    EnvironmentType,
    MetadataObjectType,
    TransformationType,
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

    def get_by_id(self, baseline_id: str) -> SanitizedBaseline | None:
        return self._items.get(baseline_id)


class InMemoryMetadataCatalogRepository:
    def __init__(
        self,
        objects: list[MetadataObject],
        relationships: list[Relationship] | None = None,
    ) -> None:
        self._objects = list(objects)
        self._relationships = list(relationships or [])

    def list_objects(self, source_id: str, *, object_type=None) -> list[MetadataObject]:
        items = [item for item in self._objects if item.source_id == source_id]
        if object_type is not None:
            items = [item for item in items if item.object_type == object_type]
        return items

    def list_relationships(self, source_id: str) -> list[Relationship]:
        return [item for item in self._relationships if item.source_id == source_id]


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


class InMemoryAuditEventRepository:
    def __init__(self) -> None:
        self._items: list[AuditEvent] = []

    def add(self, event: AuditEvent) -> None:
        self._items.append(event)

    def list_for_subject(self, subject_id: str) -> list[AuditEvent]:
        return [event for event in self._items if event.subject_id == subject_id]


class InMemoryJobQueue:
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


def sample_sensitivity_tags() -> list[SensitivityTag]:
    source = sample_source()
    return [
        SensitivityTag(
            tag_id="tag-email",
            source_id=source.source_id,
            object_id="column-customers-email",
            tag_name="pii.email",
            assigned_by="manual-review",
        )
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


def build_publish_source_resolution_service(
    *,
    baselines: list[SanitizedBaseline] | None = None,
):
    from sanitized_data_platform.application.services import (
        BaselineSelectionService,
        PublishSourceResolutionService,
    )

    return PublishSourceResolutionService(
        BaselineSelectionService(
            InMemoryBaselineRepository(
                [sample_baseline()] if baselines is None else baselines
            )
        )
    )
