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

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from repobridge.config import DEFAULT_DATABASE_CONFIG, DatabaseConfig, get_database_url
from repobridge.infra.schemas import SCHEMA_VERSION, Base

logger = logging.getLogger(__name__)


class SchemaVersionError(RuntimeError):
    """
    The database on disk was written by a different schema version.

    v0.1 has no migrations, by decision rather than oversight: nothing has shipped, so no
    database holds history worth migrating, and Alembic is a dependency plus a workflow
    for three tables that change every milestone. What was worth fixing is the *failure
    mode* -- previously a stale database produced `OperationalError: no such column` on
    every endpoint, mid-request, with a stack trace. This says what happened instead.
    """


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
        """
        Create the schema, stamping the version on a fresh database.

        Refuses to touch a database written by a different version rather than leaving it
        half-usable: `create_all` never alters existing tables, so an older database would
        otherwise survive startup and fail on the first query.
        """
        async with self._engine.begin() as conn:
            existing = await conn.run_sync(lambda c: inspect(c).get_table_names())
            version = await conn.scalar(text("PRAGMA user_version"))

            if existing and version != SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"This database was created by schema version {version}, but this build "
                    f"expects version {SCHEMA_VERSION}. RepoBridge v0.1 has no migrations: "
                    f"delete the database file at {self.url} and run again. Any stored runs "
                    "will be lost -- they can be re-created by re-analysing the repositories."
                )

            await conn.run_sync(Base.metadata.create_all)
            if version != SCHEMA_VERSION:
                # PRAGMA does not accept bind parameters; SCHEMA_VERSION is our own int.
                await conn.execute(text(f"PRAGMA user_version = {int(SCHEMA_VERSION)}"))

    async def schema_version(self) -> int:
        async with self._engine.connect() as conn:
            return int(await conn.scalar(text("PRAGMA user_version")) or 0)

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
