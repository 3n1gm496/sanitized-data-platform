import pytest

from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import (
    BaselineLookupService,
    BaselineSelectionService,
    BaselineStorageReadinessService,
    BaselineValidationEligibilityService,
    PublishRequestService,
    ValidationLookupService,
)
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import ValidationStatus

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineAssetRepository,
    InMemoryBaselineRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryJobQueue,
    InMemoryPublishJobRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    build_publish_source_resolution_service,
    build_readiness_service,
    sample_baseline,
    sample_baseline_asset,
    sample_profile,
    sample_source,
    sample_target,
    sample_validation_report,
)


def test_baseline_lookup_lists_active_baselines_for_system():
    service = BaselineLookupService(
        InMemoryBaselineRepository([sample_baseline()])
    )

    baselines = service.list_active_for_system("crm")

    assert len(baselines) == 1
    assert baselines[0].baseline_id == "baseline-crm-dev-v1"


def test_baseline_selection_returns_compatible_validated_baseline():
    service = BaselineSelectionService(
        InMemoryBaselineRepository([sample_baseline()]),
        BaselineStorageReadinessService(
            InMemoryBaselineAssetRepository([sample_baseline_asset()])
        ),
        BaselineValidationEligibilityService(
            ValidationLookupService(
                InMemoryValidationRepository([sample_validation_report()])
            )
        ),
    )

    baseline, report = service.select_for_publish(
        source=sample_source(),
        target=sample_target(),
        profile=sample_profile(),
    )

    assert baseline.baseline_id == "baseline-crm-dev-v1"
    assert report.status.value == "passed"


def test_baseline_selection_accepts_warning_only_validation():
    service = BaselineSelectionService(
        InMemoryBaselineRepository([sample_baseline()]),
        BaselineStorageReadinessService(
            InMemoryBaselineAssetRepository([sample_baseline_asset()])
        ),
        BaselineValidationEligibilityService(
            ValidationLookupService(
                InMemoryValidationRepository(
                    [
                        sample_validation_report(
                            status=ValidationStatus.PASSED_WITH_WARNINGS
                        )
                    ]
                )
            )
        ),
    )

    baseline, report = service.select_for_publish(
        source=sample_source(),
        target=sample_target(),
        profile=sample_profile(),
    )

    assert baseline.baseline_id == "baseline-crm-dev-v1"
    assert report.status.value == "passed_with_warnings"
    assert report.warning_count == 1


def test_baseline_selection_rejects_failed_validation():
    service = BaselineSelectionService(
        InMemoryBaselineRepository([sample_baseline()]),
        BaselineStorageReadinessService(
            InMemoryBaselineAssetRepository([sample_baseline_asset()])
        ),
        BaselineValidationEligibilityService(
            ValidationLookupService(
                InMemoryValidationRepository(
                    [sample_validation_report(status=ValidationStatus.FAILED)]
                )
            )
        ),
    )

    with pytest.raises(
        DomainError,
        match="No compatible sufficiently validated sanitized baseline",
    ):
        service.select_for_publish(
            source=sample_source(),
            target=sample_target(),
            profile=sample_profile(),
        )


def test_baseline_selection_fails_when_no_compatible_baseline_exists():
    service = BaselineSelectionService(
        InMemoryBaselineRepository([]),
        BaselineStorageReadinessService(InMemoryBaselineAssetRepository([])),
        BaselineValidationEligibilityService(
            ValidationLookupService(InMemoryValidationRepository([]))
        ),
    )

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
        publish_source_resolution=build_publish_source_resolution_service(
            baselines=[],
            validation_reports=[],
        ),
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


def test_publish_request_fails_when_baseline_exists_but_is_not_validated():
    service = PublishRequestService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        environments=InMemoryTargetEnvironmentRepository([sample_target()]),
        dataset_profiles=InMemoryDatasetProfileRepository([sample_profile()]),
        jobs=InMemoryPublishJobRepository(),
        audits=InMemoryAuditEventRepository(),
        queue=InMemoryJobQueue(),
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(),
        publish_source_resolution=build_publish_source_resolution_service(
            baselines=[sample_baseline()],
            validation_reports=[
                sample_validation_report(status=ValidationStatus.NOT_VALIDATED)
            ],
        ),
        clock=FakeClock(),
        ids=SequentialIdGenerator(),
    )

    with pytest.raises(
        DomainError,
        match="No compatible sufficiently validated sanitized baseline",
    ):
        service.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-replica",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )


def test_baseline_selection_rejects_missing_materialized_assets():
    service = BaselineSelectionService(
        InMemoryBaselineRepository([sample_baseline()]),
        BaselineStorageReadinessService(InMemoryBaselineAssetRepository([])),
        BaselineValidationEligibilityService(
            ValidationLookupService(
                InMemoryValidationRepository([sample_validation_report()])
            )
        ),
    )

    with pytest.raises(
        DomainError,
        match="No compatible materially stored sanitized baseline",
    ):
        service.select_for_publish(
            source=sample_source(),
            target=sample_target(),
            profile=sample_profile(),
        )


def test_publish_request_fails_when_baseline_exists_but_has_no_materialized_assets():
    service = PublishRequestService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        environments=InMemoryTargetEnvironmentRepository([sample_target()]),
        dataset_profiles=InMemoryDatasetProfileRepository([sample_profile()]),
        jobs=InMemoryPublishJobRepository(),
        audits=InMemoryAuditEventRepository(),
        queue=InMemoryJobQueue(),
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(),
        publish_source_resolution=build_publish_source_resolution_service(
            baselines=[sample_baseline()],
            baseline_assets=[],
            validation_reports=[sample_validation_report()],
        ),
        clock=FakeClock(),
        ids=SequentialIdGenerator(),
    )

    with pytest.raises(
        DomainError,
        match="No compatible materially stored sanitized baseline",
    ):
        service.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-replica",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )
