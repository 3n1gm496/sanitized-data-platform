import asyncio
import json

from fastapi.routing import APIRoute
from starlette.requests import Request

from sanitized_data_platform.interfaces.http.fastapi_app import create_fastapi_app

from tests.test_api_app import build_api


def _build_request(
    *,
    method: str,
    path: str,
    body: bytes = b"",
    query_string: bytes = b"",
) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string,
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


def _route(app, path: str) -> APIRoute:
    return next(route for route in app.routes if isinstance(route, APIRoute) and route.path == path)


async def _call_asgi(app, *, method: str, path: str, body: bytes = b"", headers=None):
    headers = headers or []
    messages = []
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
        },
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    chunks = [message.get("body", b"") for message in messages if message["type"] == "http.response.body"]
    return start, b"".join(chunks)


def test_fastapi_registers_healthcheck_and_api_routes():
    app = create_fastapi_app(build_api())

    paths = {route.path for route in app.routes}

    assert "/health" in paths
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/metrics" in paths
    assert "/api/v1/{path:path}" in paths


def test_fastapi_healthcheck_endpoint():
    app = create_fastapi_app(build_api())
    route = _route(app, "/health")

    response = asyncio.run(route.endpoint())

    assert response == {"status": "ok"}


def test_fastapi_lists_publish_jobs():
    app = create_fastapi_app(build_api())
    route = _route(app, "/api/v1/{path:path}")
    create_body = json.dumps(
        {
            "sourceId": "source-crm-replica",
            "targetEnvironmentId": "env-dev",
            "datasetProfileId": "profile-full-sanitized",
            "requestedBy": "developer@example.internal",
        }
    ).encode()

    create_response = asyncio.run(
        route.endpoint(
            path="jobs",
            request=_build_request(method="POST", path="/api/v1/jobs", body=create_body),
        )
    )
    list_response = asyncio.run(
        route.endpoint(
            path="jobs",
            request=_build_request(method="GET", path="/api/v1/jobs"),
        )
    )

    created_job = json.loads(create_response.body)
    jobs = json.loads(list_response.body)

    assert create_response.status_code == 202
    assert list_response.status_code == 200
    assert jobs[0]["job_id"] == created_job["job_id"]
    assert jobs[0]["status"] == "pending"


def test_fastapi_preserves_error_shape():
    app = create_fastapi_app(build_api())
    route = _route(app, "/api/v1/{path:path}")
    create_body = json.dumps(
        {
            "sourceId": "source-crm-replica",
            "targetEnvironmentId": "env-dev",
            "datasetProfileId": "profile-does-not-exist",
            "requestedBy": "developer@example.internal",
        }
    ).encode()

    response = asyncio.run(
        route.endpoint(
            path="jobs",
            request=_build_request(method="POST", path="/api/v1/jobs", body=create_body),
        )
    )

    assert response.status_code == 400
    assert json.loads(response.body) == {
        "error": "Unknown or inactive dataset profile: profile-does-not-exist"
    }


def test_fastapi_ready_probe_and_metrics_are_exposed():
    app = create_fastapi_app(
        build_api(),
        ready_probe=lambda: {"status": "degraded", "dependencies": [{"name": "database", "status": "down"}]},
        metrics_provider=lambda: {"status": "ok", "metrics": {"publishJobCount": 3}},
    )
    ready_route = _route(app, "/health/ready")
    metrics_route = _route(app, "/metrics")

    ready_response = asyncio.run(ready_route.endpoint())
    metrics_response = asyncio.run(metrics_route.endpoint())

    assert ready_response.status_code == 503
    assert json.loads(ready_response.body)["status"] == "degraded"
    assert metrics_response["metrics"]["publishJobCount"] == 3


def test_fastapi_sets_request_id_header_in_full_asgi_path():
    app = create_fastapi_app(build_api())

    start, body = asyncio.run(
        _call_asgi(
            app,
            method="GET",
            path="/api/v1/jobs",
            headers=[(b"x-request-id", b"req-123")],
        )
    )

    headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    payload = json.loads(body)

    assert start["status"] == 200
    assert headers["x-request-id"] == "req-123"
    assert isinstance(payload, list)


def test_fastapi_returns_internal_error_for_unhandled_api_exception():
    class BrokenApiApp:
        def handle(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    app = create_fastapi_app(BrokenApiApp())  # type: ignore[arg-type]

    start, body = asyncio.run(
        _call_asgi(
            app,
            method="GET",
            path="/api/v1/jobs",
        )
    )

    assert start["status"] == 500
    assert json.loads(body) == {"error": "Internal server error"}
