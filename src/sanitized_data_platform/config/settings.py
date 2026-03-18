from __future__ import annotations

import os
from dataclasses import dataclass


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _read_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class ApiRuntimeSettings:
    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = "INFO"
    json_format: bool = True


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    poll_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 30
    burst_size: int = 1


@dataclass(frozen=True, slots=True)
class StorageSettings:
    artifact_root: str = "/var/lib/sanitized-data-platform/artifacts"
    baseline_asset_root: str = "/var/lib/sanitized-data-platform/baselines"


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    control_plane_dsn: str | None = None
    connect_timeout_seconds: int = 10


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    environment: str = "production"
    bootstrap_mode: str = "production"
    enabled_engines: tuple[str, ...] = ("postgres", "oracle")


@dataclass(frozen=True, slots=True)
class PlatformSettings:
    service_name: str
    service_version: str
    api: ApiRuntimeSettings
    logging: LoggingSettings
    workers: WorkerSettings
    storage: StorageSettings
    database: DatabaseSettings
    runtime: RuntimeSettings

    @classmethod
    def from_env(cls) -> PlatformSettings:
        return cls(
            service_name=os.getenv("SDP_SERVICE_NAME", "Sanitized Data Platform"),
            service_version=os.getenv("SDP_SERVICE_VERSION", "0.1.0"),
            api=ApiRuntimeSettings(
                host=os.getenv("SDP_API_HOST", "0.0.0.0"),
                port=_read_int("SDP_API_PORT", 8000),
                public_base_url=os.getenv("SDP_PUBLIC_BASE_URL", "http://127.0.0.1:8000"),
            ),
            logging=LoggingSettings(
                level=os.getenv("SDP_LOG_LEVEL", "INFO").upper(),
                json_format=_read_bool("SDP_LOG_JSON", True),
            ),
            workers=WorkerSettings(
                poll_interval_seconds=_read_int("SDP_WORKER_POLL_INTERVAL_SECONDS", 5),
                heartbeat_interval_seconds=_read_int("SDP_WORKER_HEARTBEAT_INTERVAL_SECONDS", 30),
                burst_size=_read_int("SDP_WORKER_BURST_SIZE", 1),
            ),
            storage=StorageSettings(
                artifact_root=os.getenv(
                    "SDP_ARTIFACT_ROOT",
                    "/var/lib/sanitized-data-platform/artifacts",
                ),
                baseline_asset_root=os.getenv(
                    "SDP_BASELINE_ASSET_ROOT",
                    "/var/lib/sanitized-data-platform/baselines",
                ),
            ),
            database=DatabaseSettings(
                control_plane_dsn=os.getenv("SDP_CONTROL_PLANE_DSN"),
                connect_timeout_seconds=_read_int("SDP_DB_CONNECT_TIMEOUT_SECONDS", 10),
            ),
            runtime=RuntimeSettings(
                environment=os.getenv("SDP_ENVIRONMENT", "production"),
                bootstrap_mode=os.getenv("SDP_BOOTSTRAP_MODE", "production"),
                enabled_engines=_read_csv("SDP_ENABLED_ENGINES", ("postgres", "oracle")),
            ),
        )
