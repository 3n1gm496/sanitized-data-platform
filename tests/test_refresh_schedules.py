from sanitized_data_platform.application.dto import CreateRefreshScheduleCommand
from sanitized_data_platform.application.services import (
    BaselineRefreshRequestService,
    RefreshScheduleDispatchService,
    RefreshScheduleService,
)
from sanitized_data_platform.workers.refresh_schedule_dispatch_worker import (
    RefreshScheduleDispatchWorker,
)

from tests.fakes import (
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineRefreshJobRepository,
    InMemoryBaselineRefreshQueue,
    InMemoryBaselineRefreshScheduleRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemorySystemRepository,
    SequentialIdGenerator,
    sample_profile,
    sample_source,
    sample_system,
)


def build_schedule_services():
    clock = FakeClock()
    ids = SequentialIdGenerator()
    system_repo = InMemorySystemRepository([sample_system()])
    source_repo = InMemoryDataSourceRepository([sample_source()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    refresh_job_repo = InMemoryBaselineRefreshJobRepository()
    refresh_queue = InMemoryBaselineRefreshQueue()
    refresh_schedule_repo = InMemoryBaselineRefreshScheduleRepository()
    audit_repo = InMemoryAuditEventRepository()

    refresh_requests = BaselineRefreshRequestService(
        systems=system_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        refresh_jobs=refresh_job_repo,
        refresh_queue=refresh_queue,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    refresh_schedules = RefreshScheduleService(
        systems=system_repo,
        dataset_profiles=profile_repo,
        schedules=refresh_schedule_repo,
        clock=clock,
        ids=ids,
    )
    dispatch = RefreshScheduleDispatchService(
        schedules=refresh_schedule_repo,
        refresh_jobs=refresh_job_repo,
        refresh_requests=refresh_requests,
        clock=clock,
    )
    return (
        refresh_schedules,
        dispatch,
        refresh_job_repo,
        refresh_queue,
    )


def test_refresh_schedule_creation_and_listing():
    refresh_schedules, _, _, _ = build_schedule_services()

    created = refresh_schedules.create_schedule(
        CreateRefreshScheduleCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            interval_minutes=60,
            created_by="steward@example.internal",
        )
    )
    listed = refresh_schedules.list_schedules()

    assert created.schedule_id == "refresh-schedule-1"
    assert created.status == "enabled"
    assert listed[0].schedule_id == created.schedule_id


def test_dispatch_due_schedule_creates_refresh_job():
    refresh_schedules, dispatch, refresh_job_repo, refresh_queue = build_schedule_services()
    schedule = refresh_schedules.create_schedule(
        CreateRefreshScheduleCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            interval_minutes=60,
            created_by="steward@example.internal",
        )
    )

    dispatched = dispatch.dispatch_due_schedules()
    created_job = refresh_job_repo.get_by_id(dispatched[0].job_id)

    assert dispatched[0].refresh_schedule_id == schedule.schedule_id
    assert dispatched[0].trigger_type == "scheduled"
    assert refresh_queue.dequeue() == dispatched[0].job_id
    assert created_job is not None
    assert created_job.refresh_schedule_id == schedule.schedule_id


def test_dispatch_skips_duplicate_when_pending_job_exists():
    refresh_schedules, dispatch, refresh_job_repo, _ = build_schedule_services()
    schedule = refresh_schedules.create_schedule(
        CreateRefreshScheduleCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            interval_minutes=60,
            created_by="steward@example.internal",
        )
    )

    first_dispatch = dispatch.dispatch_due_schedules()
    second_dispatch = dispatch.dispatch_due_schedules()

    assert len(first_dispatch) == 1
    assert second_dispatch == []
    assert refresh_job_repo.get_by_id(first_dispatch[0].job_id) is not None
    assert first_dispatch[0].refresh_schedule_id == schedule.schedule_id


def test_refresh_schedule_dispatch_worker_runs_dispatch_cycle():
    refresh_schedules, dispatch, _, _ = build_schedule_services()
    refresh_schedules.create_schedule(
        CreateRefreshScheduleCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            interval_minutes=60,
            created_by="steward@example.internal",
        )
    )
    worker = RefreshScheduleDispatchWorker(dispatch)

    dispatched = worker.dispatch_due_schedules()

    assert len(dispatched) == 1
    assert dispatched[0].trigger_type == "scheduled"
