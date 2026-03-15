from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from .enums import (
    DatabaseEngine,
    DatasetMode,
    EnvironmentType,
    JobStatus,
    MetadataObjectType,
    PolicyCoverageSeverity,
    TransformationType,
)
from .errors import DomainError


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class DataSource:
    source_id: str
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
    name: str
    system_name: str
    dataset_mode: DatasetMode
    target_environment_type: EnvironmentType
    uses_sanitized_baseline: bool = True
    preserve_constraints: bool = True
    requires_approval: bool = False
    active: bool = True


@dataclass(frozen=True, slots=True)
class MetadataObject:
    object_id: str
    source_id: str
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
class SensitivityTag:
    tag_id: str
    source_id: str
    object_id: str
    tag_name: str
    assigned_by: str
    approved: bool = True
    active: bool = True


@dataclass(frozen=True, slots=True)
class TransformationPolicy:
    policy_id: str
    system_name: str
    object_name: str
    column_name: str
    sensitivity_tag: str
    transformation_type: TransformationType
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
        if self.system_name != metadata_object.system_name:
            return False
        if self.object_name != metadata_object.container_name:
            return False
        if self.column_name != metadata_object.name:
            return False
        return any(tag.tag_name == self.sensitivity_tag for tag in tags)


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
        target_environment_id: str,
        dataset_profile_id: str,
        requested_by: str,
        created_at: datetime,
    ) -> "PublishJob":
        return cls(
            job_id=job_id,
            source_id=source_id,
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
