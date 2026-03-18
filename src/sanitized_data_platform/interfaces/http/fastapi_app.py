from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from sanitized_data_platform.interfaces.api.app import ApiApp


def _default_live_probe() -> dict[str, object]:
    return {"status": "ok"}


def create_fastapi_app(
    api_app: ApiApp,
    *,
    service_name: str = "Sanitized Data Platform",
    service_version: str = "0.1.0",
    live_probe: Callable[[], dict[str, object]] | None = None,
    ready_probe: Callable[[], dict[str, object]] | None = None,
    metrics_provider: Callable[[], dict[str, object]] | None = None,
    logger: logging.Logger | None = None,
) -> FastAPI:
    app_logger = logger or logging.getLogger("sanitized_data_platform.http")
    live = live_probe or _default_live_probe

    app = FastAPI(
        title=service_name,
        version=service_version,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        request.state.request_id = request_id
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
            app_logger.exception(
                "http_request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": elapsed_ms,
                },
            )
            raise
        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        app_logger.info(
            "http_request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": elapsed_ms,
            },
        )
        return response

    @app.get("/health")
    async def health() -> dict[str, object]:
        return live()

    @app.get("/health/live")
    async def health_live() -> dict[str, object]:
        return live()

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        body = ready_probe() if ready_probe is not None else live()
        status_code = 200 if body.get("status") == "ok" else 503
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body))

    @app.get("/metrics")
    async def metrics() -> dict[str, object]:
        return metrics_provider() if metrics_provider is not None else {"status": "ok", "metrics": {}}

    @app.api_route("/api/v1/{path:path}", methods=["GET", "POST"])
    async def route_api(path: str, request: Request) -> JSONResponse:
        normalized_path = f"/api/v1/{path}"
        body: dict[str, Any] | None = None
        if request.method != "GET":
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            body = payload if isinstance(payload, dict) else {}

        try:
            response = api_app.handle(
                request.method,
                normalized_path,
                query=dict(request.query_params),
                body=body,
            )
        except Exception:
            app_logger.exception(
                "api_request_unhandled_error",
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "method": request.method,
                    "path": normalized_path,
                },
            )
            return JSONResponse(status_code=500, content={"error": "Internal server error"})
        return JSONResponse(
            status_code=response.status_code,
            content=jsonable_encoder(response.body),
        )

    return app
