from sanitized_data_platform.adapters.postgres.control_plane import (
    ControlPlaneJsonStore,
    PostgresAuditEventRepository,
    PostgresPublishJobRepository,
    SqliteBackend,
)
from sanitized_data_platform.domain.enums import JobStatus
from sanitized_data_platform.bootstrap.production import build_sqlite_seeded_api_app
from sanitized_data_platform.bootstrap.worker_runtime import (
    PollingWorkerRunner,
    build_sqlite_seeded_worker_bundle,
    run_named_worker,
)


class DummyProcessor:
    def __init__(self, results):
        self._results = list(results)

    def process_next_job(self):
        if not self._results:
            return None
        return self._results.pop(0)


def test_polling_worker_runner_honors_burst_size():
    runner = PollingWorkerRunner(
        processor=DummyProcessor(["job-1", "job-2", "job-3"]),
        poll_interval_seconds=0,
        burst_size=2,
    )

    processed = runner.run_burst()

    assert processed == 2


def test_sqlite_seeded_worker_bundle_dispatches_due_refresh_schedule(tmp_path):
    database_path = str(tmp_path / "workers.db")
    bundle = build_sqlite_seeded_worker_bundle(
        database_path,
        postgres_connect=lambda _dsn: None,
        oracle_connect=lambda _dsn: None,
    )

    dispatched = bundle.refresh_schedule_dispatch.dispatch_due_schedules()
    api = build_sqlite_seeded_api_app(database_path)
    jobs_response = api.handle("GET", "/api/v1/baseline-refresh-jobs")

    assert len(dispatched) == 1
    assert jobs_response.status_code == 200
    assert len(jobs_response.body) >= 2


def test_stale_job_recovery_requeues_publish_job_without_active_lease(tmp_path):
    database_path = str(tmp_path / "workers.db")
    api = build_sqlite_seeded_api_app(database_path)
    create_response = api.handle(
        "POST",
        "/api/v1/jobs",
        body={
            "sourceId": "source-crm-replica",
            "targetEnvironmentId": "env-dev",
            "datasetProfileId": "profile-full-sanitized",
            "requestedBy": "developer@example.internal",
        },
    )
    store = ControlPlaneJsonStore(SqliteBackend(database_path))
    jobs = PostgresPublishJobRepository(store)
    audits = PostgresAuditEventRepository(store)
    stuck = jobs.get_by_id(create_response.body["job_id"])
    jobs.save(stuck.transition_to(JobStatus.PLANNING, updated_at=stuck.updated_at))

    bundle = build_sqlite_seeded_worker_bundle(
        database_path,
        postgres_connect=lambda _dsn: None,
        oracle_connect=lambda _dsn: None,
    )
    summary = bundle.stale_job_recovery.run_once()
    recovered = jobs.get_by_id(create_response.body["job_id"])
    events = audits.list_for_subject(create_response.body["job_id"])

    assert summary["recoveredJobCount"] >= 1
    assert recovered.status == JobStatus.PENDING
    assert any(event.event_type == "job_recovered_after_stale_lease" for event in events)


def test_run_named_worker_rejects_unknown_kind():
    try:
        run_named_worker("does-not-exist", max_cycles=1)
    except Exception as exc:
        assert "Unsupported worker kind" in str(exc)
    else:
        raise AssertionError("Expected unsupported worker kind failure")
