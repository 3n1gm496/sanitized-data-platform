from __future__ import annotations

import os
from typing import Any

from sanitized_data_platform.application.ports import (
    AuditEventRepository,
    ClockPort,
    ExtractionArtifactRepository,
    IdGeneratorPort,
)
from sanitized_data_platform.application.services import ExtractionArtifactCleanupService
from sanitized_data_platform.domain.entities import AuditEvent


class ExtractionArtifactCleanupWorker:
    """Minimal local-file cleanup runner for expired extraction artifacts."""

    def __init__(
        self,
        *,
        cleanup: ExtractionArtifactCleanupService,
        artifacts: ExtractionArtifactRepository,
        clock: ClockPort,
        audits: AuditEventRepository | None = None,
        ids: IdGeneratorPort | None = None,
    ) -> None:
        self._cleanup = cleanup
        self._artifacts = artifacts
        self._clock = clock
        self._audits = audits
        self._ids = ids

    def run_once(self) -> dict[str, Any]:
        run_at = self._clock.now()
        expired_artifacts = [
            artifact
            for artifact in self._artifacts.list_all()
            if artifact.status.value == "expired"
        ]
        missing_by_artifact_id = {
            artifact.artifact_id: (not os.path.exists(artifact.artifact_path))
            for artifact in expired_artifacts
        }
        summary = self._cleanup.cleanup_expired_artifacts()
        if self._audits is not None and self._ids is not None:
            run_id = self._ids.new_id("artifact-cleanup-run")
            self._audits.add(
                AuditEvent(
                    event_id=self._ids.new_id("audit"),
                    event_type="extraction_artifact_cleanup_completed",
                    actor="system",
                    subject_type="extraction_artifact_cleanup_run",
                    subject_id=run_id,
                    details=summary,
                    created_at=run_at,
                )
            )
            for artifact in expired_artifacts:
                stored = self._artifacts.get_by_id(artifact.artifact_id)
                if stored is None or stored.status.value != "deleted":
                    continue
                self._audits.add(
                    AuditEvent(
                        event_id=self._ids.new_id("audit"),
                        event_type="extraction_artifact_deleted",
                        actor="system",
                        subject_type="extraction_artifact",
                        subject_id=artifact.artifact_id,
                        details={
                            "runId": run_id,
                            "artifactPath": artifact.artifact_path,
                            "physicalFileMissing": missing_by_artifact_id[artifact.artifact_id],
                        },
                        created_at=run_at,
                    )
                )
            return {
                "runId": run_id,
                **summary,
            }
        return summary
