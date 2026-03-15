from sanitized_data_platform.application.services import (
    CatalogQueryService,
    JobMonitoringService,
    PublishRequestService,
)
from sanitized_data_platform.interfaces.api.app import ApiApp

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
    sample_profile,
    sample_source,
    sample_target,
)


def build_api() -> ApiApp:
    source_repo = InMemoryDataSourceRepository([sample_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()

    catalog = CatalogQueryService(source_repo, target_repo, profile_repo)
    requests = PublishRequestService(
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        policy=AllowAllPolicy(),
        clock=clock,
        ids=ids,
    )
    monitoring = JobMonitoringService(job_repo, audit_repo)
    return ApiApp(catalog=catalog, publish_requests=requests, job_monitoring=monitoring)


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
