import pytest

from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import PublishRequestService
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import DatabaseEngine

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryJobQueue,
    InMemoryPublishJobRepository,
    InMemoryTargetEnvironmentRepository,
    SequentialIdGenerator,
    build_publish_source_resolution_service,
    build_readiness_service,
    sample_profile,
    sample_source,
    sample_target,
)


def build_service():
    return PublishRequestService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        environments=InMemoryTargetEnvironmentRepository([sample_target()]),
        dataset_profiles=InMemoryDatasetProfileRepository([sample_profile()]),
        jobs=InMemoryPublishJobRepository(),
        audits=InMemoryAuditEventRepository(),
        queue=InMemoryJobQueue(),
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(),
        publish_source_resolution=build_publish_source_resolution_service(),
        clock=FakeClock(),
        ids=SequentialIdGenerator(),
    )


def test_create_job_persists_and_queues_publish_request():
    service = build_service()

    job = service.create_job(
        CreatePublishJobCommand(
            source_id="source-crm-replica",
            target_environment_id="env-dev",
            dataset_profile_id="profile-full-sanitized",
            requested_by="developer@example.internal",
        )
    )

    assert job.job_id == "job-1"
    assert job.status == "pending"
    assert job.sanitized_baseline_id == "baseline-crm-dev-v1"
    assert job.execution_summary == {}


def test_create_job_rejects_engine_mismatch():
    target = sample_target()
    mismatched_target = type(target)(
        environment_id=target.environment_id,
        name=target.name,
        environment_type=target.environment_type,
        engine_type=DatabaseEngine.MYSQL,
        target_endpoint=target.target_endpoint,
    )
    service = PublishRequestService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        environments=InMemoryTargetEnvironmentRepository([mismatched_target]),
        dataset_profiles=InMemoryDatasetProfileRepository([sample_profile()]),
        jobs=InMemoryPublishJobRepository(),
        audits=InMemoryAuditEventRepository(),
        queue=InMemoryJobQueue(),
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(),
        publish_source_resolution=build_publish_source_resolution_service(),
        clock=FakeClock(),
        ids=SequentialIdGenerator(),
    )

    with pytest.raises(DomainError):
        service.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-replica",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )
