from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sanitized_data_platform.application.dto import CreatePublishJobCommand
from sanitized_data_platform.application.services import (
    CatalogQueryService,
    JobMonitoringService,
    PublishRequestService,
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
        catalog: CatalogQueryService,
        publish_requests: PublishRequestService,
        job_monitoring: JobMonitoringService,
    ) -> None:
        self._catalog = catalog
        self._publish_requests = publish_requests
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

            if method == "POST" and path == "/api/v1/jobs":
                command = CreatePublishJobCommand(
                    source_id=body["sourceId"],
                    target_environment_id=body["targetEnvironmentId"],
                    dataset_profile_id=body["datasetProfileId"],
                    requested_by=body["requestedBy"],
                )
                job = self._publish_requests.create_job(command)
                return ApiResponse(status_code=202, body=asdict(job))

            if method == "GET" and path.startswith("/api/v1/jobs/"):
                job_id = path.removeprefix("/api/v1/jobs/")
                job = self._job_monitoring.get_job(job_id)
                return ApiResponse(status_code=200, body=asdict(job))

        except KeyError as exc:
            return ApiResponse(status_code=400, body={"error": f"Missing field: {exc.args[0]}"})
        except DomainError as exc:
            return ApiResponse(status_code=400, body={"error": str(exc)})

        return ApiResponse(status_code=404, body={"error": "Route not found"})
