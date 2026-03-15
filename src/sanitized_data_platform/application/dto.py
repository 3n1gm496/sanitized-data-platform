from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sanitized_data_platform.domain.entities import (
    MetadataObject,
    PolicyCoverageGap,
    PolicyCoverageReport,
    PublishJob,
    TransformationPolicy,
)
from sanitized_data_platform.domain.enums import DatabaseEngine, EnvironmentType


@dataclass(frozen=True, slots=True)
class SystemSummary:
    system_id: str
    name: str
    source_engine: DatabaseEngine
    available_profiles: int


@dataclass(frozen=True, slots=True)
class CreatePublishJobCommand:
    source_id: str
    target_environment_id: str
    dataset_profile_id: str
    requested_by: str


@dataclass(frozen=True, slots=True)
class JobView:
    job_id: str
    status: str
    source_id: str
    target_environment_id: str
    dataset_profile_id: str
    requested_by: str
    created_at: datetime
    updated_at: datetime
    execution_summary: dict[str, Any]

    @classmethod
    def from_job(cls, job: PublishJob) -> "JobView":
        return cls(
            job_id=job.job_id,
            status=job.status.value,
            source_id=job.source_id,
            target_environment_id=job.target_environment_id,
            dataset_profile_id=job.dataset_profile_id,
            requested_by=job.requested_by,
            created_at=job.created_at,
            updated_at=job.updated_at,
            execution_summary=dict(job.execution_summary),
        )


@dataclass(frozen=True, slots=True)
class MetadataObjectView:
    object_id: str
    object_type: str
    name: str
    qualified_name: str
    container_name: str | None
    logical_data_type: str | None
    parent_object_id: str | None

    @classmethod
    def from_metadata_object(cls, metadata_object: MetadataObject) -> "MetadataObjectView":
        return cls(
            object_id=metadata_object.object_id,
            object_type=metadata_object.object_type.value,
            name=metadata_object.name,
            qualified_name=metadata_object.qualified_name,
            container_name=metadata_object.container_name,
            logical_data_type=metadata_object.logical_data_type,
            parent_object_id=metadata_object.parent_object_id,
        )


@dataclass(frozen=True, slots=True)
class MetadataCatalogView:
    system_id: str
    system_name: str
    source_id: str
    items: list[MetadataObjectView]


@dataclass(frozen=True, slots=True)
class TransformationPolicyView:
    policy_id: str
    system_id: str
    system_name: str
    object_name: str
    column_name: str
    sensitivity_tag: str
    transformation_type: str
    reversible: bool
    active: bool

    @classmethod
    def from_policy(cls, policy: TransformationPolicy) -> "TransformationPolicyView":
        return cls(
            policy_id=policy.policy_id,
            system_id=policy.system_id,
            system_name=policy.system_name,
            object_name=policy.object_name,
            column_name=policy.column_name,
            sensitivity_tag=policy.sensitivity_tag,
            transformation_type=policy.transformation_type.value,
            reversible=policy.reversible,
            active=policy.active,
        )


@dataclass(frozen=True, slots=True)
class PolicyListingView:
    filters: dict[str, str]
    items: list[TransformationPolicyView]


@dataclass(frozen=True, slots=True)
class PolicyCoverageGapView:
    gap_type: str
    object_name: str
    severity: str
    message: str
    sensitivity_tags: list[str]

    @classmethod
    def from_gap(cls, gap: PolicyCoverageGap) -> "PolicyCoverageGapView":
        return cls(
            gap_type=gap.gap_type,
            object_name=gap.object_name,
            severity=gap.severity.value,
            message=gap.message,
            sensitivity_tags=list(gap.sensitivity_tags),
        )


@dataclass(frozen=True, slots=True)
class PolicyCoverageReportView:
    system_id: str
    system_name: str
    source_id: str
    publish_ready: bool
    evaluated_object_count: int
    covered_object_count: int
    blocking_gap_count: int
    informational_gap_count: int
    gaps: list[PolicyCoverageGapView]

    @classmethod
    def from_report(cls, report: PolicyCoverageReport) -> "PolicyCoverageReportView":
        return cls(
            system_id=report.system_id,
            system_name=report.system_name,
            source_id=report.source_id,
            publish_ready=report.is_publish_ready,
            evaluated_object_count=report.evaluated_object_count,
            covered_object_count=report.covered_object_count,
            blocking_gap_count=len(report.blocking_gaps),
            informational_gap_count=len(report.informational_gaps),
            gaps=[PolicyCoverageGapView.from_gap(gap) for gap in report.gaps],
        )
