from __future__ import annotations

from dataclasses import dataclass

from sanitized_data_platform.domain.enums import DatabaseEngine


@dataclass(frozen=True, slots=True)
class EngineAdapterSet:
    engine_type: DatabaseEngine
    metadata_discovery: object | None = None
    extraction_pipeline: object | None = None
    artifact_publish_pipeline: object | None = None
    baseline_refresh_pipeline: object | None = None
    baseline_publish_pipeline: object | None = None

    @property
    def metadata_discovery_supported(self) -> bool:
        return self.metadata_discovery is not None

    @property
    def extraction_supported(self) -> bool:
        return self.extraction_pipeline is not None

    @property
    def artifact_publish_supported(self) -> bool:
        return self.artifact_publish_pipeline is not None

    @property
    def baseline_refresh_supported(self) -> bool:
        return self.baseline_refresh_pipeline is not None

    @property
    def baseline_publish_supported(self) -> bool:
        return self.baseline_publish_pipeline is not None

    @property
    def release_ready(self) -> bool:
        return all(
            (
                self.metadata_discovery_supported,
                self.extraction_supported,
                self.artifact_publish_supported,
                self.baseline_refresh_supported,
                self.baseline_publish_supported,
            )
        )


class AdapterRegistry:
    def __init__(self) -> None:
        self._engines: dict[DatabaseEngine, EngineAdapterSet] = {}

    def register(
        self,
        *,
        engine_type: DatabaseEngine,
        metadata_discovery: object | None = None,
        extraction_pipeline: object | None = None,
        artifact_publish_pipeline: object | None = None,
        baseline_refresh_pipeline: object | None = None,
        baseline_publish_pipeline: object | None = None,
    ) -> EngineAdapterSet:
        engine = EngineAdapterSet(
            engine_type=engine_type,
            metadata_discovery=metadata_discovery,
            extraction_pipeline=extraction_pipeline,
            artifact_publish_pipeline=artifact_publish_pipeline,
            baseline_refresh_pipeline=baseline_refresh_pipeline,
            baseline_publish_pipeline=baseline_publish_pipeline,
        )
        self._engines[engine_type] = engine
        return engine

    def get(self, engine_type: DatabaseEngine) -> EngineAdapterSet | None:
        return self._engines.get(engine_type)

    def list_all(self) -> list[EngineAdapterSet]:
        return [self._engines[key] for key in sorted(self._engines, key=lambda item: item.value)]
