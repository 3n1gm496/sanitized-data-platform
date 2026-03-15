from sanitized_data_platform.application.services import (
    CatalogQueryService,
    JobMonitoringService,
    MetadataQueryService,
    PolicyCoverageQueryService,
    PolicyCoverageEvaluationService,
    PolicyQueryService,
    PublishRequestService,
)
from sanitized_data_platform.interfaces.api.app import ApiApp

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineRepository,
    InMemoryClassificationRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryJobQueue,
    InMemoryMetadataCatalogRepository,
    InMemoryPublishJobRepository,
    InMemorySystemRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryTransformationPolicyRepository,
    SequentialIdGenerator,
    build_publish_source_resolution_service,
    build_readiness_service,
    sample_baseline,
    sample_metadata_objects,
    sample_profile,
    sample_sensitivity_tags,
    sample_source,
    sample_system,
    sample_target,
    sample_transformation_policies,
)


def build_api() -> ApiApp:
    source_repo = InMemoryDataSourceRepository([sample_source()])
    system_repo = InMemorySystemRepository([sample_system()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_baseline()])
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()

    catalog = CatalogQueryService(system_repo, source_repo, target_repo, profile_repo)
    coverage = PolicyCoverageEvaluationService(
        metadata_catalog=InMemoryMetadataCatalogRepository(sample_metadata_objects()),
        policies=InMemoryTransformationPolicyRepository(sample_transformation_policies()),
        classifications=InMemoryClassificationRepository(sample_sensitivity_tags()),
        clock=clock,
    )
    requests = PublishRequestService(
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(clock=clock),
        publish_source_resolution=build_publish_source_resolution_service(),
        clock=clock,
        ids=ids,
    )
    monitoring = JobMonitoringService(job_repo, audit_repo)
    metadata_queries = MetadataQueryService(
        systems=system_repo,
        data_sources=source_repo,
        metadata_catalog=InMemoryMetadataCatalogRepository(sample_metadata_objects()),
    )
    policy_queries = PolicyQueryService(
        systems=system_repo,
        data_sources=source_repo,
        policies=InMemoryTransformationPolicyRepository(sample_transformation_policies()),
    )
    policy_coverage_queries = PolicyCoverageQueryService(
        systems=system_repo,
        data_sources=source_repo,
        coverage=coverage,
    )
    return ApiApp(
        catalog=catalog,
        metadata_queries=metadata_queries,
        policy_queries=policy_queries,
        policy_coverage_queries=policy_coverage_queries,
        publish_requests=requests,
        job_monitoring=monitoring,
    )


def test_api_lists_systems_and_creates_job():
    app = build_api()

    systems_response = app.handle("GET", "/api/v1/systems")
    create_response = app.handle(
        "POST",
        "/api/v1/jobs",
        body={
            "sourceId": "source-crm-replica",
            "targetEnvironmentId": "env-dev",
            "datasetProfileId": "profile-full-sanitized",
            "requestedBy": "developer@example.internal",
        },
    )

    assert systems_response.status_code == 200
    assert systems_response.body[0]["name"] == "CRM"
    assert create_response.status_code == 202
    assert create_response.body["status"] == "pending"
    assert create_response.body["sanitized_baseline_id"] == "baseline-crm-dev-v1"


def test_api_exposes_metadata_policies_and_policy_coverage():
    app = build_api()

    metadata_response = app.handle("GET", "/api/v1/metadata/systems/crm")
    policies_response = app.handle(
        "GET",
        "/api/v1/policies",
        query={"systemId": "crm", "objectName": "crm.customers", "columnName": "email"},
    )
    coverage_response = app.handle("GET", "/api/v1/policy-coverage/crm")

    assert metadata_response.status_code == 200
    assert metadata_response.body["system_id"] == "crm"
    assert len(metadata_response.body["items"]) == 3

    assert policies_response.status_code == 200
    assert policies_response.body["filters"]["systemId"] == "crm"
    assert policies_response.body["items"][0]["column_name"] == "email"

    assert coverage_response.status_code == 200
    assert coverage_response.body["system_id"] == "crm"
    assert coverage_response.body["publish_ready"] is True
    assert coverage_response.body["informational_gap_count"] == 1
