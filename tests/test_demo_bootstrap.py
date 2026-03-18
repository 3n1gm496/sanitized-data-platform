import asyncio
import json

from fastapi.routing import APIRoute
from starlette.requests import Request

from sanitized_data_platform.bootstrap.demo import build_demo_api_app, create_demo_fastapi_app


def _build_request(*, method: str, path: str, body: bytes = b"") -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


def _route(app, path: str) -> APIRoute:
    return next(route for route in app.routes if isinstance(route, APIRoute) and route.path == path)


def test_demo_api_app_lists_seeded_publish_jobs():
    api = build_demo_api_app()

    response = api.handle("GET", "/api/v1/jobs")

    assert response.status_code == 200
    assert response.body[0]["job_id"] == "job-1"
    assert response.body[0]["sanitized_baseline_id"] == "baseline-crm-dev-v1"


def test_demo_fastapi_app_serves_systems():
    app = create_demo_fastapi_app()
    route = _route(app, "/api/v1/{path:path}")

    response = asyncio.run(
        route.endpoint(
            path="systems",
            request=_build_request(method="GET", path="/api/v1/systems"),
        )
    )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload[0]["system_id"] == "crm"


def test_demo_fastapi_app_creates_publish_job():
    app = create_demo_fastapi_app()
    route = _route(app, "/api/v1/{path:path}")
    body = json.dumps(
        {
            "sourceId": "source-crm-replica",
            "targetEnvironmentId": "env-dev",
            "datasetProfileId": "profile-full-sanitized",
            "requestedBy": "developer@example.internal",
        }
    ).encode()

    response = asyncio.run(
        route.endpoint(
            path="jobs",
            request=_build_request(method="POST", path="/api/v1/jobs", body=body),
        )
    )

    payload = json.loads(response.body)
    assert response.status_code == 202
    assert payload["status"] == "pending"
