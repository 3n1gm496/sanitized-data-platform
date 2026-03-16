from sanitized_data_platform.domain.entities import DataSource, System, TransformationPolicy
from sanitized_data_platform.domain.enums import DatabaseEngine

from sanitized_data_platform.application.services import (
    CatalogQueryService,
    ClassificationQueryService,
    GovernanceSummaryQueryService,
    MetadataQueryService,
    PolicyCoverageEvaluationService,
    PolicyCoverageQueryService,
    PolicyQueryService,
    RelationshipQueryService,
)
from sanitized_data_platform.domain.entities import SensitivityTag
from sanitized_data_platform.domain.enums import ClassificationStatus, TransformationType

from tests.fakes import (
    FakeClock,
    InMemoryClassificationRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemorySystemRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryTransformationPolicyRepository,
    build_coverage_evaluation_service,
    sample_classification_tags,
    sample_metadata_objects,
    sample_profile,
    sample_relationships,
    sample_sensitivity_tags,
    sample_source,
    sample_system,
    sample_target,
    sample_transformation_policies,
)


def build_governance_service(*, tags=None, policies=None):
    return GovernanceSummaryQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects(),
            sample_relationships(),
        ),
        classifications=InMemoryClassificationRepository(
            sample_sensitivity_tags() if tags is None else tags
        ),
        policies=InMemoryTransformationPolicyRepository(
            sample_transformation_policies() if policies is None else policies
        ),
        coverage=PolicyCoverageEvaluationService(
            metadata_catalog=InMemoryMetadataCatalogRepository(
                sample_metadata_objects(),
                sample_relationships(),
            ),
            classifications=InMemoryClassificationRepository(
                sample_sensitivity_tags() if tags is None else tags
            ),
            policies=InMemoryTransformationPolicyRepository(
                sample_transformation_policies() if policies is None else policies
            ),
            clock=FakeClock(),
        ),
    )


def test_metadata_query_lists_objects_for_system():
    service = MetadataQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects(),
            sample_relationships(),
        ),
    )

    result = service.list_metadata_objects("crm")

    assert result.system_id == "crm"
    assert result.source_id == "source-crm-replica"
    assert [item.qualified_name for item in result.items] == [
        "crm.customers",
        "crm.customers.email",
        "crm.customers.status",
    ]


def test_relationship_query_lists_relationships_for_system():
    service = RelationshipQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects(),
            sample_relationships(),
        ),
    )

    result = service.list_relationships("crm")

    assert result.system_id == "crm"
    assert result.source_id == "source-crm-replica"
    assert len(result.items) == 2
    assert result.items[0].relationship_type == "primary_key"


def test_relationship_query_filters_by_object_and_relationship_type():
    service = RelationshipQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects(),
            sample_relationships(),
        ),
    )

    result = service.list_relationships(
        "crm",
        object_id="column-customers-email",
        relationship_type="foreign_key",
    )

    assert result.filters == {
        "objectId": "column-customers-email",
        "relationshipType": "foreign_key",
    }
    assert len(result.items) == 1
    assert result.items[0].relationship_id.startswith("fk:")


def test_classification_query_lists_classifications_for_system():
    service = ClassificationQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        classifications=InMemoryClassificationRepository(sample_classification_tags()),
    )

    result = service.list_classifications("crm")

    assert result.system_id == "crm"
    assert result.source_id == "source-crm-replica"
    assert len(result.items) == 3


def test_classification_query_filters_by_status_and_tag():
    service = ClassificationQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        classifications=InMemoryClassificationRepository(sample_classification_tags()),
    )

    result = service.list_classifications(
        "crm",
        classification_status="non_sensitive",
        sensitivity_tag="classification.non_sensitive",
    )

    assert result.filters == {
        "classificationStatus": "non_sensitive",
        "sensitivityTag": "classification.non_sensitive",
    }
    assert len(result.items) == 1
    assert result.items[0].object_id == "column-customers-status"


def test_classification_query_filters_by_object_id():
    service = ClassificationQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        classifications=InMemoryClassificationRepository(sample_classification_tags()),
    )

    result = service.list_classifications(
        "crm",
        object_id="column-customers-status",
    )

    assert result.filters == {"objectId": "column-customers-status"}
    assert len(result.items) == 1
    assert result.items[0].classification_status == "non_sensitive"


def test_governance_summary_lists_objects_with_complete_and_missing_governance():
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
    service = build_governance_service(tags=tags)

    result = service.list_governance_summary("crm")

    email = next(item for item in result.items if item.object_id == "column-customers-email")
    status = next(item for item in result.items if item.object_id == "column-customers-status")

    assert email.coverage_state == "complete"
    assert email.policy_present is True
    assert email.policy_types == ["deterministic_pseudonymization"]
    assert status.classification_status == "non_sensitive"
    assert status.coverage_state == "complete"


def test_governance_summary_reports_missing_classification():
    service = build_governance_service()

    result = service.list_governance_summary("crm")

    status = next(item for item in result.items if item.object_id == "column-customers-status")
    assert status.classification_status == "unclassified"
    assert status.coverage_state == "informational_gap"
    assert status.gap_types == ["missing_classification"]


def test_governance_summary_reports_missing_policy():
    service = build_governance_service(policies=[])

    result = service.list_governance_summary("crm")

    email = next(item for item in result.items if item.object_id == "column-customers-email")
    assert email.classification_status == "sensitive"
    assert email.policy_present is False
    assert email.coverage_state == "blocking_gap"
    assert "missing_transformation_policy" in email.gap_types


def test_governance_summary_reports_needs_review_classification():
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
    service = build_governance_service(tags=tags)

    result = service.list_governance_summary("crm")

    email = next(item for item in result.items if item.object_id == "column-customers-email")
    assert email.classification_status == "needs_review"
    assert email.coverage_state == "blocking_gap"
    assert email.gap_types == ["classification_needs_review"]


def test_policy_query_filters_by_system_object_and_column():
    service = PolicyQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        policies=InMemoryTransformationPolicyRepository(sample_transformation_policies()),
    )

    result = service.list_transformation_policies(
        system_id="crm",
        object_name="crm.customers",
        column_name="email",
    )

    assert result.filters == {
        "systemId": "crm",
        "objectName": "crm.customers",
        "columnName": "email",
    }
    assert len(result.items) == 1
    assert result.items[0].transformation_type == "deterministic_pseudonymization"
    assert result.items[0].canonical_object_id is None
    assert result.items[0].legacy_object_name == "crm.customers"
    assert result.items[0].target_mode == "legacy_fallback"


def test_policy_query_exposes_canonical_target_visibility():
    source = sample_source()
    policy = TransformationPolicy(
        policy_id="policy-canonical-query",
        system_id=source.system_id,
        system_name=source.system_name,
        object_name="legacy.not-used",
        object_id="table-customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.HASHING,
    )
    service = PolicyQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([source]),
        policies=InMemoryTransformationPolicyRepository([policy]),
    )

    result = service.list_transformation_policies(system_id="crm")

    assert len(result.items) == 1
    assert result.items[0].canonical_object_id == "table-customers"
    assert result.items[0].legacy_object_name == "legacy.not-used"
    assert result.items[0].target_mode == "canonical"


def test_policy_query_filters_by_canonical_target_mode():
    source = sample_source()
    policies = [
        TransformationPolicy(
            policy_id="policy-canonical-query",
            system_id=source.system_id,
            system_name=source.system_name,
            object_name="legacy.not-used",
            object_id="table-customers",
            column_name="email",
            sensitivity_tag="pii.email",
            transformation_type=TransformationType.HASHING,
        ),
        sample_transformation_policies()[0],
    ]
    service = PolicyQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([source]),
        policies=InMemoryTransformationPolicyRepository(policies),
    )

    result = service.list_transformation_policies(
        system_id="crm",
        target_mode="canonical",
    )

    assert result.filters == {"systemId": "crm", "targetMode": "canonical"}
    assert len(result.items) == 1
    assert result.items[0].target_mode == "canonical"
    assert result.items[0].canonical_object_id == "table-customers"


def test_policy_query_filters_by_legacy_target_mode():
    source = sample_source()
    policies = [
        TransformationPolicy(
            policy_id="policy-canonical-query",
            system_id=source.system_id,
            system_name=source.system_name,
            object_name="legacy.not-used",
            object_id="table-customers",
            column_name="email",
            sensitivity_tag="pii.email",
            transformation_type=TransformationType.HASHING,
        ),
        sample_transformation_policies()[0],
    ]
    service = PolicyQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([source]),
        policies=InMemoryTransformationPolicyRepository(policies),
    )

    result = service.list_transformation_policies(
        system_id="crm",
        target_mode="legacy_fallback",
    )

    assert result.filters == {"systemId": "crm", "targetMode": "legacy_fallback"}
    assert len(result.items) == 1
    assert result.items[0].target_mode == "legacy_fallback"
    assert result.items[0].canonical_object_id is None


def test_policy_coverage_query_returns_mvp_friendly_report():
    clock = FakeClock()
    service = PolicyCoverageQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        coverage=build_coverage_evaluation_service(clock=clock),
    )

    result = service.get_policy_coverage("crm")

    assert result.system_id == "crm"
    assert result.publish_ready is True
    assert result.blocking_gap_count == 0
    assert result.informational_gap_count == 1
    assert result.gaps[0].gap_type == "missing_classification"


def test_active_source_resolution_uses_explicit_system_id():
    system_repo = InMemorySystemRepository([sample_system()])
    source_repo = InMemoryDataSourceRepository([sample_source()])

    resolved = source_repo.get_active_by_system_id("crm")
    system = system_repo.get_by_id("crm")

    assert system is not None
    assert resolved is not None
    assert resolved.system_id == system.system_id


def test_catalog_query_uses_explicit_system_id_not_derived_name():
    system = System(system_id="crm-core", name="CRM")
    source = DataSource(
        source_id="source-crm-replica",
        system_id="crm-core",
        system_name="CRM",
        engine_type=DatabaseEngine.POSTGRES,
        endpoint="postgresql://crm-replica.local",
        database_name="crm",
    )
    profile = sample_profile()
    profile = type(profile)(
        profile_id=profile.profile_id,
        system_id="crm-core",
        name=profile.name,
        system_name=profile.system_name,
        dataset_mode=profile.dataset_mode,
        target_environment_type=profile.target_environment_type,
        uses_sanitized_baseline=profile.uses_sanitized_baseline,
        preserve_constraints=profile.preserve_constraints,
        requires_approval=profile.requires_approval,
        active=profile.active,
    )
    service = CatalogQueryService(
        InMemorySystemRepository([system]),
        InMemoryDataSourceRepository([source]),
        InMemoryTargetEnvironmentRepository([sample_target()]),
        InMemoryDatasetProfileRepository([profile]),
    )

    result = service.list_systems()

    assert result[0].system_id == "crm-core"
    assert result[0].name == "CRM"
