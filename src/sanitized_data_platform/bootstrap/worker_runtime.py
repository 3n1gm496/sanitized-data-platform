from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from dataclasses import dataclass
from typing import Callable, Protocol

from sanitized_data_platform.adapters.oracle.artifact_publish_pipeline import (
    OracleArtifactPublishPipelineAdapter,
)
from sanitized_data_platform.adapters.oracle.baseline_publish_pipeline import (
    OracleBaselinePublishPipelineAdapter,
)
from sanitized_data_platform.adapters.oracle.baseline_refresh_pipeline import (
    OracleBaselineRefreshPipelineAdapter,
)
from sanitized_data_platform.adapters.oracle.extraction_pipeline import (
    OracleExtractionPipelineAdapter,
)
from sanitized_data_platform.adapters.postgres.artifact_publish_pipeline import (
    PostgreSQLArtifactPublishPipelineAdapter,
)
from sanitized_data_platform.adapters.postgres.baseline_publish_pipeline import (
    PostgreSQLBaselinePublishPipelineAdapter,
)
from sanitized_data_platform.adapters.postgres.baseline_refresh_pipeline import (
    PostgreSQLBaselineRefreshPipelineAdapter,
)
from sanitized_data_platform.adapters.postgres.control_plane import (
    ControlPlaneJsonStore,
    PostgresArtifactPublishJobRepository,
    PostgresAuditEventRepository,
    PostgresBaselineAssetRepository,
    PostgresBaselineRefreshJobRepository,
    PostgresBaselineRefreshScheduleRepository,
    PostgresBaselineRepository,
    PostgresDataSourceRepository,
    PostgresDatasetProfileRepository,
    PostgresExtractionArtifactRepository,
    PostgresExtractionJobRepository,
    PostgresExtractionPlanSnapshotRepository,
    PostgresLineageRepository,
    PostgresMetadataCatalogRepository,
    PostgresPublishJobRepository,
    PostgresSystemRepository,
    PostgresTargetEnvironmentRepository,
    PostgresValidationRepository,
    PsycopgBackend,
    SqliteBackend,
)
from sanitized_data_platform.adapters.postgres.extraction_pipeline import (
    PostgreSQLExtractionPipelineAdapter,
)
from sanitized_data_platform.application.services import (
    BaselineRefreshRequestService,
    ExtractionArtifactCleanupService,
    ExtractionArtifactLifecycleService,
    RefreshScheduleDispatchService,
)
from sanitized_data_platform.bootstrap.production import (
    ArtifactPublishJobPollingQueue,
    BaselineRefreshJobPollingQueue,
    ExtractionJobPollingQueue,
    PublishJobPollingQueue,
    SystemClock,
    UuidIdGenerator,
    seed_demo_control_plane,
)
from sanitized_data_platform.config.settings import PlatformSettings
from sanitized_data_platform.domain.enums import DatabaseEngine
from sanitized_data_platform.domain.enums import BaselineRefreshStatus, ExtractionJobStatus, JobStatus
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.entities import AuditEvent
from sanitized_data_platform.observability.logging import configure_logging
from sanitized_data_platform.workers.artifact_publish_worker import ArtifactPublishWorker
from sanitized_data_platform.workers.baseline_refresh_worker import BaselineRefreshWorker
from sanitized_data_platform.workers.extraction_artifact_cleanup_worker import (
    ExtractionArtifactCleanupWorker,
)
from sanitized_data_platform.workers.extraction_artifact_retention_worker import (
    ExtractionArtifactRetentionWorker,
)
from sanitized_data_platform.workers.extraction_worker import ExtractionWorker
from sanitized_data_platform.workers.publish_worker import PublishWorker
from sanitized_data_platform.workers.refresh_schedule_dispatch_worker import (
    RefreshScheduleDispatchWorker,
)


class JobProcessor(Protocol):
    def process_next_job(self) -> str | None: ...


class MaintenanceProcessor(Protocol):
    def run_once(self) -> dict[str, object]: ...


class DispatchProcessor(Protocol):
    def dispatch_due_schedules(self): ...


class RecoveryProcessor(Protocol):
    def run_once(self) -> dict[str, object]: ...


class EngineRoutedExtractionPipeline:
    def __init__(self, pipelines: dict[DatabaseEngine, object], data_sources: PostgresDataSourceRepository) -> None:
        self._pipelines = pipelines
        self._data_sources = data_sources

    def execute(self, *, job, plan):
        source = self._data_sources.get_by_id(job.source_id)
        if source is None:
            raise DomainError(f"Unknown or inactive data source: {job.source_id}")
        pipeline = self._pipelines.get(source.engine_type)
        if pipeline is None:
            raise DomainError(f"No extraction pipeline configured for engine: {source.engine_type.value}")
        return pipeline.execute(job=job, plan=plan)


class EngineRoutedArtifactPublishPipeline:
    def __init__(self, pipelines: dict[DatabaseEngine, object]) -> None:
        self._pipelines = pipelines

    def execute(self, *, job, artifact, target):
        pipeline = self._pipelines.get(target.engine_type)
        if pipeline is None:
            raise DomainError(f"No artifact publish pipeline configured for engine: {target.engine_type.value}")
        return pipeline.execute(job=job, artifact=artifact, target=target)


class EngineRoutedBaselineRefreshPipeline:
    def __init__(self, pipelines: dict[DatabaseEngine, object]) -> None:
        self._pipelines = pipelines

    def execute(self, *, job, source, profile, existing_baseline):
        pipeline = self._pipelines.get(source.engine_type)
        if pipeline is None:
            raise DomainError(f"No baseline refresh pipeline configured for engine: {source.engine_type.value}")
        return pipeline.execute(
            job=job,
            source=source,
            profile=profile,
            existing_baseline=existing_baseline,
        )


class EngineRoutedPublishPipeline:
    def __init__(self, pipelines: dict[DatabaseEngine, object]) -> None:
        self._pipelines = pipelines

    def execute(self, *, job, source, baseline, target, profile):
        pipeline = self._pipelines.get(target.engine_type)
        if pipeline is None:
            raise DomainError(f"No publish pipeline configured for engine: {target.engine_type.value}")
        return pipeline.execute(
            job=job,
            source=source,
            baseline=baseline,
            target=target,
            profile=profile,
        )


@dataclass(frozen=True, slots=True)
class WorkerBundle:
    publish: PublishWorker
    extraction: ExtractionWorker
    artifact_publish: ArtifactPublishWorker
    baseline_refresh: BaselineRefreshWorker
    refresh_schedule_dispatch: RefreshScheduleDispatchWorker
    artifact_retention: ExtractionArtifactRetentionWorker
    artifact_cleanup: ExtractionArtifactCleanupWorker
    stale_job_recovery: StaleJobRecoveryService


class PollingWorkerRunner:
    def __init__(
        self,
        *,
        processor: JobProcessor,
        poll_interval_seconds: int,
        burst_size: int = 1,
        logger: logging.Logger | None = None,
    ) -> None:
        self._processor = processor
        self._poll_interval_seconds = poll_interval_seconds
        self._burst_size = burst_size
        self._logger = logger or logging.getLogger("sanitized_data_platform.worker")

    def run_burst(self) -> int:
        processed = 0
        for _ in range(self._burst_size):
            job_id = self._processor.process_next_job()
            if job_id is None:
                break
            processed += 1
        self._logger.info("worker_burst_completed", extra={"processed_jobs": processed})
        return processed

    def run_forever(self, *, max_cycles: int | None = None) -> None:
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            processed = self.run_burst()
            cycles += 1
            if processed == 0:
                time.sleep(self._poll_interval_seconds)


class OneShotRunner:
    def __init__(self, *, processor: RecoveryProcessor) -> None:
        self._processor = processor

    def run_once(self) -> dict[str, object]:
        return self._processor.run_once()


class StaleJobRecoveryService:
    def __init__(
        self,
        *,
        store: ControlPlaneJsonStore,
        publish_jobs: PostgresPublishJobRepository,
        extraction_jobs: PostgresExtractionJobRepository,
        artifact_publish_jobs: PostgresArtifactPublishJobRepository,
        baseline_refresh_jobs: PostgresBaselineRefreshJobRepository,
        audits: PostgresAuditEventRepository,
        clock: SystemClock,
        ids: UuidIdGenerator,
    ) -> None:
        self._store = store
        self._publish_jobs = publish_jobs
        self._extraction_jobs = extraction_jobs
        self._artifact_publish_jobs = artifact_publish_jobs
        self._baseline_refresh_jobs = baseline_refresh_jobs
        self._audits = audits
        self._clock = clock
        self._ids = ids

    def run_once(self) -> dict[str, object]:
        recovered = 0
        recovered += self._recover_publish_jobs()
        recovered += self._recover_extraction_jobs()
        recovered += self._recover_artifact_publish_jobs()
        recovered += self._recover_baseline_refresh_jobs()
        return {"recoveredJobCount": recovered}

    def _recover_publish_jobs(self) -> int:
        recovered = 0
        for job in self._publish_jobs.list_all():
            if job.status not in {JobStatus.PLANNING, JobStatus.PUBLISHING}:
                continue
            if self._store.has_active_lease(lease_kind="publish_job", job_id=job.job_id):
                continue
            recovered_job = replace(job, status=JobStatus.PENDING, updated_at=self._clock.now())
            self._publish_jobs.save(recovered_job)
            self._record_recovery("publish_job", recovered_job.job_id, recovered_job.requested_by)
            recovered += 1
        return recovered

    def _recover_extraction_jobs(self) -> int:
        recovered = 0
        for job in self._extraction_jobs.list_all():
            if job.status != ExtractionJobStatus.RUNNING:
                continue
            if self._store.has_active_lease(lease_kind="extraction_job", job_id=job.job_id):
                continue
            recovered_job = replace(job, status=ExtractionJobStatus.REQUESTED, updated_at=self._clock.now())
            self._extraction_jobs.save(recovered_job)
            self._record_recovery("extraction_job", recovered_job.job_id, recovered_job.requested_by)
            recovered += 1
        return recovered

    def _recover_artifact_publish_jobs(self) -> int:
        recovered = 0
        for job in self._artifact_publish_jobs.list_all():
            if job.status != JobStatus.PUBLISHING:
                continue
            if self._store.has_active_lease(lease_kind="artifact_publish_job", job_id=job.job_id):
                continue
            recovered_job = replace(job, status=JobStatus.PENDING, updated_at=self._clock.now())
            self._artifact_publish_jobs.save(recovered_job)
            self._record_recovery("artifact_publish_job", recovered_job.job_id, recovered_job.requested_by)
            recovered += 1
        return recovered

    def _recover_baseline_refresh_jobs(self) -> int:
        recovered = 0
        for job in self._baseline_refresh_jobs.list_all():
            if job.status != BaselineRefreshStatus.RUNNING:
                continue
            if self._store.has_active_lease(lease_kind="baseline_refresh_job", job_id=job.job_id):
                continue
            recovered_job = replace(job, status=BaselineRefreshStatus.REQUESTED, updated_at=self._clock.now())
            self._baseline_refresh_jobs.save(recovered_job)
            self._record_recovery("baseline_refresh_job", recovered_job.job_id, recovered_job.requested_by)
            recovered += 1
        return recovered

    def _record_recovery(self, subject_type: str, subject_id: str, actor: str) -> None:
        self._audits.add(
            AuditEvent(
                event_id=self._ids.new_id("audit"),
                event_type="job_recovered_after_stale_lease",
                actor=actor,
                subject_type=subject_type,
                subject_id=subject_id,
                details={"recovery": "stale_lease"},
                created_at=self._clock.now(),
            )
        )


def _postgres_connect(dsn: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for PostgreSQL worker execution.") from exc
    return psycopg.connect(dsn)


def _oracle_connect(dsn: str):
    try:
        import oracledb
    except ImportError as exc:
        raise RuntimeError("python-oracledb is required for Oracle worker execution.") from exc
    return oracledb.connect(dsn)


def build_production_worker_bundle(settings: PlatformSettings | None = None) -> WorkerBundle:
    resolved_settings = settings or PlatformSettings.from_env()
    configure_logging(resolved_settings.logging)
    if not resolved_settings.database.control_plane_dsn:
        raise RuntimeError("SDP_CONTROL_PLANE_DSN is required for production workers.")
    store = ControlPlaneJsonStore(PsycopgBackend(resolved_settings.database.control_plane_dsn))
    store.run_migrations()
    if resolved_settings.runtime.bootstrap_mode == "seed":
        seed_demo_control_plane(store=store)
    return _build_worker_bundle_from_store(
        store=store,
        settings=resolved_settings,
        postgres_connect=_postgres_connect,
        oracle_connect=_oracle_connect,
    )


def build_sqlite_seeded_worker_bundle(
    database_path: str,
    *,
    settings: PlatformSettings | None = None,
    postgres_connect: Callable[[str], object] | None = None,
    oracle_connect: Callable[[str], object] | None = None,
) -> WorkerBundle:
    resolved_settings = settings or PlatformSettings.from_env()
    store = ControlPlaneJsonStore(SqliteBackend(database_path))
    store.run_migrations()
    seed_demo_control_plane(store=store)
    return _build_worker_bundle_from_store(
        store=store,
        settings=resolved_settings,
        postgres_connect=postgres_connect or _postgres_connect,
        oracle_connect=oracle_connect or _oracle_connect,
    )


def _build_worker_bundle_from_store(
    *,
    store: ControlPlaneJsonStore,
    settings: PlatformSettings,
    postgres_connect: Callable[[str], object],
    oracle_connect: Callable[[str], object],
) -> WorkerBundle:
    clock = SystemClock()
    ids = UuidIdGenerator()
    worker_id = os.getenv("SDP_WORKER_ID", f"worker-{settings.runtime.environment}")
    lease_seconds = settings.workers.heartbeat_interval_seconds * 2

    systems = PostgresSystemRepository(store)
    data_sources = PostgresDataSourceRepository(store)
    targets = PostgresTargetEnvironmentRepository(store)
    profiles = PostgresDatasetProfileRepository(store)
    baselines = PostgresBaselineRepository(store)
    baseline_assets = PostgresBaselineAssetRepository(store)
    refresh_jobs = PostgresBaselineRefreshJobRepository(store)
    refresh_schedules = PostgresBaselineRefreshScheduleRepository(store)
    extraction_jobs = PostgresExtractionJobRepository(store)
    extraction_snapshots = PostgresExtractionPlanSnapshotRepository(store)
    extraction_artifacts = PostgresExtractionArtifactRepository(store)
    artifact_publish_jobs = PostgresArtifactPublishJobRepository(store)
    publish_jobs = PostgresPublishJobRepository(store)
    audits = PostgresAuditEventRepository(store)
    lineage = PostgresLineageRepository(store)
    metadata_catalog = PostgresMetadataCatalogRepository(store)
    validations = PostgresValidationRepository(store)

    extraction_pipelines = {
        DatabaseEngine.POSTGRES: PostgreSQLExtractionPipelineAdapter(
            data_sources=data_sources,
            connect=postgres_connect,
            artifact_dir=settings.storage.artifact_root,
        ),
        DatabaseEngine.ORACLE: OracleExtractionPipelineAdapter(
            data_sources=data_sources,
            connect=oracle_connect,
            artifact_dir=settings.storage.artifact_root,
        ),
    }
    artifact_publish_pipelines = {
        DatabaseEngine.POSTGRES: PostgreSQLArtifactPublishPipelineAdapter(connect=postgres_connect),
        DatabaseEngine.ORACLE: OracleArtifactPublishPipelineAdapter(connect=oracle_connect),
    }
    baseline_refresh_pipelines = {
        DatabaseEngine.POSTGRES: PostgreSQLBaselineRefreshPipelineAdapter(
            metadata_catalog=metadata_catalog,
            data_sources=data_sources,
            connect=postgres_connect,
            artifact_dir=settings.storage.baseline_asset_root,
            clock=clock,
        ),
        DatabaseEngine.ORACLE: OracleBaselineRefreshPipelineAdapter(
            metadata_catalog=metadata_catalog,
            data_sources=data_sources,
            connect=oracle_connect,
            artifact_dir=settings.storage.baseline_asset_root,
            clock=clock,
        ),
    }
    publish_pipelines = {
        DatabaseEngine.POSTGRES: PostgreSQLBaselinePublishPipelineAdapter(
            baseline_assets=baseline_assets,
            connect=postgres_connect,
        ),
        DatabaseEngine.ORACLE: OracleBaselinePublishPipelineAdapter(
            baseline_assets=baseline_assets,
            connect=oracle_connect,
        ),
    }

    artifact_lifecycle = ExtractionArtifactLifecycleService(
        artifacts=extraction_artifacts,
        clock=clock,
    )

    publish_queue = PublishJobPollingQueue(
        store=store,
        jobs=publish_jobs,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    extraction_queue = ExtractionJobPollingQueue(
        store=store,
        jobs=extraction_jobs,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    artifact_publish_queue = ArtifactPublishJobPollingQueue(
        store=store,
        jobs=artifact_publish_jobs,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    baseline_refresh_queue = BaselineRefreshJobPollingQueue(
        store=store,
        jobs=refresh_jobs,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )

    return WorkerBundle(
        publish=PublishWorker(
            queue=publish_queue,
            jobs=publish_jobs,
            baselines=baselines,
            data_sources=data_sources,
            environments=targets,
            dataset_profiles=profiles,
            pipeline=EngineRoutedPublishPipeline(publish_pipelines),
            audits=audits,
            lineage=lineage,
            validations=validations,
            clock=clock,
            ids=ids,
        ),
        extraction=ExtractionWorker(
            queue=extraction_queue,
            jobs=extraction_jobs,
            artifacts=extraction_artifacts,
            plan_snapshots=extraction_snapshots,
            pipeline=EngineRoutedExtractionPipeline(extraction_pipelines, data_sources),
            audits=audits,
            lineage=lineage,
            validations=validations,
            clock=clock,
            ids=ids,
        ),
        artifact_publish=ArtifactPublishWorker(
            queue=artifact_publish_queue,
            jobs=artifact_publish_jobs,
            artifacts=extraction_artifacts,
            environments=targets,
            pipeline=EngineRoutedArtifactPublishPipeline(artifact_publish_pipelines),
            audits=audits,
            lineage=lineage,
            validations=validations,
            clock=clock,
            ids=ids,
        ),
        baseline_refresh=BaselineRefreshWorker(
            systems=systems,
            refresh_queue=baseline_refresh_queue,
            refresh_jobs=refresh_jobs,
            baselines=baselines,
            baseline_assets=baseline_assets,
            data_sources=data_sources,
            dataset_profiles=profiles,
            pipeline=EngineRoutedBaselineRefreshPipeline(baseline_refresh_pipelines),
            audits=audits,
            lineage=lineage,
            validations=validations,
            clock=clock,
            ids=ids,
        ),
        refresh_schedule_dispatch=RefreshScheduleDispatchWorker(
            RefreshScheduleDispatchService(
                schedules=refresh_schedules,
                refresh_jobs=refresh_jobs,
                refresh_requests=BaselineRefreshRequestService(
                    systems=systems,
                    data_sources=data_sources,
                    dataset_profiles=profiles,
                    refresh_jobs=refresh_jobs,
                    refresh_queue=baseline_refresh_queue,
                    audits=audits,
                    clock=clock,
                    ids=ids,
                ),
                clock=clock,
            )
        ),
        artifact_retention=ExtractionArtifactRetentionWorker(
            lifecycle=artifact_lifecycle,
            artifacts=extraction_artifacts,
            clock=clock,
            audits=audits,
            ids=ids,
        ),
        artifact_cleanup=ExtractionArtifactCleanupWorker(
            cleanup=ExtractionArtifactCleanupService(
                artifacts=extraction_artifacts,
                clock=clock,
            ),
            artifacts=extraction_artifacts,
            clock=clock,
            audits=audits,
            ids=ids,
        ),
        stale_job_recovery=StaleJobRecoveryService(
            store=store,
            publish_jobs=publish_jobs,
            extraction_jobs=extraction_jobs,
            artifact_publish_jobs=artifact_publish_jobs,
            baseline_refresh_jobs=refresh_jobs,
            audits=audits,
            clock=clock,
            ids=ids,
        ),
    )


def run_named_worker(
    worker_kind: str,
    *,
    settings: PlatformSettings | None = None,
    max_cycles: int | None = None,
) -> object:
    supported_kinds = {
        "publish",
        "extraction",
        "artifact_publish",
        "baseline_refresh",
        "refresh_schedule_dispatch",
        "artifact_retention",
        "artifact_cleanup",
        "stale_job_recovery",
    }
    if worker_kind not in supported_kinds:
        raise DomainError(f"Unsupported worker kind: {worker_kind}")

    resolved_settings = settings or PlatformSettings.from_env()
    bundle = build_production_worker_bundle(resolved_settings)
    logger = logging.getLogger("sanitized_data_platform.worker")

    if worker_kind == "publish":
        runner = PollingWorkerRunner(
            processor=bundle.publish,
            poll_interval_seconds=resolved_settings.workers.poll_interval_seconds,
            burst_size=resolved_settings.workers.burst_size,
            logger=logger,
        )
        runner.run_forever(max_cycles=max_cycles)
        return None
    if worker_kind == "extraction":
        runner = PollingWorkerRunner(
            processor=bundle.extraction,
            poll_interval_seconds=resolved_settings.workers.poll_interval_seconds,
            burst_size=resolved_settings.workers.burst_size,
            logger=logger,
        )
        runner.run_forever(max_cycles=max_cycles)
        return None
    if worker_kind == "artifact_publish":
        runner = PollingWorkerRunner(
            processor=bundle.artifact_publish,
            poll_interval_seconds=resolved_settings.workers.poll_interval_seconds,
            burst_size=resolved_settings.workers.burst_size,
            logger=logger,
        )
        runner.run_forever(max_cycles=max_cycles)
        return None
    if worker_kind == "baseline_refresh":
        runner = PollingWorkerRunner(
            processor=bundle.baseline_refresh,
            poll_interval_seconds=resolved_settings.workers.poll_interval_seconds,
            burst_size=resolved_settings.workers.burst_size,
            logger=logger,
        )
        runner.run_forever(max_cycles=max_cycles)
        return None
    if worker_kind == "refresh_schedule_dispatch":
        return bundle.refresh_schedule_dispatch.dispatch_due_schedules()
    if worker_kind == "artifact_retention":
        return bundle.artifact_retention.run_once()
    if worker_kind == "artifact_cleanup":
        return bundle.artifact_cleanup.run_once()
    if worker_kind == "stale_job_recovery":
        return bundle.stale_job_recovery.run_once()
    raise DomainError(f"Unsupported worker kind: {worker_kind}")


def main() -> int:
    worker_kind = os.getenv("SDP_WORKER_KIND")
    if not worker_kind:
        raise RuntimeError("SDP_WORKER_KIND is required.")
    max_cycles_raw = os.getenv("SDP_WORKER_MAX_CYCLES")
    max_cycles = None if max_cycles_raw is None else int(max_cycles_raw)
    run_named_worker(worker_kind, max_cycles=max_cycles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
