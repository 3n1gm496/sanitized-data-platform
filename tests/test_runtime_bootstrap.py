import asyncio
import json

from fastapi.routing import APIRoute

from sanitized_data_platform.bootstrap.demo import build_demo_runtime
from sanitized_data_platform.bootstrap.production import (
    build_sqlite_seeded_api_app,
    build_production_runtime,
    create_production_fastapi_app,
)
from sanitized_data_platform.config.settings import PlatformSettings
from tests.test_api_app import build_api


def _route(app, path: str) -> APIRoute:
    return next(route for route in app.routes if isinstance(route, APIRoute) and route.path == path)


def test_platform_settings_read_environment(monkeypatch):
    monkeypatch.setenv("SDP_SERVICE_NAME", "SDP Enterprise")
    monkeypatch.setenv("SDP_API_PORT", "8100")
    monkeypatch.setenv("SDP_LOG_JSON", "false")
    monkeypatch.setenv("SDP_ENABLED_ENGINES", "postgres")
    monkeypatch.setenv("SDP_BOOTSTRAP_MODE", "demo")

    settings = PlatformSettings.from_env()

    assert settings.service_name == "SDP Enterprise"
    assert settings.api.port == 8100
    assert settings.logging.json_format is False
    assert settings.runtime.enabled_engines == ("postgres",)
    assert settings.runtime.bootstrap_mode == "demo"


def test_build_production_runtime_uses_injected_api_and_defaults():
    runtime = build_production_runtime(
        api_app=build_api(),
        settings=PlatformSettings.from_env(),
    )

    ready = runtime.ready_probe()
    metrics = runtime.metrics_provider()

    assert ready["status"] == "ok"
    assert ready["dependencies"][0]["name"] == "control-plane-postgres"
    assert ready["dependencies"][0]["status"] in {"not_configured", "ok"}
    assert metrics["status"] == "ok"
    assert "configuredEngines" in metrics["metrics"]


def test_create_production_fastapi_app_supports_demo_bootstrap(monkeypatch):
    monkeypatch.setenv("SDP_BOOTSTRAP_MODE", "demo")
    monkeypatch.setenv("SDP_ENVIRONMENT", "local")

    app = create_production_fastapi_app()
    ready_route = _route(app, "/health/ready")
    metrics_route = _route(app, "/metrics")

    ready = asyncio.run(ready_route.endpoint())
    metrics = asyncio.run(metrics_route.endpoint())

    assert ready.status_code == 200
    assert json.loads(ready.body)["environment"] == "demo"
    assert metrics["metrics"]["publishJobCount"] >= 1


def test_demo_runtime_exposes_metrics_and_readiness():
    runtime = build_demo_runtime()

    ready = runtime.ready_probe()
    metrics = runtime.metrics_provider()

    assert ready["status"] == "ok"
    assert metrics["metrics"]["baselineCount"] >= 1


def test_sqlite_seeded_api_app_is_restart_safe(tmp_path):
    database_path = str(tmp_path / "control-plane.db")
    first = build_sqlite_seeded_api_app(database_path)

    create_response = first.handle(
        "POST",
        "/api/v1/jobs",
        body={
            "sourceId": "source-crm-replica",
            "targetEnvironmentId": "env-dev",
            "datasetProfileId": "profile-full-sanitized",
            "requestedBy": "developer@example.internal",
        },
    )

    second = build_sqlite_seeded_api_app(database_path)
    list_response = second.handle("GET", "/api/v1/jobs")

    assert create_response.status_code == 202
    assert any(item["job_id"] == create_response.body["job_id"] for item in list_response.body)
