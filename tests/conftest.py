"""
Shared test fixtures.

Nothing here touches the network: every GitHub call is served by httpx.MockTransport.
"""

from __future__ import annotations

from typing import Callable

import httpx
import pytest

from repobridge.core import github_client


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
        class _MockedAsyncClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(handler)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(github_client.httpx, "AsyncClient", _MockedAsyncClient)

    return _install
