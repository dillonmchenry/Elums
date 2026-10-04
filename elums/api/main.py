"""FastAPI entrypoint. Routers accumulate here milestone by milestone —
auth (M6), songs/blobs (M7), separation jobs (M8), etc.

CORS/COOP/COEP headers belong to Caddy (M5, once the SPA needs
SharedArrayBuffer for the AudioWorklet pipeline), not here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from elums.api.errors import install_error_handlers
from elums.api.routers import auth, health, internal, songs, users
from elums.jobs.app import app as procrastinate_app
from elums.logging import configure_logging

configure_logging()


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
install_error_handlers(app)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(songs.router, prefix="/api")
# No "/api" prefix: `/internal/*` must stay unreachable through Caddy's
# public routing (see elums/api/routers/internal.py's docstring).
app.include_router(internal.router)
