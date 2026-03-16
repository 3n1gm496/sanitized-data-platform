from sanitized_data_platform.application.dto import CreateBaselineRefreshJobCommand
from sanitized_data_platform.application.services import (
    BaselineRefreshMonitoringService,
    BaselineRefreshRequestService,
)
from sanitized_data_platform.workers.baseline_refresh_worker import (
    BaselineRefreshWorker,
)

from tests.fakes import (
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineRefreshJobRepository,
    InMemoryBaselineRefreshQueue,
    InMemoryBaselineRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryLineageRepository,
    InMemorySystemRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    StubBaselineRefreshPipeline,
    sample_baseline,
    sample_profile,
    sample_source,
    sample_system,
    sample_validation_report,
)


def test_baseline_refresh_job_creation_and_queue_handoff():
    system_repo = InMemorySystemRepository([sample_system()])
    source_repo = InMemoryDataSourceRepository([sample_source()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    refresh_job_repo = InMemoryBaselineRefreshJobRepository()
    refresh_queue = InMemoryBaselineRefreshQueue()
    audit_repo = InMemoryAuditEventRepository()
    lineage_repo = InMemoryLineageRepository()
    clock = FakeClock()
    ids = SequentialIdGenerator()

    service = BaselineRefreshRequestService(
        systems=system_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        refresh_jobs=refresh_job_repo,
        refresh_queue=refresh_queue,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )

    job = service.create_job(
        CreateBaselineRefreshJobCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            requested_by="steward@example.internal",
        )
    )

    assert job.job_id == "baseline-refresh-1"
    assert job.status == "requested"
    assert refresh_queue.dequeue() == job.job_id


def test_baseline_refresh_monitoring_lists_and_reads_jobs():
    refresh_job_repo = InMemoryBaselineRefreshJobRepository()
    monitoring = BaselineRefreshMonitoringService(refresh_job_repo)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    request = BaselineRefreshRequestService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        dataset_profiles=InMemoryDatasetProfileRepository([sample_profile()]),
        refresh_jobs=refresh_job_repo,
        refresh_queue=InMemoryBaselineRefreshQueue(),
        audits=InMemoryAuditEventRepository(),
        clock=clock,
        ids=ids,
    )
    created = request.create_job(
        CreateBaselineRefreshJobCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            requested_by="steward@example.internal",
        )
    )

    listed = monitoring.list_jobs()
    detail = monitoring.get_job(created.job_id)

    assert listed[0].job_id == created.job_id
    assert detail.system_id == "crm"


def test_baseline_refresh_worker_processes_job_and_updates_baseline():
    system_repo = InMemorySystemRepository([sample_system()])
    source_repo = InMemoryDataSourceRepository([sample_source()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_baseline()])
    refresh_job_repo = InMemoryBaselineRefreshJobRepository()
    refresh_queue = InMemoryBaselineRefreshQueue()
    audit_repo = InMemoryAuditEventRepository()
    lineage_repo = InMemoryLineageRepository()
    clock = FakeClock()
    ids = SequentialIdGenerator()

    request = BaselineRefreshRequestService(
        systems=system_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        refresh_jobs=refresh_job_repo,
        refresh_queue=refresh_queue,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    created = request.create_job(
        CreateBaselineRefreshJobCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            requested_by="steward@example.internal",
        )
    )

    worker = BaselineRefreshWorker(
        systems=system_repo,
        refresh_queue=refresh_queue,
        refresh_jobs=refresh_job_repo,
        baselines=baseline_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        pipeline=StubBaselineRefreshPipeline(),
        audits=audit_repo,
        lineage=lineage_repo,
        validations=InMemoryValidationRepository([sample_validation_report()]),
        clock=clock,
        ids=ids,
    )

    processed_job_id = worker.process_next_job()
    refreshed_job = refresh_job_repo.get_by_id(created.job_id)
    baseline = baseline_repo.get_by_id("baseline-crm-dev-v1")
    lineage_records = lineage_repo.list_related(
        reference_type="sanitized_baseline",
        reference_id="baseline-crm-dev-v1",
    )

    assert processed_job_id == created.job_id
    assert refreshed_job is not None
    assert refreshed_job.status.value == "completed"
    assert refreshed_job.result_summary["version"] == "2026.01.02.1"
    assert baseline is not None
    assert baseline.status.value == "active"
    assert baseline.version == "2026.01.02.1"
    assert [record.event_type for record in lineage_records] == [
        "baseline_materialized",
        "baseline_validated",
    ]
