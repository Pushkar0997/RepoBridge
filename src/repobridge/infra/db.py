"""
SQLite connection layer.

A `Database` owns an async engine and session factory. The app uses one built from
config; tests construct their own against a temp or in-memory URL, so no test ever
touches a developer's real database file.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from repobridge.config import DEFAULT_DATABASE_CONFIG, DatabaseConfig, get_database_url
from repobridge.infra.schemas import Base

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str, *, echo: bool = False, **engine_kwargs):
        self.url = url
        self._engine = create_async_engine(url, echo=echo, future=True, **engine_kwargs)
        self._sessionmaker = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    @property
    def engine(self):
        return self._engine

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessionmaker() as session:
            yield session

    async def dispose(self) -> None:
        await self._engine.dispose()


_database: Database | None = None


def get_database(cfg: DatabaseConfig = DEFAULT_DATABASE_CONFIG) -> Database:
    """The process-wide Database, created lazily from config on first use."""
    global _database
    if _database is None:
        url = get_database_url(cfg)
        logger.info("Opening database at %s", url)
        _database = Database(url)
    return _database


def set_database(database: Database | None) -> Database | None:
    """
    Replace the process-wide Database and return the previous one.

    Exists so tests can point the app at their own storage. Production code should not
    call it.
    """
    global _database
    previous = _database
    _database = database
    return previous


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session from the current Database."""
    async with get_database().session() as session:
        yield session
