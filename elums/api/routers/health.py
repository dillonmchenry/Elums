"""`/api/healthz` — M4's acceptance criterion A4: "a green health check."

Deliberately checks both infra dependencies for real (SELECT 1, PING)
rather than returning a static 200 — a healthy process with a dead DB
connection is the failure mode this exists to catch.
"""

from __future__ import annotations

import valkey.asyncio as valkey_asyncio
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from elums.api.deps import get_db, get_valkey

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(
    db: AsyncSession = Depends(get_db),
    cache: valkey_asyncio.Valkey = Depends(get_valkey),
) -> dict:
    await db.execute(text("SELECT 1"))
    pong = await cache.ping()
    return {"status": "ok", "db": "ok", "valkey": "ok" if pong else "fail"}
