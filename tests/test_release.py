"""
Milestone 10: the things that only matter to someone who is not the author.

Every test here pins a decision that was recorded in prose during release hardening. Prose
rots -- the README claimed extraction and summaries were "not built yet" for two
milestones after they shipped, which is why Milestone 8 made the endpoint list executable.
These do the same for the release-time decisions: the no-migrations policy, the
unversioned-API statement, and the two error messages a first-time user is most likely to
be the first to see.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from repobridge.infra.db import Database, SchemaVersionError, sqlite_path
from repobridge.infra.schemas import SCHEMA_VERSION
from repobridge.main import APP_VERSION, app
from tests.test_api import REPO_URL, _blob, _install, _tree_body

client = TestClient(app)

README = Path(__file__).resolve().parents[1] / "README.md"


# --------------------------------------------------------------------------
# the stale-database path: the one error a first upgrade guarantees
# --------------------------------------------------------------------------


def test_sqlite_path_resolves_a_url_to_a_real_file():
    resolved = sqlite_path("sqlite+aiosqlite:///./repobridge.db")
    assert resolved is not None
    assert resolved.endswith("repobridge.db")
    assert "sqlite" not in resolved, "a path, not a connection URL"
    assert Path(resolved).is_absolute()


def test_sqlite_path_declines_to_guess_for_other_databases():
    assert sqlite_path("postgresql+asyncpg://host/db") is None
    assert sqlite_path("sqlite+aiosqlite://") is None


async def test_a_stale_database_names_the_file_to_delete(tmp_path):
    """
    Before this the message said "delete the database file at
    sqlite+aiosqlite:///./repobridge.db" -- a connection URL, which the reader has to know
    how to turn into a path. It now names the file.
    """
    db_file = tmp_path / "repobridge.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    fresh = Database(url)
    await fresh.create_all()
    await fresh.dispose()

    # rewind the stamp, as pulling a build with a schema change would
    connection = sqlite3.connect(db_file)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    connection.commit()
    connection.close()

    stale = Database(url)
    with pytest.raises(SchemaVersionError) as excinfo:
        await stale.create_all()
    await stale.dispose()

    message = str(excinfo.value)
    assert str(db_file.resolve()) in message, "the message must name the actual file"
    assert "sqlite+aiosqlite" not in message, "and must not name a connection URL"
    assert str(SCHEMA_VERSION) in message and str(SCHEMA_VERSION - 1) in message
    assert "Upgrading" in message, "it points at the README section explaining the policy"
    assert "re-analysing" in message, "and says what the cost of deleting actually is"


async def test_a_fresh_database_is_stamped_and_starts_clean(tmp_path):
    db_file = tmp_path / "fresh.db"
    database = Database(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    await database.create_all()
    assert await database.schema_version() == SCHEMA_VERSION
    # and starting again against the same file is a no-op, not an error
    await database.create_all()
    await database.dispose()


async def test_foreign_keys_are_enforced_on_sqlite(tmp_path):
    """
    Every child table declares `ondelete="CASCADE"`, and SQLite ignores foreign keys
    unless asked, per connection. Without the PRAGMA those declarations were decoration.
    """
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'fk.db').as_posix()}")
    await database.create_all()
    async with database.session() as session:
        enabled = await session.scalar(text("PRAGMA foreign_keys"))
    await database.dispose()
    assert enabled == 1, "foreign keys must be on, or CASCADE never fires"


async def test_deleting_a_run_takes_its_rows_with_it(install_transport, isolated_database):
    """The behaviour the PRAGMA buys, asserted rather than assumed."""
    from sqlalchemy import delete, func, select

    from repobridge.infra.schemas import AnalysisEvent, AnalysisFile, AnalysisRun

    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([_blob("README.md", 40)])),
    )
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    async with isolated_database.session() as session:
        before = await session.scalar(
            select(func.count()).select_from(AnalysisFile).where(AnalysisFile.run_id == run_id)
        )
        assert before and before > 0, "the run stored file rows to begin with"

        await session.execute(delete(AnalysisRun).where(AnalysisRun.id == run_id))
        await session.commit()

        for model in (AnalysisFile, AnalysisEvent):
            left = await session.scalar(
                select(func.count()).select_from(model).where(model.run_id == run_id)
            )
            assert left == 0, f"{model.__tablename__} rows outlived their run"


# --------------------------------------------------------------------------
# the rate-limit message: the other error a first-time user is likely to hit
# --------------------------------------------------------------------------


def _rate_limited(**headers):
    base = {
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Limit": "60",
        "X-RateLimit-Used": "60",
        "X-RateLimit-Reset": "1787056707",
        "X-RateLimit-Resource": "core",
    }
    base.update(headers)
    return httpx.Response(403, headers=base, json={"message": "API rate limit exceeded"})


@pytest.fixture(autouse=True)
def _release_database(isolated_database):
    return isolated_database


def test_an_unauthenticated_rate_limit_says_a_token_raises_the_ceiling(
    install_transport, monkeypatch
):
    """
    The gap: the message named the limit and the reset time and left the reader to already
    know that a token exists. A first-time user has no reason to.
    """
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: _rate_limited(),
    )
    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})
    assert resp.status_code == 429

    message = resp.json()["error"]["message"]
    assert "rate limit exceeded" in message.lower()
    assert "unauthenticated" in message.lower()
    assert "REPOBRIDGE_GITHUB_TOKEN" in message
    assert "5,000" in message


def test_an_authenticated_rate_limit_does_not_tell_you_to_authenticate(
    install_transport, monkeypatch
):
    """Telling someone who already set a token to set a token is noise."""
    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", "ghp_ALREADYSET000000000000000000000000")
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: _rate_limited(**{"X-RateLimit-Limit": "5000"}),
    )
    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})
    message = resp.json()["error"]["message"]

    assert "rate limit exceeded" in message.lower()
    assert "REPOBRIDGE_GITHUB_TOKEN" not in message
    assert "unauthenticated" not in message.lower()


def test_a_secondary_rate_limit_does_not_claim_the_quota_is_the_problem(
    install_transport, monkeypatch
):
    """A secondary limit is about request pacing, not about the hourly allowance."""
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    secondary = httpx.Response(
        403,
        headers={"Retry-After": "60", "X-RateLimit-Remaining": "4321"},
        json={"message": "secondary rate limit"},
    )
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: secondary,
    )
    message = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["error"]["message"]

    assert "secondary" in message.lower()
    assert "5,000" not in message


def test_no_token_value_appears_in_a_rate_limit_message(install_transport, monkeypatch):
    token = "ghp_RATELIMITMESSAGEMUSTNOTECHOTHIS0000"
    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", token)
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: _rate_limited(),
    )
    assert token not in client.post("/api/analyze", json={"repo_url": REPO_URL}).text


# --------------------------------------------------------------------------
# one version string, not three
# --------------------------------------------------------------------------


def test_the_version_is_reported_from_package_metadata_not_a_literal():
    """`/health`, the OpenAPI document and the startup line were three separate literals."""
    health = client.get("/health").json()
    assert health["version"] == APP_VERSION
    assert app.openapi()["info"]["version"] == APP_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", APP_VERSION), APP_VERSION


# --------------------------------------------------------------------------
# the release decisions are written down, and stay written down
# --------------------------------------------------------------------------


def test_the_readme_records_the_no_migrations_decision():
    """Deferred four times before it was decided; a test is what keeps it decided."""
    text_ = README.read_text(encoding="utf-8")
    assert "## Upgrading, and why there are no migrations" in text_
    assert "no database migrations, by decision" in text_.lower()
    assert "Alembic" in text_, "the alternative that was rejected is named"
    # and the cost is stated, not just the choice
    assert "loses your stored runs" in text_ or "lose your stored runs" in text_
    assert "provider quota" in text_


def test_the_readme_records_the_api_stability_decision():
    text_ = README.read_text(encoding="utf-8")
    assert "## API stability" in text_
    assert "unstable" in text_
    assert "no `/v1/` prefix" in text_ or "no `/v1/`" in text_
    assert "Pin a commit" in text_


def test_no_endpoint_has_acquired_a_version_prefix():
    """The decision, enforced: if a prefix appears, this fails and the README must change."""
    paths = [p for p in app.openapi()["paths"] if p.startswith("/api")]
    assert paths
    for path in paths:
        assert not re.match(r"^/api/v\d", path), (
            f"{path} is versioned, but the README says the API is unversioned. "
            "Change both together or neither."
        )


def test_the_readme_states_the_python_floor_the_project_actually_requires():
    import tomllib

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    floor = pyproject["project"]["requires-python"].lstrip(">=")
    assert f"Python {floor}" in README.read_text(encoding="utf-8"), (
        f"pyproject requires Python {floor}; the README must say so"
    )


def test_every_runtime_dependency_is_declared_in_both_places():
    """
    `requirements.txt` and `pyproject.toml` are two lists of the same thing, and the README
    offers a flow that uses each. They drift silently.
    """
    import tomllib

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    def names(lines):
        out = set()
        for line in lines:
            name = re.split(r"[>=<\[;\s]", line.strip(), maxsplit=1)[0]
            if name:
                out.add(name.lower())
        return out

    declared = names(pyproject["project"]["dependencies"])
    dev = names(pyproject["project"]["optional-dependencies"]["dev"])
    pinned = names(
        line for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )

    missing = (declared | dev) - pinned
    assert not missing, f"in pyproject but not requirements.txt: {sorted(missing)}"
    extra = pinned - (declared | dev)
    assert not extra, f"in requirements.txt but not pyproject: {sorted(extra)}"
