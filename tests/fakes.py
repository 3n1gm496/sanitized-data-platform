from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sanitized_data_platform.domain.entities import (
    AuditEvent,
    DataSource,
    DatasetProfile,
    PublishJob,
    TargetEnvironment,
)
from sanitized_data_platform.domain.enums import (
    DatabaseEngine,
    DatasetMode,
    EnvironmentType,
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


class InMemoryDataSourceRepository:
    def __init__(self, items: list[DataSource]) -> None:
        self._items = {item.source_id: item for item in items}

    def list_active(self) -> list[DataSource]:
        return [item for item in self._items.values() if item.active]

    def get_by_id(self, source_id: str) -> DataSource | None:
        return self._items.get(source_id)


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
        return {
            "baselineStrategy": "precomputed_or_generate",
            "rowsPublished": 0,
            "validationStatus": "pending-real-implementation",
        }


def sample_source() -> DataSource:
    return DataSource(
        source_id="source-crm-replica",
        system_name="CRM",
        engine_type=DatabaseEngine.POSTGRES,
        endpoint="postgresql://crm-replica.local",
        database_name="crm",
    )


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
        name="full_sanitized_clone",
        system_name="CRM",
        dataset_mode=DatasetMode.FULL_CLONE,
        target_environment_type=EnvironmentType.DEV,
    )
