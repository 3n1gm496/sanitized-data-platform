from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .enums import (
    BaselineStatus,
    BaselineRefreshStatus,
    ClassificationStatus,
    DatabaseEngine,
    DatasetMode,
    EnvironmentType,
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    ExtractionArtifactStatus,
    ExtractionJobStatus,
    JobStatus,
    MetadataObjectType,
    PolicyCoverageSeverity,
    RefreshScheduleStatus,
    TransformationType,
    ValidationSeverity,
    ValidationStatus,
)
from .errors import DomainError


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class System:
    system_id: str
    name: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class DataSource:
    source_id: str
    system_id: str
    system_name: str
    engine_type: DatabaseEngine
    endpoint: str
    database_name: str
    access_mode: str = "replica"
    replica_preferred: bool = True
    active: bool = True


@dataclass(frozen=True, slots=True)
class TargetEnvironment:
    environment_id: str
    name: str
    environment_type: EnvironmentType
    engine_type: DatabaseEngine
    target_endpoint: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    profile_id: str
    system_id: str
    name: str
    system_name: str
    dataset_mode: DatasetMode
    target_environment_type: EnvironmentType
    uses_sanitized_baseline: bool = True
    preserve_constraints: bool = True
    requires_approval: bool = False
    active: bool = True


@dataclass(frozen=True, slots=True)
class SanitizedBaseline:
    baseline_id: str
    system_id: str
    system_name: str
    source_id: str
    dataset_profile_id: str
    target_environment_type: EnvironmentType
    engine_type: DatabaseEngine
    version: str
    status: BaselineStatus
    created_at: datetime
    refreshed_at: datetime
    active: bool = True

    @property
    def is_selectable(self) -> bool:
        return self.active and self.status == BaselineStatus.ACTIVE

    def is_compatible_with(
        self,
        *,
        source: DataSource,
        target: TargetEnvironment,
        profile: DatasetProfile,
    ) -> bool:
        return (
            self.is_selectable
            and self.system_id == source.system_id
            and self.dataset_profile_id == profile.profile_id
            and self.target_environment_type == target.environment_type
            and self.engine_type == source.engine_type
            and self.engine_type == target.engine_type
        )


@dataclass(frozen=True, slots=True)
class ValidationCheckResult:
    check_name: str
    severity: ValidationSeverity
    passed: bool
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    report_id: str
    baseline_id: str
    status: ValidationStatus
    checks: tuple[ValidationCheckResult, ...]
    created_at: datetime

    @property
    def warning_count(self) -> int:
        return sum(1 for check in self.checks if check.severity == ValidationSeverity.WARNING)

    @property
    def error_count(self) -> int:
        return sum(1 for check in self.checks if check.severity == ValidationSeverity.ERROR)

    @property
    def is_publish_eligible(self) -> bool:
        return self.status in {
            ValidationStatus.PASSED,
            ValidationStatus.PASSED_WITH_WARNINGS,
        }


@dataclass(frozen=True, slots=True)
class BaselineRefreshJob:
    job_id: str
    system_id: str
    dataset_profile_id: str
    target_environment_type: EnvironmentType
    requested_by: str
    trigger_type: str
    refresh_schedule_id: str | None
    status: BaselineRefreshStatus
    baseline_id: str | None
    created_at: datetime
    updated_at: datetime
    result_summary: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        system_id: str,
        dataset_profile_id: str,
        target_environment_type: EnvironmentType,
        requested_by: str,
        trigger_type: str,
        created_at: datetime,
        baseline_id: str | None = None,
        refresh_schedule_id: str | None = None,
    ) -> "BaselineRefreshJob":
        return cls(
            job_id=job_id,
            system_id=system_id,
            dataset_profile_id=dataset_profile_id,
            target_environment_type=target_environment_type,
            requested_by=requested_by,
            trigger_type=trigger_type,
            refresh_schedule_id=refresh_schedule_id,
            status=BaselineRefreshStatus.REQUESTED,
            baseline_id=baseline_id,
            created_at=created_at,
            updated_at=created_at,
        )

    def transition_to(
        self,
        status: BaselineRefreshStatus,
        *,
        updated_at: datetime,
        baseline_id: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> "BaselineRefreshJob":
        summary = dict(self.result_summary)
        if result_summary:
            summary.update(result_summary)

        return replace(
            self,
            status=status,
            baseline_id=self.baseline_id if baseline_id is None else baseline_id,
            updated_at=updated_at,
            result_summary=summary,
        )


@dataclass(frozen=True, slots=True)
class BaselineRefreshSchedule:
    schedule_id: str
    system_id: str
    dataset_profile_id: str
    target_environment_type: EnvironmentType
    interval_minutes: int
    status: RefreshScheduleStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime
    last_dispatched_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        return self.status == RefreshScheduleStatus.ENABLED

    def is_due(self, at: datetime) -> bool:
        return self.enabled and self.next_run_at <= at

    def mark_dispatched(self, *, dispatched_at: datetime) -> "BaselineRefreshSchedule":
        return replace(
            self,
            last_dispatched_at=dispatched_at,
            next_run_at=dispatched_at + timedelta(minutes=self.interval_minutes),
            updated_at=dispatched_at,
        )


@dataclass(frozen=True, slots=True)
class LineageRecord:
    record_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    event_type: str
    created_at: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetadataObject:
    object_id: str
    source_id: str
    system_id: str
    system_name: str
    object_type: MetadataObjectType
    name: str
    qualified_name: str
    container_name: str | None = None
    parent_object_id: str | None = None
    logical_data_type: str | None = None
    active: bool = True

    @property
    def is_column(self) -> bool:
        return self.object_type == MetadataObjectType.COLUMN


@dataclass(frozen=True, slots=True)
class Relationship:
    relationship_id: str
    source_id: str
    source_object_id: str
    target_object_id: str
    relationship_type: str
    inferred: bool = False
    confidence: float | None = None
    active: bool = True


@dataclass(frozen=True, slots=True)
class SelectionCriteria:
    field_name: str
    operator: str
    value: str


@dataclass(frozen=True, slots=True)
class ExtractionRoot:
    object_id: str
    criteria: tuple[SelectionCriteria, ...] = ()
    selected_columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TraversalRule:
    include_related: bool = False
    max_depth: int = 0
    relationship_types: tuple[str, ...] = ("foreign_key",)


@dataclass(frozen=True, slots=True)
class ExtractionPlan:
    source_id: str
    root: ExtractionRoot
    traversal_rule: TraversalRule
    selected_object_ids: tuple[str, ...]
    selected_relationship_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionPlanSnapshot:
    snapshot_id: str
    source_id: str
    root: ExtractionRoot
    traversal_rule: TraversalRule
    selected_object_ids: tuple[str, ...]
    selected_relationship_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    created_by: str = "system"

    @classmethod
    def from_plan(
        cls,
        *,
        snapshot_id: str,
        plan: ExtractionPlan,
        created_at: datetime,
        created_by: str,
    ) -> "ExtractionPlanSnapshot":
        return cls(
            snapshot_id=snapshot_id,
            source_id=plan.source_id,
            root=plan.root,
            traversal_rule=plan.traversal_rule,
            selected_object_ids=plan.selected_object_ids,
            selected_relationship_ids=plan.selected_relationship_ids,
            notes=plan.notes,
            created_at=created_at,
            created_by=created_by,
        )

    def to_plan(self) -> ExtractionPlan:
        return ExtractionPlan(
            source_id=self.source_id,
            root=self.root,
            traversal_rule=self.traversal_rule,
            selected_object_ids=self.selected_object_ids,
            selected_relationship_ids=self.selected_relationship_ids,
            notes=self.notes,
        )


@dataclass(frozen=True, slots=True)
class ExtractionArtifact:
    artifact_id: str
    job_id: str
    source_id: str
    root_object_id: str
    kind: ExtractionArtifactKind
    artifact_format: ExtractionArtifactFormat
    artifact_path: str
    row_count: int
    created_at: datetime
    file_size_bytes: int | None = None
    checksum: str | None = None
    column_count: int | None = None
    status: ExtractionArtifactStatus = ExtractionArtifactStatus.AVAILABLE
    expires_at: datetime | None = None
    deleted_at: datetime | None = None

    @property
    def is_available(self) -> bool:
        return self.status == ExtractionArtifactStatus.AVAILABLE

    def expire(self, *, expired_at: datetime) -> "ExtractionArtifact":
        return replace(
            self,
            status=ExtractionArtifactStatus.EXPIRED,
            expires_at=expired_at if self.expires_at is None else self.expires_at,
        )

    def mark_deleted(self, *, deleted_at: datetime) -> "ExtractionArtifact":
        return replace(
            self,
            status=ExtractionArtifactStatus.DELETED,
            deleted_at=deleted_at,
        )


@dataclass(frozen=True, slots=True)
class ExtractionJob:
    job_id: str
    source_id: str
    system_id: str
    plan_snapshot_id: str
    root_object_id: str
    criteria: tuple[SelectionCriteria, ...]
    include_related: bool
    max_depth: int
    requested_by: str
    status: ExtractionJobStatus
    extraction_artifact_id: str | None
    created_at: datetime
    updated_at: datetime
    execution_summary: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        source_id: str,
        system_id: str,
        plan_snapshot_id: str,
        root_object_id: str,
        criteria: tuple[SelectionCriteria, ...],
        include_related: bool,
        max_depth: int,
        requested_by: str,
        created_at: datetime,
    ) -> "ExtractionJob":
        return cls(
            job_id=job_id,
            source_id=source_id,
            system_id=system_id,
            plan_snapshot_id=plan_snapshot_id,
            root_object_id=root_object_id,
            criteria=criteria,
            include_related=include_related,
            max_depth=max_depth,
            requested_by=requested_by,
            status=ExtractionJobStatus.REQUESTED,
            extraction_artifact_id=None,
            created_at=created_at,
            updated_at=created_at,
        )

    def transition_to(
        self,
        status: ExtractionJobStatus,
        *,
        updated_at: datetime,
        execution_summary: dict[str, Any] | None = None,
        extraction_artifact_id: str | None = None,
    ) -> "ExtractionJob":
        summary = dict(self.execution_summary)
        if execution_summary:
            summary.update(execution_summary)

        return replace(
            self,
            status=status,
            extraction_artifact_id=(
                self.extraction_artifact_id
                if extraction_artifact_id is None
                else extraction_artifact_id
            ),
            updated_at=updated_at,
            execution_summary=summary,
        )


@dataclass(frozen=True, slots=True)
class SensitivityTag:
    tag_id: str
    source_id: str
    object_id: str
    tag_name: str
    assigned_by: str
    classification_status: ClassificationStatus = ClassificationStatus.SENSITIVE
    approved: bool = True
    active: bool = True

    @property
    def is_sensitive(self) -> bool:
        return (
            self.active
            and self.approved
            and self.classification_status == ClassificationStatus.SENSITIVE
        )

    @property
    def is_non_sensitive(self) -> bool:
        return (
            self.active
            and self.approved
            and self.classification_status == ClassificationStatus.NON_SENSITIVE
        )

    @property
    def needs_review(self) -> bool:
        return self.active and (
            self.classification_status == ClassificationStatus.NEEDS_REVIEW
            or not self.approved
        )


@dataclass(frozen=True, slots=True)
class TransformationPolicy:
    policy_id: str
    system_id: str
    system_name: str
    object_name: str
    column_name: str
    sensitivity_tag: str
    transformation_type: TransformationType
    object_id: str | None = None
    reversible: bool = False
    preserve_format: bool = True
    preserve_length: bool = True
    tokenization_domain_id: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        if self.reversible and not self.tokenization_domain_id:
            raise DomainError(
                "Reversible transformation policies require a tokenization domain."
            )

    def applies_to(self, metadata_object: MetadataObject, tags: list[SensitivityTag]) -> bool:
        if not metadata_object.is_column:
            return False
        if not self.target.matches_metadata_column(
            metadata_object=metadata_object,
        ):
            return False
        return any(tag.tag_name == self.sensitivity_tag for tag in tags)

    @property
    def target(self) -> "TransformationPolicyTarget":
        return TransformationPolicyTarget(
            system_id=self.system_id,
            canonical_object_id=self.object_id,
            legacy_object_name=self.object_name,
            column_name=self.column_name,
        )


@dataclass(frozen=True, slots=True)
class TransformationPolicyTarget:
    system_id: str
    canonical_object_id: str | None
    legacy_object_name: str | None
    column_name: str

    def matches_metadata_column(self, *, metadata_object: MetadataObject) -> bool:
        if self._normalize_identity(self.system_id) != self._normalize_identity(
            metadata_object.system_id
        ):
            return False
        if self._normalize_identity(self.column_name) != self._normalize_identity(
            metadata_object.name
        ):
            return False
        return self.matches_table_identity(
            canonical_object_id=metadata_object.parent_object_id,
            legacy_object_name=metadata_object.container_name,
        )

    def matches_table_identity(
        self,
        *,
        canonical_object_id: str | None,
        legacy_object_name: str | None,
    ) -> bool:
        if self.canonical_object_id is not None:
            return self._normalize_identity(self.canonical_object_id) == self._normalize_identity(
                canonical_object_id
            )
        legacy_identity = self._normalize_identity(self.legacy_object_name)
        return legacy_identity in {
            self._normalize_identity(canonical_object_id),
            self._normalize_identity(legacy_object_name),
        }

    @staticmethod
    def _normalize_identity(value: str | None) -> str:
        if value is None:
            return ""
        return value.strip().lower()


@dataclass(frozen=True, slots=True)
class PolicyCoverageGap:
    gap_type: str
    metadata_object_id: str
    object_name: str
    message: str
    severity: PolicyCoverageSeverity
    sensitivity_tags: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return self.severity == PolicyCoverageSeverity.BLOCKING


@dataclass(frozen=True, slots=True)
class PolicyCoverageReport:
    source_id: str
    system_id: str
    system_name: str
    evaluated_object_count: int
    covered_object_count: int
    gaps: tuple[PolicyCoverageGap, ...]
    evaluated_at: datetime = field(default_factory=utc_now)

    @property
    def blocking_gaps(self) -> tuple[PolicyCoverageGap, ...]:
        return tuple(gap for gap in self.gaps if gap.blocking)

    @property
    def informational_gaps(self) -> tuple[PolicyCoverageGap, ...]:
        return tuple(gap for gap in self.gaps if not gap.blocking)

    @property
    def is_publish_ready(self) -> bool:
        return not self.blocking_gaps


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    actor: str
    subject_type: str
    subject_id: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class PublishJob:
    job_id: str
    source_id: str
    sanitized_baseline_id: str | None
    baseline_validation_status: ValidationStatus | None
    baseline_validation_warning_count: int
    baseline_validation_error_count: int
    baseline_validated_at: datetime | None
    target_environment_id: str
    dataset_profile_id: str
    requested_by: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    execution_summary: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        source_id: str,
        sanitized_baseline_id: str | None,
        baseline_validation_status: ValidationStatus | None,
        baseline_validation_warning_count: int,
        baseline_validation_error_count: int,
        baseline_validated_at: datetime | None,
        target_environment_id: str,
        dataset_profile_id: str,
        requested_by: str,
        created_at: datetime,
    ) -> "PublishJob":
        return cls(
            job_id=job_id,
            source_id=source_id,
            sanitized_baseline_id=sanitized_baseline_id,
            baseline_validation_status=baseline_validation_status,
            baseline_validation_warning_count=baseline_validation_warning_count,
            baseline_validation_error_count=baseline_validation_error_count,
            baseline_validated_at=baseline_validated_at,
            target_environment_id=target_environment_id,
            dataset_profile_id=dataset_profile_id,
            requested_by=requested_by,
            status=JobStatus.PENDING,
            created_at=created_at,
            updated_at=created_at,
        )

    def transition_to(
        self,
        status: JobStatus,
        *,
        updated_at: datetime,
        execution_summary: dict[str, Any] | None = None,
    ) -> "PublishJob":
        summary = dict(self.execution_summary)
        if execution_summary:
            summary.update(execution_summary)

        return replace(
            self,
            status=status,
            updated_at=updated_at,
            execution_summary=summary,
        )
