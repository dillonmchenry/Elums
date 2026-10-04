"""FastAPI entrypoint. Routers accumulate here milestone by milestone —
auth (M6), songs/blobs (M7), separation jobs (M8), etc.

CORS/COOP/COEP headers belong to Caddy (M5, once the SPA needs
SharedArrayBuffer for the AudioWorklet pipeline), not here.
"""

from __future__ import annotations

from fastapi import FastAPI

from elums.api.errors import install_error_handlers
from elums.api.routers import auth, health, internal, songs, users
from elums.logging import configure_logging

configure_logging()

app = FastAPI(title="Elums API")
install_error_handlers(app)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(songs.router, prefix="/api")
# No "/api" prefix: `/internal/*` must stay unreachable through Caddy's
# public routing (see elums/api/routers/internal.py's docstring).
app.include_router(internal.router)
