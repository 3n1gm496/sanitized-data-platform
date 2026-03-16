from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sanitized_data_platform.application.dto import (
    CreateExtractionJobCommand,
    CreatePublishJobCommand,
    CreateRefreshScheduleCommand,
    PreviewExtractionPlanCommand,
)
from sanitized_data_platform.application.services import (
    BaselineQueryService,
    BaselineRefreshMonitoringService,
    BaselineRefreshRequestService,
    CatalogQueryService,
    ClassificationQueryService,
    ExtractionJobMonitoringService,
    ExtractionJobRequestService,
    ExtractionArtifactQueryService,
    ExtractionPlanPreviewService,
    ExtractionPlanSnapshotQueryService,
    GovernanceSummaryQueryService,
    JobMonitoringService,
    LineageQueryService,
    MetadataQueryService,
    PolicyCoverageQueryService,
    PolicyQueryService,
    PublishRequestService,
    RelationshipQueryService,
    RefreshScheduleService,
    ValidationQueryService,
)
from sanitized_data_platform.domain.errors import DomainError


@dataclass(frozen=True, slots=True)
class ApiResponse:
    status_code: int
    body: Any


class ApiApp:
    """A small HTTP-like adapter skeleton that can later be mapped to a real framework."""

    def __init__(
        self,
        *,
        baselines: BaselineQueryService,
        baseline_refresh_monitoring: BaselineRefreshMonitoringService,
        baseline_refresh_requests: BaselineRefreshRequestService,
        catalog: CatalogQueryService,
        classification_queries: ClassificationQueryService,
        extraction_job_monitoring: ExtractionJobMonitoringService,
        extraction_job_requests: ExtractionJobRequestService,
        extraction_artifacts: ExtractionArtifactQueryService,
        extraction_plan_previews: ExtractionPlanPreviewService,
        extraction_plan_snapshots: ExtractionPlanSnapshotQueryService,
        governance_summary_queries: GovernanceSummaryQueryService,
        lineage_queries: LineageQueryService,
        metadata_queries: MetadataQueryService,
        relationship_queries: RelationshipQueryService,
        policy_queries: PolicyQueryService,
        policy_coverage_queries: PolicyCoverageQueryService,
        publish_requests: PublishRequestService,
        refresh_schedules: RefreshScheduleService,
        validation_queries: ValidationQueryService,
        job_monitoring: JobMonitoringService,
    ) -> None:
        self._baselines = baselines
        self._baseline_refresh_monitoring = baseline_refresh_monitoring
        self._baseline_refresh_requests = baseline_refresh_requests
        self._catalog = catalog
        self._classification_queries = classification_queries
        self._extraction_job_monitoring = extraction_job_monitoring
        self._extraction_job_requests = extraction_job_requests
        self._extraction_artifacts = extraction_artifacts
        self._extraction_plan_previews = extraction_plan_previews
        self._extraction_plan_snapshots = extraction_plan_snapshots
        self._governance_summary_queries = governance_summary_queries
        self._lineage_queries = lineage_queries
        self._metadata_queries = metadata_queries
        self._relationship_queries = relationship_queries
        self._policy_queries = policy_queries
        self._policy_coverage_queries = policy_coverage_queries
        self._publish_requests = publish_requests
        self._refresh_schedules = refresh_schedules
        self._validation_queries = validation_queries
        self._job_monitoring = job_monitoring

    def handle(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> ApiResponse:
        query = query or {}
        body = body or {}

        try:
            if method == "GET" and path == "/api/v1/systems":
                systems = [asdict(item) for item in self._catalog.list_systems()]
                return ApiResponse(status_code=200, body=systems)

            if method == "GET" and path == "/api/v1/environments":
                environments = [asdict(item) for item in self._catalog.list_environments()]
                return ApiResponse(status_code=200, body=environments)

            if method == "GET" and path == "/api/v1/dataset-profiles":
                profiles = self._catalog.list_dataset_profiles(
                    source_id=query.get("sourceId"),
                    target_environment_id=query.get("targetEnvironmentId"),
                )
                return ApiResponse(
                    status_code=200,
                    body=[asdict(profile) for profile in profiles],
                )

            if method == "POST" and path == "/api/v1/extraction-plans/preview":
                command = PreviewExtractionPlanCommand(
                    source_id=body["sourceId"],
                    root_object_id=body["rootObjectId"],
                    criteria=body.get("criteria", []),
                    selected_columns=body.get("selectedColumns"),
                    include_related=body.get("includeRelated", False),
                    max_depth=body.get("maxDepth", 1),
                )
                preview = self._extraction_plan_previews.preview_plan(command)
                return ApiResponse(status_code=200, body=asdict(preview))

            if method == "POST" and path == "/api/v1/extraction-jobs":
                command = CreateExtractionJobCommand(
                    source_id=body["sourceId"],
                    root_object_id=body["rootObjectId"],
                    criteria=body.get("criteria", []),
                    include_related=body.get("includeRelated", False),
                    max_depth=body.get("maxDepth", 1),
                    requested_by=body["requestedBy"],
                    selected_columns=body.get("selectedColumns"),
                )
                job = self._extraction_job_requests.create_job(command)
                return ApiResponse(status_code=202, body=asdict(job))

            if method == "GET" and path.startswith("/api/v1/extraction-plan-snapshots/"):
                snapshot_id = path.removeprefix("/api/v1/extraction-plan-snapshots/")
                snapshot = self._extraction_plan_snapshots.get_snapshot(snapshot_id)
                return ApiResponse(status_code=200, body=asdict(snapshot))

            if method == "GET" and path == "/api/v1/extraction-jobs":
                jobs = self._extraction_job_monitoring.list_jobs()
                return ApiResponse(status_code=200, body=[asdict(job) for job in jobs])

            if method == "GET" and path.startswith("/api/v1/extraction-jobs/") and path.endswith("/lineage"):
                job_id = path.removeprefix("/api/v1/extraction-jobs/").removesuffix("/lineage")
                lineage = self._lineage_queries.get_extraction_job_lineage(job_id)
                return ApiResponse(status_code=200, body=asdict(lineage))

            if method == "GET" and path.startswith("/api/v1/extraction-jobs/") and path.endswith("/artifact"):
                job_id = path.removeprefix("/api/v1/extraction-jobs/").removesuffix("/artifact")
                artifact = self._extraction_artifacts.get_artifact_for_job(job_id)
                return ApiResponse(status_code=200, body=asdict(artifact))

            if method == "GET" and path.startswith("/api/v1/extraction-jobs/"):
                job_id = path.removeprefix("/api/v1/extraction-jobs/")
                job = self._extraction_job_monitoring.get_job(job_id)
                return ApiResponse(status_code=200, body=asdict(job))

            if method == "GET" and path == "/api/v1/baselines":
                baselines = self._baselines.list_baselines(
                    system_id=query.get("systemId"),
                    target_environment_type=query.get("targetEnvironmentType"),
                    dataset_profile_id=query.get("datasetProfileId"),
                )
                return ApiResponse(status_code=200, body=asdict(baselines))

            if method == "GET" and path.startswith("/api/v1/baselines/") and path.endswith("/lineage"):
                baseline_id = path.removeprefix("/api/v1/baselines/").removesuffix("/lineage")
                lineage = self._lineage_queries.get_baseline_lineage(baseline_id)
                return ApiResponse(status_code=200, body=asdict(lineage))

            if method == "GET" and path.startswith("/api/v1/baselines/") and path.endswith("/validation"):
                baseline_id = path.removeprefix("/api/v1/baselines/").removesuffix("/validation")
                report = self._validation_queries.get_validation_report_for_baseline(baseline_id)
                return ApiResponse(status_code=200, body=asdict(report))

            if method == "GET" and path.startswith("/api/v1/baselines/"):
                baseline_id = path.removeprefix("/api/v1/baselines/")
                baseline = self._baselines.get_baseline(baseline_id)
                return ApiResponse(status_code=200, body=asdict(baseline))

            if method == "POST" and path == "/api/v1/refresh-schedules":
                command = CreateRefreshScheduleCommand(
                    system_id=body["systemId"],
                    dataset_profile_id=body["datasetProfileId"],
                    target_environment_type=body["targetEnvironmentType"],
                    interval_minutes=body["intervalMinutes"],
                    created_by=body["createdBy"],
                )
                schedule = self._refresh_schedules.create_schedule(command)
                return ApiResponse(status_code=202, body=asdict(schedule))

            if method == "GET" and path == "/api/v1/refresh-schedules":
                schedules = self._refresh_schedules.list_schedules()
                return ApiResponse(
                    status_code=200,
                    body=[asdict(schedule) for schedule in schedules],
                )

            if method == "POST" and path == "/api/v1/baseline-refresh-jobs":
                from sanitized_data_platform.application.dto import CreateBaselineRefreshJobCommand

                command = CreateBaselineRefreshJobCommand(
                    system_id=body["systemId"],
                    dataset_profile_id=body["datasetProfileId"],
                    target_environment_type=body["targetEnvironmentType"],
                    requested_by=body["requestedBy"],
                    trigger_type=body.get("triggerType", "manual"),
                )
                job = self._baseline_refresh_requests.create_job(command)
                return ApiResponse(status_code=202, body=asdict(job))

            if method == "GET" and path == "/api/v1/baseline-refresh-jobs":
                jobs = self._baseline_refresh_monitoring.list_jobs()
                return ApiResponse(
                    status_code=200,
                    body=[asdict(job) for job in jobs],
                )

            if method == "GET" and path.startswith("/api/v1/baseline-refresh-jobs/"):
                job_id = path.removeprefix("/api/v1/baseline-refresh-jobs/")
                job = self._baseline_refresh_monitoring.get_job(job_id)
                return ApiResponse(status_code=200, body=asdict(job))

            if method == "GET" and path.startswith("/api/v1/metadata/systems/") and path.endswith("/relationships"):
                system_id = path.removeprefix("/api/v1/metadata/systems/").removesuffix("/relationships")
                relationships = self._relationship_queries.list_relationships(
                    system_id,
                    object_id=query.get("objectId"),
                    relationship_type=query.get("relationshipType"),
                )
                return ApiResponse(status_code=200, body=asdict(relationships))

            if method == "GET" and path.startswith("/api/v1/metadata/systems/") and path.endswith("/classifications"):
                system_id = path.removeprefix("/api/v1/metadata/systems/").removesuffix("/classifications")
                classifications = self._classification_queries.list_classifications(
                    system_id,
                    object_id=query.get("objectId"),
                    classification_status=query.get("classificationStatus"),
                    sensitivity_tag=query.get("sensitivityTag"),
                )
                return ApiResponse(status_code=200, body=asdict(classifications))

            if method == "GET" and path.startswith("/api/v1/metadata/systems/") and path.endswith("/governance-summary"):
                system_id = path.removeprefix("/api/v1/metadata/systems/").removesuffix("/governance-summary")
                summary = self._governance_summary_queries.list_governance_summary(system_id)
                return ApiResponse(status_code=200, body=asdict(summary))

            if method == "GET" and path.startswith("/api/v1/metadata/systems/"):
                system_id = path.removeprefix("/api/v1/metadata/systems/")
                metadata = self._metadata_queries.list_metadata_objects(system_id)
                return ApiResponse(status_code=200, body=asdict(metadata))

            if method == "GET" and path == "/api/v1/policies":
                policies = self._policy_queries.list_transformation_policies(
                    system_id=query.get("systemId"),
                    object_name=query.get("objectName"),
                    column_name=query.get("columnName"),
                    target_mode=query.get("targetMode"),
                )
                return ApiResponse(status_code=200, body=asdict(policies))

            if method == "GET" and path.startswith("/api/v1/policy-coverage/"):
                system_id = path.removeprefix("/api/v1/policy-coverage/")
                report = self._policy_coverage_queries.get_policy_coverage(system_id)
                return ApiResponse(status_code=200, body=asdict(report))

            if method == "POST" and path == "/api/v1/jobs":
                command = CreatePublishJobCommand(
                    source_id=body["sourceId"],
                    target_environment_id=body["targetEnvironmentId"],
                    dataset_profile_id=body["datasetProfileId"],
                    requested_by=body["requestedBy"],
                )
                job = self._publish_requests.create_job(command)
                return ApiResponse(status_code=202, body=asdict(job))

            if method == "GET" and path.startswith("/api/v1/jobs/") and path.endswith("/lineage"):
                job_id = path.removeprefix("/api/v1/jobs/").removesuffix("/lineage")
                lineage = self._lineage_queries.get_publish_job_lineage(job_id)
                return ApiResponse(status_code=200, body=asdict(lineage))

            if method == "GET" and path.startswith("/api/v1/jobs/"):
                job_id = path.removeprefix("/api/v1/jobs/")
                job = self._job_monitoring.get_job(job_id)
                return ApiResponse(status_code=200, body=asdict(job))

        except KeyError as exc:
            return ApiResponse(status_code=400, body={"error": f"Missing field: {exc.args[0]}"})
        except DomainError as exc:
            return ApiResponse(status_code=400, body={"error": str(exc)})

        return ApiResponse(status_code=404, body={"error": "Route not found"})
