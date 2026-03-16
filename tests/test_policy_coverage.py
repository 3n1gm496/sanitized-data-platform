import pytest

from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import (
    PolicyCoverageEvaluationService,
    PublishReadinessValidationService,
    PublishRequestService,
)
from sanitized_data_platform.domain.entities import (
    MetadataObject,
    Relationship,
    SensitivityTag,
    TransformationPolicy,
)
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import (
    ClassificationStatus,
    MetadataObjectType,
    TransformationType,
)

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


def build_relationship_aware_coverage_service(*, tags, policies, clock=None):
    service_clock = clock or FakeClock()
    return PolicyCoverageEvaluationService(
        metadata_catalog=InMemoryMetadataCatalogRepository(
            relationship_metadata_objects(),
            relationship_metadata_relationships(),
        ),
        classifications=InMemoryClassificationRepository(tags),
        policies=InMemoryTransformationPolicyRepository(policies),
        clock=service_clock,
    )


def relationship_metadata_objects() -> list[MetadataObject]:
    source = sample_source()
    return [
        MetadataObject(
            object_id="table-customers",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="customers",
            qualified_name="crm.customers",
        ),
        MetadataObject(
            object_id="table-orders",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="orders",
            qualified_name="crm.orders",
        ),
        MetadataObject(
            object_id="column-customers-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.customers.customer_id",
            container_name="crm.customers",
            parent_object_id="table-customers",
            logical_data_type="integer",
        ),
        MetadataObject(
            object_id="column-orders-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.orders.customer_id",
            container_name="crm.orders",
            parent_object_id="table-orders",
            logical_data_type="integer",
        ),
    ]


def relationship_metadata_relationships() -> list[Relationship]:
    source = sample_source()
    return [
        Relationship(
            relationship_id="fk:orders.customer_id->customers.customer_id",
            source_id=source.source_id,
            source_object_id="column-orders-customer-id",
            target_object_id="column-customers-customer-id",
            relationship_type="foreign_key",
            inferred=False,
            confidence=1.0,
        )
    ]


def relationship_sensitive_tags(
    *,
    target_status: ClassificationStatus = ClassificationStatus.SENSITIVE,
    source_status: ClassificationStatus = ClassificationStatus.SENSITIVE,
) -> list[SensitivityTag]:
    source = sample_source()
    return [
        SensitivityTag(
            tag_id="tag-customers-customer-id",
            source_id=source.source_id,
            object_id="column-customers-customer-id",
            tag_name="pii.customer_id",
            assigned_by="manual-review",
            classification_status=target_status,
            approved=(target_status != ClassificationStatus.NEEDS_REVIEW),
        ),
        SensitivityTag(
            tag_id="tag-orders-customer-id",
            source_id=source.source_id,
            object_id="column-orders-customer-id",
            tag_name="pii.customer_id",
            assigned_by="manual-review",
            classification_status=source_status,
            approved=(source_status != ClassificationStatus.NEEDS_REVIEW),
        ),
    ]


def relationship_policies(
    *,
    source_transformation: TransformationType = TransformationType.DETERMINISTIC_PSEUDONYMIZATION,
    target_transformation: TransformationType = TransformationType.DETERMINISTIC_PSEUDONYMIZATION,
) -> list[TransformationPolicy]:
    source = sample_source()
    return [
        TransformationPolicy(
            policy_id="policy-customers-customer-id",
            system_id=source.system_id,
            system_name=source.system_name,
            object_name="crm.customers",
            column_name="customer_id",
            sensitivity_tag="pii.customer_id",
            transformation_type=target_transformation,
        ),
        TransformationPolicy(
            policy_id="policy-orders-customer-id",
            system_id=source.system_id,
            system_name=source.system_name,
            object_name="crm.orders",
            column_name="customer_id",
            sensitivity_tag="pii.customer_id",
            transformation_type=source_transformation,
        ),
    ]


def test_policy_coverage_is_publish_ready_when_sensitive_columns_have_policies():
    clock = FakeClock()
    coverage = build_coverage_service(clock=clock)

    report = coverage.evaluate_for_source(sample_source())

    assert report.is_publish_ready is True
    assert report.covered_object_count == 1
    assert [gap.gap_type for gap in report.informational_gaps] == ["missing_classification"]


def test_policy_coverage_matches_transformation_policy_by_canonical_object_id():
    source = sample_source()
    policy = TransformationPolicy(
        policy_id="policy-customers-email-canonical",
        system_id=source.system_id,
        system_name=source.system_name,
        object_name="legacy.not-used",
        object_id="table-customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.HASHING,
    )
    coverage = build_coverage_service(policies=[policy], clock=FakeClock())

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is True
    assert [gap.gap_type for gap in report.blocking_gaps] == []


def test_policy_coverage_keeps_legacy_object_name_fallback_matching():
    source = sample_source()
    policy = TransformationPolicy(
        policy_id="policy-customers-email-legacy",
        system_id=source.system_id,
        system_name=source.system_name,
        object_name="CRM.CUSTOMERS",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.HASHING,
    )
    coverage = build_coverage_service(policies=[policy], clock=FakeClock())

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is True
    assert [gap.gap_type for gap in report.blocking_gaps] == []


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


def test_policy_coverage_treats_explicit_non_sensitive_columns_as_covered():
    source = sample_source()
    tags = sample_sensitivity_tags() + [
        SensitivityTag(
            tag_id="tag-status",
            source_id=source.source_id,
            object_id="column-customers-status",
            tag_name="classification.non_sensitive",
            assigned_by="manual-review",
            classification_status=ClassificationStatus.NON_SENSITIVE,
        )
    ]
    coverage = build_coverage_service(tags=tags, clock=FakeClock())

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is True
    assert report.covered_object_count == 2
    assert report.informational_gaps == ()


def test_policy_coverage_reports_blocking_gap_when_classification_needs_review():
    source = sample_source()
    tags = [
        SensitivityTag(
            tag_id="tag-email-review",
            source_id=source.source_id,
            object_id="column-customers-email",
            tag_name="pii.email",
            assigned_by="classifier",
            classification_status=ClassificationStatus.NEEDS_REVIEW,
            approved=False,
        )
    ]
    coverage = build_coverage_service(tags=tags, clock=FakeClock())

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is False
    assert [gap.gap_type for gap in report.blocking_gaps] == [
        "classification_needs_review"
    ]
    assert report.blocking_gaps[0].object_name == "crm.customers.email"


def test_policy_coverage_accepts_linked_sensitive_fields_with_consistent_policy():
    source = sample_source()
    coverage = build_relationship_aware_coverage_service(
        tags=relationship_sensitive_tags(),
        policies=relationship_policies(),
        clock=FakeClock(),
    )

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is True
    assert report.blocking_gaps == ()
    assert report.covered_object_count == 2


def test_policy_coverage_reports_linked_classification_mismatch():
    source = sample_source()
    coverage = build_relationship_aware_coverage_service(
        tags=relationship_sensitive_tags(
            target_status=ClassificationStatus.SENSITIVE,
            source_status=ClassificationStatus.NON_SENSITIVE,
        ),
        policies=relationship_policies(),
        clock=FakeClock(),
    )

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is False
    assert [gap.gap_type for gap in report.blocking_gaps] == [
        "linked_classification_mismatch"
    ]


def test_policy_coverage_reports_linked_policy_mismatch():
    source = sample_source()
    coverage = build_relationship_aware_coverage_service(
        tags=relationship_sensitive_tags(),
        policies=relationship_policies(
            source_transformation=TransformationType.HASHING,
            target_transformation=TransformationType.DETERMINISTIC_PSEUDONYMIZATION,
        ),
        clock=FakeClock(),
    )

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is False
    assert [gap.gap_type for gap in report.blocking_gaps] == [
        "linked_policy_mismatch"
    ]


def test_policy_coverage_reports_linked_sensitive_field_without_consistent_handling():
    source = sample_source()
    coverage = build_relationship_aware_coverage_service(
        tags=relationship_sensitive_tags(),
        policies=[
            relationship_policies()[0],
        ],
        clock=FakeClock(),
    )

    report = coverage.evaluate_for_source(source)

    assert report.is_publish_ready is False
    assert "missing_transformation_policy" in [
        gap.gap_type for gap in report.blocking_gaps
    ]
    assert "linked_sensitive_handling_inconsistent" in [
        gap.gap_type for gap in report.blocking_gaps
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
