from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from .enums import (
    DatabaseEngine,
    DatasetMode,
    EnvironmentType,
    JobStatus,
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
