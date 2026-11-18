from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
import logging
import aiosqlite

from config import settings

logger = logging.getLogger(__name__)


class Database:
    """
    Central async SQLite wrapper following ASAAS backend foundation standards.
    Owns connection pragmas (WAL, foreign keys, busy timeout), query execution,
    and row mapping.
    """

    _initialized: bool = False

    @classmethod
    def get_db_path(cls) -> Path:
        return settings.resolved_database_path

    @classmethod
    async def initialize(cls) -> None:
        db_path = cls.get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("PRAGMA journal_mode = WAL;")
            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.execute("PRAGMA busy_timeout = 5000;")
            await conn.execute("PRAGMA synchronous = NORMAL;")
            await conn.commit()

        cls._initialized = True
        logger.info("Database initialized with WAL mode at %s", db_path)

    @classmethod
    @asynccontextmanager
    async def connection(cls) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(cls.get_db_path()) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.execute("PRAGMA busy_timeout = 5000;")
            yield conn

    @classmethod
    @asynccontextmanager
    async def transaction(cls) -> AsyncIterator[aiosqlite.Connection]:
        async with cls.connection() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    @classmethod
    async def execute(cls, query: str, params: tuple[Any, ...] = ()) -> None:
        async with cls.connection() as conn:
            await conn.execute(query, params)
            await conn.commit()

    @classmethod
    async def fetch_one(
        cls,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        async with cls.connection() as conn:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return dict(row) if row else None

    @classmethod
    async def fetch_all(
        cls,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        async with cls.connection() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    @classmethod
    async def close(cls) -> None:
        logger.info("Database resources released")
