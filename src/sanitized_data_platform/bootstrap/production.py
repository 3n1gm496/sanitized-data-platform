from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from sanitized_data_platform.adapters.postgres.control_plane import (
    ControlPlaneJsonStore,
    PostgresArtifactPublishJobRepository,
    PostgresAuditEventRepository,
    PostgresBaselineAssetRepository,
    PostgresBaselineRefreshJobRepository,
    PostgresBaselineRefreshScheduleRepository,
    PostgresBaselineRepository,
    PostgresClassificationRepository,
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
    PostgresTransformationPolicyRepository,
    PostgresValidationRepository,
    PsycopgBackend,
    SqliteBackend,
)
from sanitized_data_platform.adapters.registry import AdapterRegistry
from sanitized_data_platform.application.services import (
    ArtifactPublishMonitoringService,
    ArtifactPublishRequestService,
    AuditQueryService,
    BaselineEligibilityExplanationService,
    BaselineQueryService,
    BaselineRefreshMonitoringService,
    BaselineRefreshRequestService,
    BaselineSelectionService,
    BaselineStorageReadinessService,
    BaselineValidationEligibilityService,
    CatalogQueryService,
    ClassificationQueryService,
    EngineCapabilityQueryService,
    ExtractionArtifactLifecycleService,
    ExtractionArtifactQueryService,
    ExtractionJobMonitoringService,
    ExtractionJobRequestService,
    ExtractionPlanPreviewService,
    ExtractionPlanSnapshotQueryService,
    ExtractionPlanningService,
    GovernanceSummaryQueryService,
    JobMonitoringService,
    LineageQueryService,
    MetadataQueryService,
    PolicyCoverageEvaluationService,
    PolicyCoverageQueryService,
    PolicyQueryService,
    PublishValidationSummaryService,
    PublishReadinessValidationService,
    PublishRequestService,
    PublishSourceResolutionService,
    RefreshScheduleService,
    RelationshipQueryService,
    ValidationLookupService,
    ValidationQueryService,
)
from sanitized_data_platform.bootstrap.demo import (
    AllowAllPolicy,
    DemoClock,
    InMemoryMetadataCatalogRepository,
    SequentialIdGenerator,
    _sample_baseline,
    _sample_baseline_asset,
    _sample_metadata_objects,
    _sample_preview_metadata_objects,
    _sample_profile,
    _sample_refresh_schedule,
    _sample_relationships,
    _sample_sensitivity_tags,
    _sample_source,
    _sample_system,
    _sample_target,
    _sample_transformation_policies,
    _sample_validation_report,
    build_demo_runtime,
)
from sanitized_data_platform.config.settings import PlatformSettings
from sanitized_data_platform.domain.entities import (
    ArtifactPublishJob,
    AuditEvent,
    BaselineRefreshJob,
    ExtractionArtifact,
    ExtractionJob,
    ExtractionPlanSnapshot,
    ExtractionRoot,
    LineageRecord,
    PublishJob,
    SelectionCriteria,
    TraversalRule,
)
from sanitized_data_platform.domain.enums import (
    BaselineRefreshStatus,
    DatabaseEngine,
    EnvironmentType,
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    ExtractionJobStatus,
    ValidationStatus,
)
from sanitized_data_platform.interfaces.api.app import ApiApp
from sanitized_data_platform.interfaces.http.fastapi_app import create_fastapi_app
from sanitized_data_platform.observability.logging import configure_logging


@dataclass(frozen=True, slots=True)
class RuntimeDependencyStatus:
    name: str
    status: str
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class ProductionRuntime:
    settings: PlatformSettings
    api_app: ApiApp
    ready_probe: Callable[[], dict[str, object]]
    metrics_provider: Callable[[], dict[str, object]]


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UuidIdGenerator:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex}"


class LeasedPollingQueue:
    def __init__(
        self,
        *,
        store: ControlPlaneJsonStore,
        lease_kind: str,
        worker_id: str,
        lease_seconds: int,
        jobs: Callable[[], list[object]],
        pending_statuses: tuple[str, ...],
    ) -> None:
        self._store = store
        self._lease_kind = lease_kind
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._jobs = jobs
        self._pending_statuses = pending_statuses

    def enqueue(self, job_id: str) -> None:
        return None

    def dequeue(self) -> str | None:
        candidates = sorted(
            [job for job in self._jobs() if job.status.value in self._pending_statuses],
            key=lambda job: job.created_at,
        )
        for job in candidates:
            if self._store.try_acquire_lease(
                lease_kind=self._lease_kind,
                job_id=job.job_id,
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            ):
                return job.job_id
        return None

    def heartbeat(self, job_id: str) -> None:
        self._store.heartbeat_lease(
            lease_kind=self._lease_kind,
            job_id=job_id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )

    def complete(self, job_id: str) -> None:
        self._store.release_lease(
            lease_kind=self._lease_kind,
            job_id=job_id,
        )


class PublishJobPollingQueue(LeasedPollingQueue):
    def __init__(
        self,
        *,
        store: ControlPlaneJsonStore,
        jobs: PostgresPublishJobRepository,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        super().__init__(
            store=store,
            lease_kind="publish_job",
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            jobs=jobs.list_all,
            pending_statuses=("pending",),
        )


class BaselineRefreshJobPollingQueue(LeasedPollingQueue):
    def __init__(
        self,
        *,
        store: ControlPlaneJsonStore,
        jobs: PostgresBaselineRefreshJobRepository,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        super().__init__(
            store=store,
            lease_kind="baseline_refresh_job",
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            jobs=jobs.list_all,
            pending_statuses=("requested",),
        )


class ExtractionJobPollingQueue(LeasedPollingQueue):
    def __init__(
        self,
        *,
        store: ControlPlaneJsonStore,
        jobs: PostgresExtractionJobRepository,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        super().__init__(
            store=store,
            lease_kind="extraction_job",
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            jobs=jobs.list_all,
            pending_statuses=("requested",),
        )


class ArtifactPublishJobPollingQueue(LeasedPollingQueue):
    def __init__(
        self,
        *,
        store: ControlPlaneJsonStore,
        jobs: PostgresArtifactPublishJobRepository,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        super().__init__(
            store=store,
            lease_kind="artifact_publish_job",
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            jobs=jobs.list_all,
            pending_statuses=("pending",),
        )


def build_sqlite_seeded_api_app(database_path: str, *, settings: PlatformSettings | None = None) -> ApiApp:
    resolved_settings = settings or PlatformSettings.from_env()
    store = ControlPlaneJsonStore(SqliteBackend(database_path))
    store.run_migrations()
    seed_demo_control_plane(store=store)
    return build_persistent_api_app(store=store, settings=resolved_settings)


def _build_ready_probe(
    settings: PlatformSettings,
    dependencies: list[RuntimeDependencyStatus],
) -> Callable[[], dict[str, object]]:
    def probe() -> dict[str, object]:
        all_ready = all(item.status in {"ok", "not_configured"} for item in dependencies)
        return {
            "status": "ok" if all_ready else "degraded",
            "environment": settings.runtime.environment,
            "service": settings.service_name,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "dependencies": [
                {"name": item.name, "status": item.status, "details": item.details}
                for item in dependencies
            ],
        }

    return probe


def _build_metrics_provider(
    settings: PlatformSettings,
    metrics: dict[str, Callable[[], int] | int],
) -> Callable[[], dict[str, object]]:
    def provider() -> dict[str, object]:
        resolved: dict[str, object] = {}
        for key, value in metrics.items():
            resolved[key] = value() if callable(value) else value
        return {
            "status": "ok",
            "service": settings.service_name,
            "environment": settings.runtime.environment,
            "metrics": resolved,
        }

    return provider


def _register_enabled_engine_capabilities(settings: PlatformSettings) -> AdapterRegistry:
    registry = AdapterRegistry()
    for engine_name in settings.runtime.enabled_engines:
        try:
            engine = DatabaseEngine(engine_name)
        except ValueError:
            continue
        registry.register(
            engine_type=engine,
            metadata_discovery=object(),
            extraction_pipeline=object(),
            artifact_publish_pipeline=object(),
            baseline_refresh_pipeline=object(),
            baseline_publish_pipeline=object(),
        )
    return registry


def _build_publish_source_resolution_service(
    baselines: PostgresBaselineRepository,
    baseline_assets: PostgresBaselineAssetRepository,
    validations: ValidationLookupService,
) -> PublishSourceResolutionService:
    return PublishSourceResolutionService(
        BaselineSelectionService(
            baselines,
            BaselineStorageReadinessService(baseline_assets),
            BaselineValidationEligibilityService(validations),
        )
    )


def _build_readiness_service(
    *,
    metadata_catalog: PostgresMetadataCatalogRepository,
    policies: PostgresTransformationPolicyRepository,
    classifications: PostgresClassificationRepository,
    clock: DemoClock,
) -> PublishReadinessValidationService:
    coverage = PolicyCoverageEvaluationService(
        metadata_catalog=metadata_catalog,
        policies=policies,
        classifications=classifications,
        clock=clock,
    )
    return PublishReadinessValidationService(coverage)


def seed_demo_control_plane(
    *,
    store: ControlPlaneJsonStore,
) -> None:
    systems = PostgresSystemRepository(store)
    if systems.get_by_id("crm") is not None:
        return

    clock = DemoClock()
    system_repo = systems
    source_repo = PostgresDataSourceRepository(store)
    target_repo = PostgresTargetEnvironmentRepository(store)
    profile_repo = PostgresDatasetProfileRepository(store)
    baseline_repo = PostgresBaselineRepository(store)
    baseline_asset_repo = PostgresBaselineAssetRepository(store)
    refresh_schedule_repo = PostgresBaselineRefreshScheduleRepository(store)
    refresh_job_repo = PostgresBaselineRefreshJobRepository(store)
    extraction_job_repo = PostgresExtractionJobRepository(store)
    extraction_snapshot_repo = PostgresExtractionPlanSnapshotRepository(store)
    extraction_artifact_repo = PostgresExtractionArtifactRepository(store)
    artifact_publish_job_repo = PostgresArtifactPublishJobRepository(store)
    publish_job_repo = PostgresPublishJobRepository(store)
    audit_repo = PostgresAuditEventRepository(store)
    lineage_repo = PostgresLineageRepository(store)
    metadata_repo = PostgresMetadataCatalogRepository(store)
    classification_repo = PostgresClassificationRepository(store)
    policy_repo = PostgresTransformationPolicyRepository(store)
    validation_repo = PostgresValidationRepository(store)

    system_repo.save(_sample_system())
    source_repo.save(_sample_source())
    target_repo.save(_sample_target())
    profile_repo.save(_sample_profile())
    baseline_repo.add(_sample_baseline())
    baseline_asset_repo.replace_for_baseline("baseline-crm-dev-v1", [_sample_baseline_asset()])
    refresh_schedule_repo.add(_sample_refresh_schedule())
    refresh_job_repo.add(
        BaselineRefreshJob.create(
            job_id="baseline-refresh-1",
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type=EnvironmentType.DEV,
            requested_by="steward@example.internal",
            created_at=clock.now(),
            trigger_type="scheduled",
            refresh_schedule_id="refresh-schedule-1",
        ).transition_to(
            BaselineRefreshStatus.COMPLETED,
            updated_at=clock.now(),
            baseline_id="baseline-crm-dev-v1",
            result_summary={"refreshStrategy": "seeded-baseline-refresh"},
        )
    )
    extraction_snapshot_repo.add(
        ExtractionPlanSnapshot(
            snapshot_id="extraction-plan-snapshot-existing",
            source_id="source-crm-replica",
            root=ExtractionRoot(
                object_id="table-customers",
                criteria=(SelectionCriteria(field_name="customer_id", operator="eq", value="42"),),
                artifact_kind=ExtractionArtifactKind.SAMPLE,
            ),
            traversal_rule=TraversalRule(include_related=False, max_depth=1),
            selected_object_ids=("table-customers",),
            selected_relationship_ids=(),
            notes=("seeded snapshot",),
            created_at=clock.now(),
            created_by="developer@example.internal",
        )
    )
    extraction_job_repo.add(
        ExtractionJob.create(
            job_id="extraction-existing",
            source_id="source-crm-replica",
            system_id="crm",
            plan_snapshot_id="extraction-plan-snapshot-existing",
            root_object_id="table-customers",
            criteria=(SelectionCriteria(field_name="customer_id", operator="eq", value="42"),),
            include_related=False,
            max_depth=1,
            requested_by="developer@example.internal",
            created_at=clock.now(),
        ).transition_to(
            status=ExtractionJobStatus.COMPLETED,
            updated_at=clock.now(),
            execution_summary={"artifactKind": "sample", "selectedObjectCount": 1},
            extraction_artifact_id="extraction-artifact-existing",
        )
    )
    extraction_artifact_repo.add(
        ExtractionArtifact(
            artifact_id="extraction-artifact-existing",
            job_id="extraction-existing",
            source_id="source-crm-replica",
            root_object_id="table:source-crm-replica:public.customers",
            kind=ExtractionArtifactKind.SAMPLE,
            artifact_format=ExtractionArtifactFormat.JSONL,
            artifact_path="/tmp/extraction-existing.jsonl",
            row_count=2,
            created_at=clock.now(),
            file_size_bytes=256,
            checksum="api-artifact-checksum",
            column_count=2,
        )
    )
    artifact_publish_job_repo.add(
        ArtifactPublishJob.create(
            job_id="artifact-publish-job-1",
            extraction_artifact_id="extraction-artifact-existing",
            source_id="source-crm-replica",
            root_object_id="table:source-crm-replica:public.customers",
            target_environment_id="env-dev",
            requested_by="developer@example.internal",
            created_at=clock.now(),
        )
    )
    publish_job_repo.add(
        PublishJob.create(
            job_id="job-1",
            source_id="source-crm-replica",
            sanitized_baseline_id="baseline-crm-dev-v1",
            baseline_validation_status=ValidationStatus.PASSED,
            baseline_validation_warning_count=0,
            baseline_validation_error_count=0,
            baseline_validated_at=datetime(2026, 1, 1, 7, tzinfo=timezone.utc),
            target_environment_id="env-dev",
            dataset_profile_id="profile-full-sanitized",
            requested_by="developer@example.internal",
            created_at=clock.now(),
        )
    )
    metadata_repo.upsert_objects(_sample_metadata_objects())
    metadata_repo.upsert_relationships(_sample_relationships())
    for item in _sample_sensitivity_tags():
        classification_repo.save(item)
    for item in _sample_transformation_policies():
        policy_repo.save(item)
    validation_repo.save(_sample_validation_report())
    audit_repo.add(
        AuditEvent(
            event_id="audit-publish-1",
            event_type="publish_job_requested",
            actor="developer@example.internal",
            subject_type="publish_job",
            subject_id="job-1",
            details={"sourceId": "source-crm-replica"},
            created_at=clock.now(),
        )
    )
    lineage_repo.add(
        LineageRecord(
            record_id="lineage-1",
            source_type="sanitized_baseline",
            source_id="baseline-crm-dev-v1",
            target_type="publish_job",
            target_id="job-1",
            event_type="baseline_published",
            created_at=clock.now(),
            details={"baselineVersion": "2026.01.01.1"},
        )
    )


def build_persistent_api_app(
    *,
    store: ControlPlaneJsonStore,
    settings: PlatformSettings,
) -> ApiApp:
    clock = SystemClock()
    ids = UuidIdGenerator()

    system_repo = PostgresSystemRepository(store)
    source_repo = PostgresDataSourceRepository(store)
    target_repo = PostgresTargetEnvironmentRepository(store)
    profile_repo = PostgresDatasetProfileRepository(store)
    baseline_repo = PostgresBaselineRepository(store)
    baseline_asset_repo = PostgresBaselineAssetRepository(store)
    refresh_schedule_repo = PostgresBaselineRefreshScheduleRepository(store)
    refresh_job_repo = PostgresBaselineRefreshJobRepository(store)
    extraction_job_repo = PostgresExtractionJobRepository(store)
    extraction_snapshot_repo = PostgresExtractionPlanSnapshotRepository(store)
    extraction_artifact_repo = PostgresExtractionArtifactRepository(store)
    artifact_publish_job_repo = PostgresArtifactPublishJobRepository(store)
    publish_job_repo = PostgresPublishJobRepository(store)
    audit_repo = PostgresAuditEventRepository(store)
    lineage_repo = PostgresLineageRepository(store)
    metadata_catalog = PostgresMetadataCatalogRepository(store)
    classifications = PostgresClassificationRepository(store)
    policies = PostgresTransformationPolicyRepository(store)
    validations = ValidationLookupService(PostgresValidationRepository(store))
    worker_id = f"api-{settings.runtime.environment}"
    lease_seconds = settings.workers.heartbeat_interval_seconds * 2

    adapter_registry = _register_enabled_engine_capabilities(settings)
    catalog = CatalogQueryService(system_repo, source_repo, target_repo, profile_repo)
    coverage = PolicyCoverageEvaluationService(
        metadata_catalog=metadata_catalog,
        policies=policies,
        classifications=classifications,
        clock=clock,
    )
    preview_catalog = InMemoryMetadataCatalogRepository(
        _sample_preview_metadata_objects(),
        _sample_relationships(),
    )

    return ApiApp(
        artifact_publish_monitoring=ArtifactPublishMonitoringService(artifact_publish_job_repo),
        artifact_publish_requests=ArtifactPublishRequestService(
            artifacts=extraction_artifact_repo,
            environments=target_repo,
            jobs=artifact_publish_job_repo,
            audits=audit_repo,
            queue=ArtifactPublishJobPollingQueue(
                store=store,
                jobs=artifact_publish_job_repo,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            ),
            clock=clock,
            ids=ids,
        ),
        audit_queries=AuditQueryService(audit_repo),
        baselines=BaselineQueryService(
            systems=system_repo,
            baselines=baseline_repo,
            baseline_assets=baseline_asset_repo,
            validations=validations,
            validation_summary=PublishValidationSummaryService(),
            eligibility=BaselineEligibilityExplanationService(),
        ),
        baseline_refresh_monitoring=BaselineRefreshMonitoringService(refresh_job_repo),
        baseline_refresh_requests=BaselineRefreshRequestService(
            systems=system_repo,
            data_sources=source_repo,
            dataset_profiles=profile_repo,
            refresh_jobs=refresh_job_repo,
            refresh_queue=BaselineRefreshJobPollingQueue(
                store=store,
                jobs=refresh_job_repo,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            ),
            audits=audit_repo,
            clock=clock,
            ids=ids,
        ),
        catalog=catalog,
        classification_queries=ClassificationQueryService(
            systems=system_repo,
            data_sources=source_repo,
            classifications=classifications,
        ),
        engine_capabilities=EngineCapabilityQueryService(adapter_registry),
        extraction_job_monitoring=ExtractionJobMonitoringService(extraction_job_repo),
        extraction_job_requests=ExtractionJobRequestService(
            data_sources=source_repo,
            extraction_jobs=extraction_job_repo,
            extraction_plan_snapshots=extraction_snapshot_repo,
            extraction_queue=ExtractionJobPollingQueue(
                store=store,
                jobs=extraction_job_repo,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            ),
            planning=ExtractionPlanningService(preview_catalog),
            audits=audit_repo,
            clock=clock,
            ids=ids,
        ),
        extraction_artifacts=ExtractionArtifactQueryService(
            jobs=extraction_job_repo,
            artifacts=extraction_artifact_repo,
            lifecycle=ExtractionArtifactLifecycleService(
                artifacts=extraction_artifact_repo,
                clock=clock,
            ),
        ),
        extraction_plan_previews=ExtractionPlanPreviewService(ExtractionPlanningService(preview_catalog)),
        extraction_plan_snapshots=ExtractionPlanSnapshotQueryService(extraction_snapshot_repo),
        governance_summary_queries=GovernanceSummaryQueryService(
            systems=system_repo,
            data_sources=source_repo,
            metadata_catalog=metadata_catalog,
            classifications=classifications,
            policies=policies,
            coverage=coverage,
        ),
        lineage_queries=LineageQueryService(lineage_repo),
        metadata_queries=MetadataQueryService(
            systems=system_repo,
            data_sources=source_repo,
            metadata_catalog=metadata_catalog,
        ),
        relationship_queries=RelationshipQueryService(
            systems=system_repo,
            data_sources=source_repo,
            metadata_catalog=metadata_catalog,
        ),
        policy_queries=PolicyQueryService(
            systems=system_repo,
            data_sources=source_repo,
            policies=policies,
        ),
        policy_coverage_queries=PolicyCoverageQueryService(
            systems=system_repo,
            data_sources=source_repo,
            coverage=coverage,
        ),
        publish_requests=PublishRequestService(
            data_sources=source_repo,
            environments=target_repo,
            dataset_profiles=profile_repo,
            jobs=publish_job_repo,
            audits=audit_repo,
            queue=PublishJobPollingQueue(
                store=store,
                jobs=publish_job_repo,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            ),
            policy=AllowAllPolicy(),
            readiness=_build_readiness_service(
                metadata_catalog=metadata_catalog,
                policies=policies,
                classifications=classifications,
                clock=clock,
            ),
            publish_source_resolution=_build_publish_source_resolution_service(
                baseline_repo,
                baseline_asset_repo,
                validations,
            ),
            clock=clock,
            ids=ids,
        ),
        refresh_schedules=RefreshScheduleService(
            systems=system_repo,
            dataset_profiles=profile_repo,
            schedules=refresh_schedule_repo,
            clock=clock,
            ids=ids,
        ),
        validation_queries=ValidationQueryService(
            baselines=baseline_repo,
            validations=validations,
        ),
        job_monitoring=JobMonitoringService(publish_job_repo, audit_repo),
    )


def build_production_runtime(
    *,
    api_app: ApiApp | None = None,
    ready_probe: Callable[[], dict[str, object]] | None = None,
    metrics_provider: Callable[[], dict[str, object]] | None = None,
    settings: PlatformSettings | None = None,
) -> ProductionRuntime:
    resolved_settings = settings or PlatformSettings.from_env()
    configure_logging(resolved_settings.logging)
    dependency_statuses: list[RuntimeDependencyStatus] = []
    persistent_store: ControlPlaneJsonStore | None = None

    if resolved_settings.database.control_plane_dsn:
        try:
            store = ControlPlaneJsonStore(PsycopgBackend(resolved_settings.database.control_plane_dsn))
            store.run_migrations()
            persistent_store = store
            dependency_statuses.append(
                RuntimeDependencyStatus(
                    name="control-plane-postgres",
                    status="ok" if store.ping() else "down",
                    details={"configured": True},
                )
            )
        except Exception as exc:
            dependency_statuses.append(
                RuntimeDependencyStatus(
                    name="control-plane-postgres",
                    status="down",
                    details={"configured": True, "error": str(exc)},
                )
            )
    else:
        dependency_statuses.append(
            RuntimeDependencyStatus(
                name="control-plane-postgres",
                status="not_configured",
                details={"configured": False},
            )
        )

    if api_app is None:
        if persistent_store is not None:
            if resolved_settings.runtime.bootstrap_mode == "seed":
                seed_demo_control_plane(store=persistent_store)
            api_app = build_persistent_api_app(store=persistent_store, settings=resolved_settings)
        elif resolved_settings.runtime.bootstrap_mode == "demo":
            demo_runtime = build_demo_runtime()
            api_app = demo_runtime.api_app
            ready_probe = ready_probe or demo_runtime.ready_probe
            metrics_provider = metrics_provider or demo_runtime.metrics_provider
        else:
            raise RuntimeError(
                "Production ApiApp wiring requires SDP_CONTROL_PLANE_DSN "
                "or an injected ApiApp. For local seeded runtime only, set SDP_BOOTSTRAP_MODE=demo."
            )

    if ready_probe is None:
        ready_probe = _build_ready_probe(
            resolved_settings,
            dependency_statuses + [RuntimeDependencyStatus(name="api", status="ok", details={})],
        )
    if metrics_provider is None:
        if persistent_store is not None:
            publish_jobs = PostgresPublishJobRepository(persistent_store)
            extraction_jobs = PostgresExtractionJobRepository(persistent_store)
            artifact_publish_jobs = PostgresArtifactPublishJobRepository(persistent_store)
            artifacts = PostgresExtractionArtifactRepository(persistent_store)
            metrics_provider = _build_metrics_provider(
                resolved_settings,
                {
                    "configuredEngines": len(resolved_settings.runtime.enabled_engines),
                    "publishJobCount": lambda: len(publish_jobs.list_all()),
                    "extractionJobCount": lambda: len(extraction_jobs.list_all()),
                    "artifactPublishJobCount": lambda: len(artifact_publish_jobs.list_all()),
                    "artifactCount": lambda: len(artifacts.list_all()),
                    "activeLeaseCount": lambda: persistent_store.count_active_leases(),
                },
            )
        else:
            metrics_provider = _build_metrics_provider(
                resolved_settings,
                {"configuredEngines": len(resolved_settings.runtime.enabled_engines)},
            )

    return ProductionRuntime(
        settings=resolved_settings,
        api_app=api_app,
        ready_probe=ready_probe,
        metrics_provider=metrics_provider,
    )


def create_production_fastapi_app():
    runtime = build_production_runtime()
    return create_fastapi_app(
        runtime.api_app,
        service_name=runtime.settings.service_name,
        service_version=runtime.settings.service_version,
        ready_probe=runtime.ready_probe,
        metrics_provider=runtime.metrics_provider,
    )
