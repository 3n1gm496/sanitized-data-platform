import pytest

from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import (
    BaselineLookupService,
    BaselineSelectionService,
    PublishRequestService,
)
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryJobQueue,
    InMemoryPublishJobRepository,
    InMemoryTargetEnvironmentRepository,
    SequentialIdGenerator,
    build_publish_source_resolution_service,
    build_readiness_service,
    sample_baseline,
    sample_profile,
    sample_source,
    sample_target,
)


def test_baseline_lookup_lists_active_baselines_for_system():
    service = BaselineLookupService(
        InMemoryBaselineRepository([sample_baseline()])
    )

    baselines = service.list_active_for_system("crm")

    assert len(baselines) == 1
    assert baselines[0].baseline_id == "baseline-crm-dev-v1"


def test_baseline_selection_returns_compatible_active_baseline():
    service = BaselineSelectionService(
        InMemoryBaselineRepository([sample_baseline()])
    )

    baseline = service.select_for_publish(
        source=sample_source(),
        target=sample_target(),
        profile=sample_profile(),
    )

    assert baseline.baseline_id == "baseline-crm-dev-v1"


def test_baseline_selection_fails_when_no_compatible_baseline_exists():
    service = BaselineSelectionService(InMemoryBaselineRepository([]))

    with pytest.raises(DomainError, match="No compatible active sanitized baseline"):
        service.select_for_publish(
            source=sample_source(),
            target=sample_target(),
            profile=sample_profile(),
        )


def test_publish_request_fails_when_profile_requires_baseline_but_none_exists():
    service = PublishRequestService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        environments=InMemoryTargetEnvironmentRepository([sample_target()]),
        dataset_profiles=InMemoryDatasetProfileRepository([sample_profile()]),
        jobs=InMemoryPublishJobRepository(),
        audits=InMemoryAuditEventRepository(),
        queue=InMemoryJobQueue(),
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(),
        publish_source_resolution=build_publish_source_resolution_service(baselines=[]),
        clock=FakeClock(),
        ids=SequentialIdGenerator(),
    )

    with pytest.raises(DomainError, match="No compatible active sanitized baseline"):
        service.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-replica",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )
