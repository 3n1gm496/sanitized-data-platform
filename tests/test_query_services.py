from sanitized_data_platform.application.services import (
    MetadataQueryService,
    PolicyCoverageQueryService,
    PolicyQueryService,
)

from tests.fakes import (
    FakeClock,
    InMemoryDataSourceRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryTransformationPolicyRepository,
    build_coverage_evaluation_service,
    sample_metadata_objects,
    sample_source,
    sample_transformation_policies,
)


def test_metadata_query_lists_objects_for_system():
    service = MetadataQueryService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        metadata_catalog=InMemoryMetadataCatalogRepository(sample_metadata_objects()),
    )

    result = service.list_metadata_objects("crm")

    assert result.system_id == "crm"
    assert result.source_id == "source-crm-replica"
    assert [item.qualified_name for item in result.items] == [
        "crm.customers",
        "crm.customers.email",
        "crm.customers.status",
    ]


def test_policy_query_filters_by_system_object_and_column():
    service = PolicyQueryService(
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


def test_policy_coverage_query_returns_mvp_friendly_report():
    clock = FakeClock()
    service = PolicyCoverageQueryService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        coverage=build_coverage_evaluation_service(clock=clock),
    )

    result = service.get_policy_coverage("crm")

    assert result.system_id == "crm"
    assert result.publish_ready is True
    assert result.blocking_gap_count == 0
    assert result.informational_gap_count == 1
    assert result.gaps[0].gap_type == "missing_classification"
