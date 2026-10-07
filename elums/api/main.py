"""FastAPI entrypoint. Routers accumulate here milestone by milestone —
auth (M6), songs/blobs (M7), separation jobs (M8), etc.

CORS/COOP/COEP headers belong to Caddy (M5, once the SPA needs
SharedArrayBuffer for the AudioWorklet pipeline), not here.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from elums.api.errors import install_error_handlers
from elums.api.routers import auth, health, internal, performances, songs, users
from elums.jobs.app import app as procrastinate_app
from elums.logging import configure_logging, get_logger

configure_logging()
_access_logger = get_logger("elums.access")


class _RequestIdMiddleware(BaseHTTPMiddleware):
    """Binds `request_id` to structlog's contextvars for the life of one
    request (so any log line emitted while handling it carries it
    automatically, per elums/logging.py's documented convention) and
    emits one structlog JSON access-log line per request. Discovered
    missing -- and added -- during the M8 end-of-day validation pass:
    uvicorn's own access logger is plain text, not structlog, so
    `docker compose logs api` had no JSON `request_id` field at all
    until this existed, despite the docstring describing it as day-one
    convention since M4."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        structlog.contextvars.clear_contextvars()
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.monotonic()
        response = await call_next(request)
        _access_logger.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return response


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    # M8: `POST /api/songs` defers the separation job by task NAME
    # (`app.configure_task(...)`), never by importing
    # `elums.separation.task` directly — that module imports torch, which
    # the `api` image deliberately does not have (§11.6: keep api/worker
    # torch-free so the image stays small and rebuilds fast). Deferring
    # needs an opened connection pool first — hit directly Oct 3 2026:
    # `procrastinate.exceptions.AppNotOpen` on the first upload.
    async with procrastinate_app.open_async():
        yield


app = FastAPI(title="Elums API", lifespan=_lifespan)
app.add_middleware(_RequestIdMiddleware)
install_error_handlers(app)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(songs.router, prefix="/api")
app.include_router(performances.router, prefix="/api")
# No "/api" prefix: `/internal/*` must stay unreachable through Caddy's
# public routing (see elums/api/routers/internal.py's docstring).
app.include_router(internal.router)
