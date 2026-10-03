"""Async Postgres access via a psycopg3 connection pool."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

_pool: AsyncConnectionPool | None = None


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            kwargs={
                "row_factory": dict_row,
                # psycopg3 starts using server-side prepared statements after a
                # few executions of the same query. Supabase's transaction-mode
                # pooler (port 6543) hands out a different backend per
                # transaction, so a prepared statement from one is unknown to the
                # next and the query fails. Every statement here is schema-
                # qualified, so disabling prepares costs nothing.
                "prepare_threshold": None,
            },
            open=False,
        )
        await _pool.open(wait=True, timeout=30)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def connection() -> AsyncIterator[Any]:
    pool = await open_pool()
    async with pool.connection() as conn:
        yield conn


async def fetch_all(sql: str, params: Any = None) -> list[dict[str, Any]]:
    async with connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def fetch_one(sql: str, params: Any = None) -> dict[str, Any] | None:
    async with connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchone()


async def execute(sql: str, params: Any = None) -> None:
    async with connection() as conn:
        await conn.execute(sql, params)
