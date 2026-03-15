from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import PublishRequestService
from sanitized_data_platform.workers.publish_worker import PublishWorker

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
    StubPublishPipeline,
    sample_profile,
    sample_source,
    sample_target,
)


def test_worker_processes_enqueued_job_to_completion():
    source_repo = InMemoryDataSourceRepository([sample_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()

    request_service = PublishRequestService(
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
    created = request_service.create_job(
        CreatePublishJobCommand(
            source_id="source-crm-replica",
            target_environment_id="env-dev",
            dataset_profile_id="profile-full-sanitized",
            requested_by="developer@example.internal",
        )
    )

    worker = PublishWorker(
        queue=queue,
        jobs=job_repo,
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        pipeline=StubPublishPipeline(),
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )

    processed_job_id = worker.process_next_job()
    completed_job = job_repo.get_by_id(created.job_id)
    audit_events = audit_repo.list_for_subject(created.job_id)

    assert processed_job_id == created.job_id
    assert completed_job is not None
    assert completed_job.status.value == "completed"
    assert completed_job.execution_summary["validationStatus"] == "pending-real-implementation"
    assert [event.event_type for event in audit_events] == [
        "publish_job_requested",
        "publish_job_started",
        "publish_job_completed",
    ]
