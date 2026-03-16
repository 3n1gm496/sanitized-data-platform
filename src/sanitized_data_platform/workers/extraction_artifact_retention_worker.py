from __future__ import annotations

from typing import Any

from sanitized_data_platform.application.ports import (
    AuditEventRepository,
    ClockPort,
    ExtractionArtifactRepository,
    IdGeneratorPort,
)
from sanitized_data_platform.application.services import ExtractionArtifactLifecycleService
from sanitized_data_platform.domain.entities import AuditEvent


class ExtractionArtifactRetentionWorker:
    """Minimal retention runner for extraction artifacts."""

    def __init__(
        self,
        *,
        lifecycle: ExtractionArtifactLifecycleService,
        artifacts: ExtractionArtifactRepository,
        clock: ClockPort,
        audits: AuditEventRepository | None = None,
        ids: IdGeneratorPort | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._artifacts = artifacts
        self._clock = clock
        self._audits = audits
        self._ids = ids

    def run_once(self) -> dict[str, Any]:
        run_at = self._clock.now()
        evaluated_count = len(self._artifacts.list_all())
        expired_count = self._lifecycle.expire_due_artifacts()

        summary = {
            "evaluatedArtifactCount": evaluated_count,
            "expiredArtifactCount": expired_count,
        }

        if self._audits is not None and self._ids is not None:
            run_id = self._ids.new_id("artifact-retention-run")
            self._audits.add(
                AuditEvent(
                    event_id=self._ids.new_id("audit"),
                    event_type="extraction_artifact_retention_completed",
                    actor="system",
                    subject_type="extraction_artifact_retention_run",
                    subject_id=run_id,
                    details=summary,
                    created_at=run_at,
                )
            )
            return {
                "runId": run_id,
                **summary,
            }

        return summary
