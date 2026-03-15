from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sanitized_data_platform.domain.entities import PublishJob
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
