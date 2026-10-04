"""Async SQLAlchemy 2 engine/session — the one place a DB connection is made.

Convention established here, carried through every later model/router:
  - all I/O is async (asyncpg-free: psycopg3's native async mode via
    `postgresql+psycopg`, matching Alembic's sync driver with no second
    dependency — see ELUMS_TECHNICAL_APPROACH.md §4)
  - routers/tasks depend on `get_db`, never construct a session themselves
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from elums.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed/closed for you."""
    async with async_session_factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Non-FastAPI call sites (Procrastinate tasks, scripts)."""
    async with async_session_factory() as session:
        yield session
