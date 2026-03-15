from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sanitized_data_platform.domain.entities import (
    AuditEvent,
    DataSource,
    DatasetProfile,
    PublishJob,
    TargetEnvironment,
)


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class IdGeneratorPort(Protocol):
    def new_id(self, prefix: str) -> str: ...


class DataSourceRepository(Protocol):
    def list_active(self) -> list[DataSource]: ...
    def get_by_id(self, source_id: str) -> DataSource | None: ...


class TargetEnvironmentRepository(Protocol):
    def list_active(self) -> list[TargetEnvironment]: ...
    def get_by_id(self, environment_id: str) -> TargetEnvironment | None: ...


class DatasetProfileRepository(Protocol):
    def list_active(self) -> list[DatasetProfile]: ...
    def get_by_id(self, profile_id: str) -> DatasetProfile | None: ...


class PublishJobRepository(Protocol):
    def add(self, job: PublishJob) -> None: ...
    def get_by_id(self, job_id: str) -> PublishJob | None: ...
    def save(self, job: PublishJob) -> None: ...


class AuditEventRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...
    def list_for_subject(self, subject_id: str) -> list[AuditEvent]: ...


class JobQueuePort(Protocol):
    def enqueue(self, job_id: str) -> None: ...
    def dequeue(self) -> str | None: ...


class PolicyPort(Protocol):
    def assert_publish_allowed(
        self,
        *,
        source: DataSource,
        target: TargetEnvironment,
        profile: DatasetProfile,
        requested_by: str,
    ) -> None: ...


class PublishPipelinePort(Protocol):
    def execute(
        self,
        *,
        job: PublishJob,
        source: DataSource,
        target: TargetEnvironment,
        profile: DatasetProfile,
    ) -> dict[str, object]: ...
