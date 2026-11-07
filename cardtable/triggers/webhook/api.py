"""FastAPI routes for submissions, waiting, results and generated API docs."""

from __future__ import annotations

import asyncio
from threading import Event
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer
from starlette.exceptions import HTTPException

from .config import WebhookSettings
from .documentation import EXAMPLE, description, render_docs
from .errors import WebhookError
from .history import Job
from .limits import JSONRoute, RequestLimits
from .models import ErrorResponse, EventResponse, Submission


class WebhookEndpoint(Protocol):
    settings: WebhookSettings
    _stop_event: Event

    def _accept(self, payload: Submission) -> Job: ...

    def _get_result(self, event_id: str) -> EventResponse | None: ...


def create_app(endpoint: WebhookEndpoint, base_url: str) -> FastAPI:
    settings = endpoint.settings
    app = FastAPI(
        title="CardTable Inference API",
        version="2.0.0",
        description=description(settings),
        servers=[{"url": base_url}],
        redoc_url=None,
    )
    app.router.route_class = JSONRoute
    app.add_middleware(
        RequestLimits, settings=settings, stop_event=endpoint._stop_event
    )

    @app.exception_handler(WebhookError)
    async def webhook_error(request: Request, error: WebhookError):
        return JSONResponse(error.as_dict(), error.status, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_payload(request: Request, error: RequestValidationError):
        fields = ", ".join(".".join(map(str, item["loc"])) for item in error.errors())
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_payload",
                    "message": f"Invalid fields: {fields}",
                }
            },
            400,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return JSONResponse(
            {"error": {"code": "http_error", "message": str(error.detail)}},
            error.status_code,
            headers=error.headers,
        )

    dependencies = [Security(HTTPBearer(auto_error=False))] if settings.token else []
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ErrorResponse}
        for code in (400, 401, 404, 405, 408, 413, 415, 503)
    }

    @app.post(
        settings.path,
        status_code=201,
        response_model=EventResponse,
        dependencies=dependencies,
        summary="Create an inference event and receive its result",
        responses={
            **errors,
            202: {"model": EventResponse},
            500: {"model": EventResponse},
        },
        openapi_extra={
            "requestBody": {"content": {"application/json": {"example": EXAMPLE}}}
        },
    )
    async def create_event(
        submission: Submission,
        wait: Annotated[
            bool,
            Query(
                description=(
                    "Wait for inference up to response_timeout; "
                    "false returns a pending job immediately"
                )
            ),
        ] = True,
    ):
        if len(submission.texts) + len(submission.images) > settings.max_items:
            raise WebhookError(413, "too_many_items", "Submission exceeds max_items")
        job = endpoint._accept(submission)
        response, status = job.response, 201
        if wait:
            try:
                response = await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(job.done)),
                    settings.response_timeout,
                )
                status = {"failed": 500, "cancelled": 503}.get(response.status, 201)
            except asyncio.TimeoutError:
                response = endpoint._get_result(job.response.event_id) or job.response
                status = (
                    202
                    if response.status == "pending"
                    else {"failed": 500, "cancelled": 503}.get(response.status, 201)
                )
        return JSONResponse(
            response.model_dump(mode="json"),
            status,
            headers={"Location": f"{settings.path}/{response.event_id}"},
        )

    @app.get(
        settings.path + "/{event_id}",
        response_model=EventResponse,
        dependencies=dependencies,
        responses=errors,
        summary="Read inference status and named text/image results",
    )
    async def get_result(event_id: str):
        response = endpoint._get_result(event_id)
        if response is None:
            raise WebhookError(
                404, "not_found", "Event is unknown or no longer retained"
            )
        return response

    @app.get("/guide", response_class=HTMLResponse, include_in_schema=False)
    async def guide():
        return render_docs(settings, base_url)

    return app
