"""
Shared test fixtures.

Nothing here touches the network: every GitHub call is served by httpx.MockTransport.
"""

from __future__ import annotations

from typing import Callable

import asyncio

import httpx
import pytest

from repobridge.core import github_client, summarization

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


def _refuse_provider_call(*args, **kwargs):
    """
    Installed in place of `summarization._call_gemini` for every test.

    Raises through `pytest.fail`, whose exception derives from BaseException rather than
    Exception. That matters here: `summarise()` deliberately catches broad exceptions so a
    provider fault cannot lose a run, and an ordinary error raised from this guard would be
    swallowed into a PROVIDER_ERROR result -- a test would then fail on some later
    assertion with no hint that it had tried to call Google. BaseException passes straight
    through that handler and fails the test where the mistake is.
    """
    pytest.fail(
        "This test reached the real summarisation provider (`_call_gemini`). No test may "
        "make a live provider call: the free tier's allowance is measured in requests per "
        "day and a previous session spent an entire day's quota on diagnostics.\n\n"
        "The usual cause is setting REPOBRIDGE_GEMINI_API_KEY without injecting a "
        "provider. Fix it by one of:\n"
        "  - override the route dependency: "
        "app.dependency_overrides[routes_runs.get_summary_provider] = lambda: call\n"
        "  - pass call_provider=... to summarise()\n"
        "  - request the `real_provider_call` fixture, if the point of the test IS to "
        "exercise `_call_gemini` against an httpx.MockTransport.",
        pytrace=False,
    )


#: Captured before the guard replaces it, for the same reason `_REAL_ASYNC_CLIENT` is:
#: the opt-in fixture must restore the real function, not whatever is installed now.
_REAL_CALL_GEMINI = summarization._call_gemini


@pytest.fixture(autouse=True)
def _no_real_summariser(monkeypatch):
    """
    No test may call a real summarisation provider.

    Two layers, the same shape as the database guard:

    1. **Unset the key**, so `summarise()` short-circuits to NOT_CONFIGURED rather than
       reaching the network. This is the soft layer -- a test that sets the key defeats it.
    2. **Replace `_call_gemini` with a refuser**, so setting the key is not enough. This is
       the hard layer, equivalent to `_RefusesToConnect`: a forgotten injection fails
       loudly at the point of the call instead of quietly sending repository content to
       Google.

    Layer 1 alone was the state of this fixture until the guard was added, and it was not
    enough: a test that set the key and forgot to inject a provider did reach the network.

    Tests that mean to exercise `_call_gemini` itself request `real_provider_call`.
    """
    monkeypatch.delenv("REPOBRIDGE_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(summarization, "_call_gemini", _refuse_provider_call)


@pytest.fixture
def real_provider_call(_no_real_summariser, monkeypatch):
    """
    The real `_call_gemini`, for tests that exercise it against an httpx.MockTransport.

    The counterpart of `isolated_database`: the guard is the default, and a test that needs
    the real thing says so in its signature rather than reaching around it. Returns the
    function *and* restores the module attribute, so it does not matter whether a caller
    goes through the module or through the returned reference.

    Requesting this fixture does not permit a network call -- it permits calling the
    function. The test still has to install a mock transport, and every test that requests
    it does.
    """
    monkeypatch.setattr(summarization, "_call_gemini", _REAL_CALL_GEMINI)
    return _REAL_CALL_GEMINI
