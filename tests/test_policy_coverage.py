import pytest

from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import (
    PolicyCoverageEvaluationService,
    PublishReadinessValidationService,
    PublishRequestService,
)
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryClassificationRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryJobQueue,
    InMemoryMetadataCatalogRepository,
    InMemoryPublishJobRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryTransformationPolicyRepository,
    SequentialIdGenerator,
    build_publish_source_resolution_service,
    sample_metadata_objects,
    sample_profile,
    sample_sensitivity_tags,
    sample_source,
    sample_target,
    sample_transformation_policies,
)


def build_coverage_service(*, tags=None, policies=None, clock=None):
    service_clock = clock or FakeClock()
    return PolicyCoverageEvaluationService(
        metadata_catalog=InMemoryMetadataCatalogRepository(sample_metadata_objects()),
        classifications=InMemoryClassificationRepository(
            sample_sensitivity_tags() if tags is None else tags
        ),
        policies=InMemoryTransformationPolicyRepository(
            sample_transformation_policies() if policies is None else policies
        ),
        clock=service_clock,
    )


def test_policy_coverage_is_publish_ready_when_sensitive_columns_have_policies():
    clock = FakeClock()
    coverage = build_coverage_service(clock=clock)

    report = coverage.evaluate_for_source(sample_source())

    assert report.is_publish_ready is True
    assert report.covered_object_count == 1
    assert [gap.gap_type for gap in report.informational_gaps] == ["missing_classification"]


def test_policy_coverage_reports_blocking_gap_when_sensitive_column_has_no_policy():
    clock = FakeClock()
    coverage = build_coverage_service(policies=[], clock=clock)

    report = coverage.evaluate_for_source(sample_source())

    assert report.is_publish_ready is False
    assert [gap.gap_type for gap in report.blocking_gaps] == [
        "missing_transformation_policy"
    ]
    assert report.blocking_gaps[0].object_name == "crm.customers.email"


def test_policy_coverage_reports_informational_gap_for_unclassified_column():
    clock = FakeClock()
    coverage = build_coverage_service(clock=clock)

    report = coverage.evaluate_for_source(sample_source())

    assert [gap.object_name for gap in report.informational_gaps] == [
        "crm.customers.status"
    ]


def test_publish_request_is_refused_when_blocking_policy_gap_exists():
    source_repo = InMemoryDataSourceRepository([sample_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()

    readiness = PublishReadinessValidationService(
        build_coverage_service(policies=[], clock=clock)
    )
    service = PublishRequestService(
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        policy=AllowAllPolicy(),
        readiness=readiness,
        publish_source_resolution=build_publish_source_resolution_service(),
        clock=clock,
        ids=ids,
    )

    with pytest.raises(DomainError, match="blocking policy coverage gaps exist"):
        service.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-replica",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )

    assert queue.dequeue() is None
    assert audit_repo.list_for_subject("job-1") == []
