"""
Shared test fixtures.

Nothing here touches the network: every GitHub call is served by httpx.MockTransport.
"""

from __future__ import annotations

from typing import Callable

import asyncio

import httpx
import pytest

from repobridge.core import github_client

#: Captured before any patching. Re-installing a handler inside one test must subclass
#: the real client, not the previously patched one -- otherwise the parent __init__
#: overwrites the child's transport and the second handler is silently ignored.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture
def install_transport(monkeypatch) -> Callable[[Callable[[httpx.Request], httpx.Response]], None]:
    """
    Route every github_client HTTP call through a MockTransport handler.

    github_client builds its own httpx.AsyncClient per call, and GitHubConfig carries no
    transport, so there is no injection seam for the transport itself. Adding one would
    mean putting a test-only field on production config, so we monkeypatch instead.
    monkeypatch undoes this after each test.
    """

    def _install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        class _MockedAsyncClient(_REAL_ASYNC_CLIENT):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(handler)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(github_client.httpx, "AsyncClient", _MockedAsyncClient)

    return _install


class _RefusesToConnect:
    """
    Installed as the process database for every test that has not asked for a real one.

    Building an engine and running CREATE TABLE costs ~20ms, and most tests never touch
    storage. But narrowing the isolation fixture must not create a path where a test
    quietly writes to a developer's repobridge.db -- so instead of leaving the real
    config in place, unguarded access fails loudly here.
    """

    def session(self):
        raise RuntimeError(
            "This test touched the database without requesting the `isolated_database` "
            "fixture. Add it as a parameter (or rely on the module-level autouse fixture "
            "in tests that exercise the API) -- never fall through to the configured "
            "database, which is a real file."
        )

    async def create_all(self):  # pragma: no cover - defensive
        raise RuntimeError("Refusing to create schema on the guard database.")


@pytest.fixture(autouse=True)
def _no_real_database():
    """
    Autouse guard: every test starts with a database that refuses to connect.

    Cheap (no engine, no DDL) and unconditional, so a test that needs storage but forgets
    to say so gets a clear error rather than silently writing to a real file.
    """
    from repobridge.infra.db import set_database

    previous = set_database(_RefusesToConnect())
    try:
        yield
    finally:
        set_database(previous)


@pytest.fixture
def isolated_database(_no_real_database):
    """
    A fresh in-memory database, replacing the guard for tests that need storage.

    StaticPool keeps every connection on the same in-memory database, which SQLite
    otherwise scopes per-connection.
    """
    from sqlalchemy.pool import StaticPool

    from repobridge.infra.db import Database, set_database

    database = Database(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    asyncio.run(database.create_all())
    set_database(database)
    try:
        yield database
    finally:
        asyncio.run(database.dispose())


@pytest.fixture
def file_database(tmp_path, _no_real_database):
    """
    A database backed by a real file in tmp_path, for tests that need persistence to
    survive an engine being disposed and reopened (the "restart" case).
    """
    from repobridge.infra.db import Database, set_database

    path = tmp_path / "restart-test.db"

    def open_database() -> Database:
        return Database(f"sqlite+aiosqlite:///{path.as_posix()}")

    database = open_database()
    asyncio.run(database.create_all())
    previous = set_database(database)
    try:
        yield open_database
    finally:
        set_database(previous)
        asyncio.run(database.dispose())
