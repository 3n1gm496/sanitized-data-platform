from sanitized_data_platform.domain.entities import DataSource, System
from sanitized_data_platform.domain.enums import DatabaseEngine

from sanitized_data_platform.application.services import (
    CatalogQueryService,
    MetadataQueryService,
    PolicyCoverageQueryService,
    PolicyQueryService,
)

from tests.fakes import (
    FakeClock,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemorySystemRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryTransformationPolicyRepository,
    build_coverage_evaluation_service,
    sample_metadata_objects,
    sample_profile,
    sample_source,
    sample_system,
    sample_target,
    sample_transformation_policies,
)


def test_metadata_query_lists_objects_for_system():
    service = MetadataQueryService(
        systems=InMemorySystemRepository([sample_system()]),
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
