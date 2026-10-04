"""Request-scoped dependencies. Routers depend on these, never construct
infra clients themselves — see elums/db.py and elums/config.py."""

from __future__ import annotations

from collections.abc import AsyncIterator

import valkey.asyncio as valkey_asyncio

from elums.config import settings
from elums.db import get_db  # re-exported for router convenience

__all__ = ["get_db", "get_valkey"]

_valkey_pool: valkey_asyncio.Valkey | None = None


def _valkey_client() -> valkey_asyncio.Valkey:
    global _valkey_pool
    if _valkey_pool is None:
        _valkey_pool = valkey_asyncio.from_url(settings.valkey_url, decode_responses=True)
    return _valkey_pool


async def get_valkey() -> AsyncIterator[valkey_asyncio.Valkey]:
    yield _valkey_client()
