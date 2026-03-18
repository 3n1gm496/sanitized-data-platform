from __future__ import annotations

from sanitized_data_platform.application.ports import (
    AuditEventRepository,
    BaselineAssetRepository,
    BaselineRefreshJobRepository,
    BaselineRefreshPipelinePort,
    BaselineRefreshQueuePort,
    BaselineRepository,
    ClockPort,
    DataSourceRepository,
    DatasetProfileRepository,
    IdGeneratorPort,
    LineageRepository,
    SystemRepository,
    ValidationRepository,
)
from sanitized_data_platform.application.services import (
    LineageRecordingService,
    ValidationLookupService,
    resolve_active_source_for_system,
)
from sanitized_data_platform.domain.entities import (
    AuditEvent,
    BaselineTableAsset,
    SanitizedBaseline,
)
from sanitized_data_platform.domain.enums import (
    BaselineRefreshStatus,
    BaselineStatus,
    ExtractionArtifactFormat,
)
from sanitized_data_platform.domain.errors import DomainError


class BaselineRefreshWorker:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        refresh_queue: BaselineRefreshQueuePort,
        refresh_jobs: BaselineRefreshJobRepository,
        baselines: BaselineRepository,
        baseline_assets: BaselineAssetRepository,
        data_sources: DataSourceRepository,
        dataset_profiles: DatasetProfileRepository,
        pipeline: BaselineRefreshPipelinePort,
        audits: AuditEventRepository,
        lineage: LineageRepository,
        validations: ValidationRepository,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._systems = systems
        self._refresh_queue = refresh_queue
        self._refresh_jobs = refresh_jobs
        self._baselines = baselines
        self._baseline_assets = baseline_assets
        self._data_sources = data_sources
        self._dataset_profiles = dataset_profiles
        self._pipeline = pipeline
        self._audits = audits
        self._lineage = LineageRecordingService(
            lineage=lineage,
            validations=ValidationLookupService(validations),
            clock=clock,
            ids=ids,
        )
        self._clock = clock
        self._ids = ids

    def process_next_job(self) -> str | None:
        job_id = self._refresh_queue.dequeue()
        if job_id is None:
            return None

        job = self._refresh_jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Queued baseline refresh job not found: {job_id}")

        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            job.system_id,
        )
        profile = self._dataset_profiles.get_by_id(job.dataset_profile_id)
        if profile is None:
            raise DomainError(
                "Baseline refresh job references a missing dataset profile."
            )

        existing_baseline = self._find_existing_baseline(job)

        try:
            running_time = self._clock.now()
            self._refresh_queue.heartbeat(job.job_id)
            job = job.transition_to(BaselineRefreshStatus.RUNNING, updated_at=running_time)
            self._refresh_jobs.save(job)
            self._record_event(job.job_id, "baseline_refresh_started", job.requested_by, running_time)

            if existing_baseline is not None:
                self._baselines.save(
                    SanitizedBaseline(
                        baseline_id=existing_baseline.baseline_id,
                        system_id=existing_baseline.system_id,
                        system_name=existing_baseline.system_name,
                        source_id=existing_baseline.source_id,
                        dataset_profile_id=existing_baseline.dataset_profile_id,
                        target_environment_type=existing_baseline.target_environment_type,
                        engine_type=existing_baseline.engine_type,
                        version=existing_baseline.version,
                        status=BaselineStatus.REFRESHING,
                        created_at=existing_baseline.created_at,
                        refreshed_at=existing_baseline.refreshed_at,
                        active=existing_baseline.active,
                    )
                )

            result = self._pipeline.execute(
                job=job,
                source=source,
                profile=profile,
                existing_baseline=existing_baseline,
            )

            completed_time = self._clock.now()
            baseline = self._materialize_baseline(
                job=job,
                source=source,
                profile=profile,
                existing_baseline=existing_baseline,
                completed_at=completed_time,
                result=result,
            )
            if existing_baseline is None:
                self._baselines.add(baseline)
            else:
                self._baselines.save(baseline)
            self._baseline_assets.replace_for_baseline(
                baseline.baseline_id,
                self._materialize_baseline_assets(
                    baseline=baseline,
                    completed_at=completed_time,
                    result=result,
                ),
            )

            job = job.transition_to(
                BaselineRefreshStatus.COMPLETED,
                updated_at=completed_time,
                baseline_id=baseline.baseline_id,
                result_summary={
                    "baselineId": baseline.baseline_id,
                    "version": baseline.version,
                    **result,
                },
            )
            self._refresh_jobs.save(job)
            self._lineage.record_refresh_completion(job=job, baseline=baseline)
            self._record_event(
                job.job_id,
                "baseline_refresh_completed",
                job.requested_by,
                completed_time,
                details=job.result_summary,
            )
            self._refresh_queue.complete(job.job_id)
        except Exception as exc:
            failed_time = self._clock.now()
            failed_job = job.transition_to(
                BaselineRefreshStatus.FAILED,
                updated_at=failed_time,
                result_summary={"error": str(exc)},
            )
            self._refresh_jobs.save(failed_job)
            self._record_event(
                failed_job.job_id,
                "baseline_refresh_failed",
                failed_job.requested_by,
                failed_time,
                details={"error": str(exc)},
            )
            self._refresh_queue.complete(failed_job.job_id)
            raise

        return job.job_id

    def _find_existing_baseline(self, job):
        candidates = self._baselines.list_for_system(job.system_id)
        for baseline in candidates:
            if (
                baseline.dataset_profile_id == job.dataset_profile_id
                and baseline.target_environment_type == job.target_environment_type
            ):
                return baseline
        return None

    def _materialize_baseline(
        self,
        *,
        job,
        source,
        profile,
        existing_baseline,
        completed_at,
        result,
    ) -> SanitizedBaseline:
        baseline_id = (
            existing_baseline.baseline_id
            if existing_baseline is not None
            else self._ids.new_id("baseline")
        )
        created_at = (
            existing_baseline.created_at
            if existing_baseline is not None
            else completed_at
        )
        version = str(result.get("version", completed_at.strftime("%Y.%m.%d.%H%M")))
        return SanitizedBaseline(
            baseline_id=baseline_id,
            system_id=job.system_id,
            system_name=source.system_name,
            source_id=source.source_id,
            dataset_profile_id=profile.profile_id,
            target_environment_type=job.target_environment_type,
            engine_type=source.engine_type,
            version=version,
            status=BaselineStatus.ACTIVE,
            created_at=created_at,
            refreshed_at=completed_at,
            active=True,
        )

    def _record_event(
        self,
        job_id: str,
        event_type: str,
        actor: str,
        created_at,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self._audits.add(
            AuditEvent(
                event_id=self._ids.new_id("audit"),
                event_type=event_type,
                actor=actor,
                subject_type="baseline_refresh_job",
                subject_id=job_id,
                details=details or {},
                created_at=created_at,
            )
        )

    def _materialize_baseline_assets(
        self,
        *,
        baseline: SanitizedBaseline,
        completed_at,
        result: dict[str, object],
    ) -> list[BaselineTableAsset]:
        raw_assets = result.get("baselineAssets", [])
        if not isinstance(raw_assets, list):
            raise DomainError("Baseline refresh result baselineAssets must be a list.")
        assets: list[BaselineTableAsset] = []
        for index, item in enumerate(raw_assets):
            if not isinstance(item, dict):
                raise DomainError("Baseline refresh baseline asset entries must be objects.")
            artifact_path = item.get("artifactPath")
            root_object_id = item.get("rootObjectId")
            row_count = item.get("rowCount")
            if not isinstance(artifact_path, str) or not artifact_path:
                raise DomainError("Baseline refresh baseline asset requires artifactPath.")
            if not isinstance(root_object_id, str) or not root_object_id:
                raise DomainError("Baseline refresh baseline asset requires rootObjectId.")
            if not isinstance(row_count, int):
                raise DomainError("Baseline refresh baseline asset requires integer rowCount.")
            assets.append(
                BaselineTableAsset(
                    asset_id=self._ids.new_id("baseline-asset"),
                    baseline_id=baseline.baseline_id,
                    source_id=baseline.source_id,
                    root_object_id=root_object_id,
                    artifact_format=ExtractionArtifactFormat.JSONL,
                    artifact_path=artifact_path,
                    row_count=row_count,
                    created_at=completed_at,
                    checksum=(
                        item.get("checksum")
                        if isinstance(item.get("checksum"), str)
                        else None
                    ),
                    column_count=(
                        item.get("columnCount")
                        if isinstance(item.get("columnCount"), int)
                        else None
                    ),
                    import_order=(
                        item.get("importOrder")
                        if isinstance(item.get("importOrder"), int)
                        else index
                    ),
                )
            )
        return assets
