"""
Shared-deployment posture: spend control, platform config, and honest refusals.

The thing being protected here is not the app, it is **the operator's quota**. On a shared
instance every visitor spends someone else's GitHub token and Gemini allowance, and until
this milestone nothing stopped one person consuming all of it.

Every limit is off by default -- `test_limits_are_off_by_default` is the test that keeps
local development unchanged, and it is the reason the other 646 tests did not need
touching.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.config import get_bind_address, get_deployment_config
from repobridge.core.limits import RateLimiter, client_key, get_limiter
from repobridge.main import app
from tests.test_api import REPO_URL, _blob, _install, _tree_body

client = TestClient(app)


@pytest.fixture(autouse=True)
def _deployment_database(isolated_database):
    return isolated_database


@pytest.fixture(autouse=True)
def _clean_limiter():
    """The limiter is process-wide, so a test that fills it would poison the next."""
    get_limiter().reset()
    yield
    get_limiter().reset()


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    return get_deployment_config()


def _tree(entries=None):
    return lambda ref: httpx.Response(
        200, json=_tree_body(entries or [_blob("README.md", 40)])
    )


def _analyze(**kwargs):
    return client.post("/api/analyze", json={"repo_url": REPO_URL}, **kwargs)


# --------------------------------------------------------------------------
# the limiter itself
# --------------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_a_limit_of_zero_means_no_limit():
    limiter = RateLimiter()
    for _ in range(100):
        assert limiter.check("k", 0).allowed
        limiter.record("k")


def test_the_window_admits_up_to_the_limit_then_refuses():
    clock = FakeClock()
    limiter = RateLimiter(window_seconds=3600, clock=clock)

    for _ in range(3):
        assert limiter.check("k", 3).allowed
        limiter.record("k")

    verdict = limiter.check("k", 3)
    assert verdict.allowed is False
    assert verdict.limit == 3 and verdict.used == 3


def test_a_refusal_says_when_the_allowance_returns():
    """
    The property that decided the design. Every other limit in this project says when it
    lifts; a limiter that could only say "too many requests" would be the one that does not.
    """
    clock = FakeClock()
    limiter = RateLimiter(window_seconds=3600, clock=clock)
    limiter.record("k")

    clock.advance(600)  # ten minutes into the hour
    verdict = limiter.check("k", 1)

    assert verdict.allowed is False
    assert 3000 <= verdict.retry_after_seconds <= 3002, verdict.retry_after_seconds
    assert verdict.retry_after_human == "in 50 minutes"


def test_the_window_slides_rather_than_resetting_on_the_hour():
    clock = FakeClock()
    limiter = RateLimiter(window_seconds=3600, clock=clock)
    limiter.record("k")
    limiter.record("k")

    assert limiter.check("k", 2).allowed is False
    clock.advance(3601)
    assert limiter.check("k", 2).allowed is True
    assert limiter.used("k") == 0


def test_checking_does_not_consume_the_allowance():
    """An analysis that fails validation must not cost a visitor part of their quota."""
    limiter = RateLimiter()
    for _ in range(10):
        assert limiter.check("k", 1).allowed
    assert limiter.used("k") == 0


def test_keys_are_independent():
    limiter = RateLimiter()
    limiter.record("a")
    assert limiter.check("a", 1).allowed is False
    assert limiter.check("b", 1).allowed is True


def test_retry_after_reads_as_a_sentence():
    assert RateLimiter().check("x", 0).allowed
    from repobridge.core.limits import LimitVerdict

    assert LimitVerdict(False, retry_after_seconds=1).retry_after_human == "in 1 second"
    assert LimitVerdict(False, retry_after_seconds=45).retry_after_human == "in 45 seconds"
    assert LimitVerdict(False, retry_after_seconds=3600).retry_after_human == "in 60 minutes"


def test_client_key_prefers_the_original_forwarded_address():
    """Behind a proxy the direct peer is the proxy: everyone would share one bucket."""
    assert client_key("203.0.113.7, 10.0.0.1", "10.0.0.1") == "203.0.113.7"
    assert client_key(None, "198.51.100.4") == "198.51.100.4"
    assert client_key("", None) == "unknown"


# --------------------------------------------------------------------------
# limits are off unless configured
# --------------------------------------------------------------------------


def test_limits_are_off_by_default(monkeypatch):
    """Local development is unchanged. This is why the rest of the suite is untouched."""
    for name in (
        "REPOBRIDGE_DEPLOYMENT",
        "REPOBRIDGE_MAX_ANALYSES_PER_HOUR",
        "REPOBRIDGE_MAX_ANALYSES_PER_HOUR_PER_CLIENT",
        "REPOBRIDGE_MAX_REPO_ENTRIES",
    ):
        monkeypatch.delenv(name, raising=False)

    deployment = get_deployment_config()
    assert deployment.mode == "local"
    assert deployment.max_analyses_per_hour == 0
    assert deployment.max_analyses_per_hour_per_client == 0
    assert deployment.max_repo_entries == 0
    assert deployment.is_shared is False


def test_shared_mode_switches_all_three_limits_on(shared):
    assert shared.is_shared is True
    assert shared.max_analyses_per_hour == 20
    assert shared.max_analyses_per_hour_per_client == 5
    assert shared.max_repo_entries == 5_000


def test_shared_mode_lowers_the_read_cap(monkeypatch):
    """
    The read cap is part of the same budget as the rate limits, so it moves with them.
    Local development keeps 200.
    """
    from repobridge.config import get_extraction_config

    monkeypatch.delenv("REPOBRIDGE_MAX_FILES_PER_RUN", raising=False)
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    assert get_extraction_config().max_files_per_run == 100

    monkeypatch.delenv("REPOBRIDGE_DEPLOYMENT", raising=False)
    assert get_extraction_config().max_files_per_run == 200


def test_an_explicit_read_cap_still_wins_in_shared_mode(monkeypatch):
    from repobridge.config import get_extraction_config

    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "25")
    assert get_extraction_config().max_files_per_run == 25


# --------------------------------------------------------------------------
# the four shared defaults are one budget
# --------------------------------------------------------------------------

#: The quotas the defaults are sized against. GitHub authenticated is 5,000 requests an
#: hour; the Gemini free tier on `gemini-3.5-flash-lite` is ~500 requests a day, per model.
GITHUB_HOURLY_QUOTA = 5_000
GEMINI_DAILY_QUOTA = 500

#: Leave the operator room to use their own token while the demo is running, and stay well
#: clear of GitHub's *secondary* limits, which concurrency provokes before the primary one.
GITHUB_HEADROOM = 0.6


def test_the_shared_defaults_fit_both_quotas(monkeypatch):
    """
    The arithmetic, executed rather than asserted in prose.

    The shipped defaults were wrong when this was written: 40 analyses/hour at a 200-file
    read cap is 8,080 GitHub calls an hour against a 5,000 quota, and 960 Gemini requests
    a day against ~500. Both were over, and nothing would have said so until the demo
    stopped working in front of testers.

    **This test is the reason a future change to any one of the four cannot break the set
    quietly.** If it fails, the fix is to rebalance the numbers, not to loosen the test.
    """
    from repobridge.config import get_extraction_config

    monkeypatch.delenv("REPOBRIDGE_MAX_FILES_PER_RUN", raising=False)
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    deployment = get_deployment_config()
    read_cap = get_extraction_config().max_files_per_run

    # One analysis: metadata + tree, then one contents call per file read. The read cap
    # bounds the third term regardless of how large the repository is.
    github_per_analysis = 2 + read_cap
    assert github_per_analysis == 102

    worst_hour = deployment.max_analyses_per_hour * github_per_analysis
    assert worst_hour == 2_040
    assert worst_hour <= GITHUB_HOURLY_QUOTA * GITHUB_HEADROOM, (
        f"a saturated hour costs {worst_hour} GitHub calls, over "
        f"{int(GITHUB_HOURLY_QUOTA * GITHUB_HEADROOM)} of the {GITHUB_HOURLY_QUOTA}/hour quota"
    )

    # Summarisation is one provider request per analysis. An hourly limit only bounds a
    # *daily* quota if a full day at that rate still fits inside it.
    gemini_per_day = deployment.max_analyses_per_hour * 24
    assert gemini_per_day == 480
    assert gemini_per_day <= GEMINI_DAILY_QUOTA, (
        f"a full day at {deployment.max_analyses_per_hour}/hour is {gemini_per_day} "
        f"provider requests, over the ~{GEMINI_DAILY_QUOTA}/day free tier"
    )


def test_one_visitor_cannot_take_the_whole_instance_hour(monkeypatch):
    """Otherwise the fourth tester to arrive finds a demo that has stopped working."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    deployment = get_deployment_config()

    share = deployment.max_analyses_per_hour_per_client / deployment.max_analyses_per_hour
    assert share <= 0.25, f"one visitor can take {share:.0%} of the instance's hour"
    assert deployment.max_analyses_per_hour_per_client >= 3, (
        "and it must still be enough to actually try the thing"
    )


def test_the_repository_the_landing_page_suggests_is_admitted(monkeypatch):
    """
    `psf/requests` is what the landing page tells a tester to paste. A default that
    refused it would make the first thing a visitor tries fail.
    """
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    deployment = get_deployment_config()

    PSF_REQUESTS_ENTRIES = 153   # smoke.md, measured live in Runs 8-12
    assert PSF_REQUESTS_ENTRIES <= deployment.max_repo_entries

    html = client.get("/").text
    assert "https://github.com/psf/requests" in html, (
        "if the suggested example changes, re-check it against max_repo_entries"
    )


def test_the_size_limit_admits_ordinary_repositories_and_refuses_the_giants(monkeypatch):
    """Measured entry counts from the smoke suite, on both sides of the line."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    limit = get_deployment_config().max_repo_entries

    for name, entries in [
        ("octocat/Hello-World", 1),
        ("Pushkar0997/quantum-toybox", 40),
        ("psf/requests", 153),
    ]:
        assert entries <= limit, f"{name} ({entries}) should be admitted"

    for name, entries in [
        ("twitter/twemoji", 7_413),
        ("github/docs", 14_903),
        ("kubernetes/kubernetes", 37_393),
    ]:
        assert entries > limit, f"{name} ({entries}) should be refused"


def test_an_explicit_variable_overrides_the_shared_default(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR", "2")
    assert get_deployment_config().max_analyses_per_hour == 2


def test_an_explicit_zero_turns_one_limit_off_without_leaving_shared_mode(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_REPO_ENTRIES", "0")
    deployment = get_deployment_config()
    assert deployment.is_shared is True
    assert deployment.max_repo_entries == 0
    assert deployment.max_analyses_per_hour == 20, "the other limits are untouched"


def test_unusable_values_fall_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR", "not-a-number")
    monkeypatch.setenv("REPOBRIDGE_STORAGE", "sometimes")
    deployment = get_deployment_config()
    assert deployment.max_analyses_per_hour == 20
    assert deployment.storage == "persistent"


# --------------------------------------------------------------------------
# the limits trigger, and say so honestly
# --------------------------------------------------------------------------


def test_the_per_visitor_limit_refuses_and_names_itself(install_transport, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR_PER_CLIENT", "2")
    _install(install_transport, _tree())

    assert _analyze().status_code == 200
    assert _analyze().status_code == 200

    resp = _analyze()
    assert resp.status_code == 429
    error = resp.json()["error"]

    assert error["code"] == "client_limit_reached"
    assert "You have reached your hourly analysis limit" in error["message"]
    assert "2 analyses per hour per visitor" in error["message"]
    assert "The limit lifts in" in error["message"], "it says when, like every other limit"
    assert error["details"]["limit"] == 2
    assert error["details"]["used"] == 2
    assert error["details"]["window"] == "1 hour"
    assert error["details"]["retry_after_seconds"] > 0


def test_the_instance_limit_refuses_and_is_distinguishable_from_the_visitor_one(
    install_transport, monkeypatch
):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR", "1")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR_PER_CLIENT", "0")
    _install(install_transport, _tree())

    assert _analyze().status_code == 200
    resp = _analyze()

    assert resp.status_code == 429
    error = resp.json()["error"]
    assert error["code"] == "instance_limit_reached"
    assert "This instance has reached its hourly analysis limit" in error["message"]
    assert "per visitor" not in error["message"]


def test_a_different_visitor_has_their_own_allowance(install_transport, monkeypatch):
    """The per-client limit must not become an instance limit by accident."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR_PER_CLIENT", "1")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR", "0")
    _install(install_transport, _tree())

    first = {"x-forwarded-for": "203.0.113.1"}
    second = {"x-forwarded-for": "203.0.113.2"}

    assert _analyze(headers=first).status_code == 200
    assert _analyze(headers=first).status_code == 429
    assert _analyze(headers=second).status_code == 200, "a second visitor is not blocked"


def test_a_rejected_url_does_not_cost_the_visitor_an_analysis(
    install_transport, monkeypatch
):
    """Checked before validation, consumed after: a typo must not spend an allowance."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_ANALYSES_PER_HOUR_PER_CLIENT", "1")
    _install(install_transport, _tree())

    bad = client.post("/api/analyze", json={"repo_url": "https://gitlab.com/a/b"})
    assert bad.status_code == 400

    assert _analyze().status_code == 200, "the real analysis still had its allowance"


def test_a_repository_larger_than_the_instance_accepts_is_refused(
    install_transport, monkeypatch
):
    """
    Refused after two GitHub calls and before up to 200 content reads -- the whole point
    of checking size at the tree step rather than at the end.
    """
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_REPO_ENTRIES", "5")
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(12)]

    reads = []

    def content(path):
        reads.append(path)
        return httpx.Response(404, json={"message": "should never be reached"})

    _install(install_transport, _tree(entries), content_responder=content)
    resp = _analyze()

    assert resp.status_code == 413
    error = resp.json()["error"]
    assert error["code"] == "repo_too_large"
    assert "12 tree entries" in error["message"]
    assert "up to 5" in error["message"]
    assert error["details"]["entries"] == 12 and error["details"]["limit"] == 5
    assert reads == [], "no file content was fetched, which is the point of the limit"


def test_a_repository_at_the_limit_is_accepted(install_transport, monkeypatch):
    """An off-by-one here would refuse a repository the operator meant to allow."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_REPO_ENTRIES", "3")
    entries = [_blob(f"f{i}.md", 40) for i in range(3)]
    _install(install_transport, _tree(entries))
    assert _analyze().status_code == 200


def test_the_size_refusal_is_recorded_in_diagnostics(install_transport, monkeypatch):
    """A refusal is a thing that happened to a request; it should not be invisible."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_MAX_REPO_ENTRIES", "2")
    _install(install_transport, _tree([_blob(f"f{i}.md", 40) for i in range(9)]))

    resp = _analyze()
    assert resp.status_code == 413
    # no run row is created (nothing was classified), so the trace is the log and the
    # response; this asserts the response carries enough to explain itself
    assert resp.json()["error"]["details"]["repo"] == "octo/demo"


def test_no_limit_applies_when_the_instance_is_local(install_transport, monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_DEPLOYMENT", raising=False)
    _install(install_transport, _tree([_blob(f"f{i}.md", 40) for i in range(50)]))
    for _ in range(6):
        assert _analyze().status_code == 200


# --------------------------------------------------------------------------
# platform configuration
# --------------------------------------------------------------------------


def test_the_bind_address_defaults_to_loopback_and_8000(monkeypatch):
    for name in ("REPOBRIDGE_HOST", "HOST", "REPOBRIDGE_PORT", "PORT"):
        monkeypatch.delenv(name, raising=False)
    assert get_bind_address() == ("127.0.0.1", 8000)


def test_the_platform_port_is_read_from_the_environment(monkeypatch):
    """`PORT` is the convention on Render, Fly, Railway, Cloud Run and Heroku."""
    monkeypatch.delenv("REPOBRIDGE_PORT", raising=False)
    monkeypatch.setenv("PORT", "10000")
    assert get_bind_address()[1] == 10000


def test_the_projects_own_variables_win_over_the_generic_ones(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("REPOBRIDGE_PORT", "9999")
    monkeypatch.setenv("HOST", "1.2.3.4")
    monkeypatch.setenv("REPOBRIDGE_HOST", "5.6.7.8")
    assert get_bind_address() == ("5.6.7.8", 9999)


def test_an_unusable_port_falls_back_rather_than_crashing_at_boot(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_PORT", raising=False)
    monkeypatch.setenv("PORT", "$PORT")   # the classic unexpanded-variable deploy bug
    assert get_bind_address()[1] == 8000


def test_the_database_path_comes_from_the_environment(monkeypatch, tmp_path):
    from repobridge.config import get_database_url

    monkeypatch.delenv("REPOBRIDGE_DATABASE_URL", raising=False)
    assert get_database_url() == "sqlite+aiosqlite:///./repobridge.db"

    target = f"sqlite+aiosqlite:///{(tmp_path / 'x.db').as_posix()}"
    monkeypatch.setenv("REPOBRIDGE_DATABASE_URL", target)
    assert get_database_url() == target


def test_nothing_static_or_templated_depends_on_the_working_directory():
    """
    A container's working directory is not the repository root. Templates and static
    files are resolved from the package, so only the database default is CWD-relative --
    and that one is overridable, which the Dockerfile does.
    """
    from pathlib import Path

    from repobridge.main import BASE_DIR

    assert BASE_DIR.is_absolute()
    assert (BASE_DIR / "ui" / "templates" / "index.html").is_file()
    assert (BASE_DIR / "ui" / "static" / "css" / "main.css").is_file()
    assert Path(__file__).resolve() != BASE_DIR


# --------------------------------------------------------------------------
# what a visitor is told
# --------------------------------------------------------------------------


def test_a_shared_instance_announces_itself_as_a_demo(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    html = client.get("/").text

    assert "This is a shared demo instance." in html
    assert "every analysis here is visible to everyone using it" in html.lower()
    assert "no accounts" in html.lower()


def test_a_local_instance_shows_no_demo_banner(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_DEPLOYMENT", raising=False)
    assert "shared demo instance" not in client.get("/").text


def test_a_shared_instance_lists_its_limits(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    html = client.get("/").text

    assert "Limits on this instance" in html
    assert "20</strong> analyses per hour" in html
    assert "5</strong> analyses per hour per visitor" in html
    assert "5,000</strong> tree entries" in html


def test_a_shared_instance_does_not_tell_visitors_to_set_the_operators_keys(monkeypatch):
    """The advice is not actionable by a tester and would be misleading."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REPOBRIDGE_GEMINI_API_KEY", raising=False)
    html = client.get("/").text

    assert "export REPOBRIDGE_GITHUB_TOKEN" not in html
    assert "export REPOBRIDGE_GEMINI_API_KEY" not in html
    assert "runs on the operator" in html
    assert "The operator can fix this; you cannot." in html


def test_a_local_instance_still_tells_the_reader_how_to_set_their_own_keys(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_DEPLOYMENT", raising=False)
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    html = client.get("/").text
    assert "export REPOBRIDGE_GITHUB_TOKEN=your_token_here" in html


def test_the_landing_page_says_what_to_paste_and_what_happens(monkeypatch):
    """First contact: what is this, what do I do, how long does it take."""
    html = client.get("/").text
    assert "public GitHub repository" in html
    assert "https://github.com/psf/requests" in html
    assert "roughly ten seconds" in html


# --------------------------------------------------------------------------
# ephemeral storage
# --------------------------------------------------------------------------


def test_an_ephemeral_instance_does_not_claim_nothing_was_ever_analysed(monkeypatch):
    """
    The rule this milestone adds: a wiped database and a never-used one look identical
    from the home page, and "No runs yet" to someone whose runs a restart deleted would be
    the one dishonest empty state in the project.
    """
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_STORAGE", "ephemeral")
    html = client.get("/").text

    assert "No runs yet" not in html
    assert "No runs stored right now" in html
    assert "wiped when the process restarts" in html
    assert "may have existed and be gone" in html


def test_a_persistent_instance_keeps_the_plain_empty_state(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_STORAGE", raising=False)
    html = client.get("/").text
    assert "No runs yet. Analyze a repository above." in html


def test_an_ephemeral_instance_warns_beside_the_runs_it_does_have(
    install_transport, monkeypatch
):
    monkeypatch.setenv("REPOBRIDGE_STORAGE", "ephemeral")
    _install(install_transport, _tree())
    assert _analyze().status_code == 200

    html = client.get("/").text
    assert "Stored runs do not survive a restart on this instance." in html


def test_a_fresh_database_serves_every_page_without_breaking(monkeypatch):
    """Nothing assumes a run exists. The first visitor to a wiped instance sees a UI."""
    monkeypatch.setenv("REPOBRIDGE_DEPLOYMENT", "shared")
    monkeypatch.setenv("REPOBRIDGE_STORAGE", "ephemeral")

    assert client.get("/").status_code == 200
    assert client.get("/api/runs").json() == {
        "total": 0,
        "unfiltered_total": 0,
        "limit": 20,
        "offset": 0,
        "filters": {"status": None, "owner": None, "since": None, "until": None},
        "items": [],
    }
    assert client.get("/health").json()["status"] == "ok"
    # and an unknown run is a clean 404, not a crash
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/diagnostics").status_code == 404


# --------------------------------------------------------------------------
# the README documents the deployment surface
# --------------------------------------------------------------------------


def test_the_readme_documents_every_deployment_variable():
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for name in (
        "REPOBRIDGE_DEPLOYMENT",
        "REPOBRIDGE_MAX_ANALYSES_PER_HOUR",
        "REPOBRIDGE_MAX_ANALYSES_PER_HOUR_PER_CLIENT",
        "REPOBRIDGE_MAX_REPO_ENTRIES",
        "REPOBRIDGE_STORAGE",
        "PORT",
    ):
        assert f"`{name}`" in readme, f"{name} is undocumented"


def test_the_readme_warns_that_limits_are_per_process():
    """The failure mode is silent: two workers means double the configured limit."""
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "per-process" in readme
    assert "one worker" in readme.lower()


# --------------------------------------------------------------------------
# the Dockerfile, checked as far as it can be without a Docker daemon
# --------------------------------------------------------------------------

#: Docker is not installed in the environment this project is developed in, so the image
#: has never been built or run. These assertions cover the class of mistake that would
#: otherwise only surface at deploy time -- a variable the app does not read, a path that
#: is not copied, an entrypoint that does not exist -- and they are explicitly **not** a
#: substitute for building it. See `smoke.md` and the README.


def _dockerfile() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")


def test_every_environment_variable_the_dockerfile_sets_is_one_the_app_reads():
    """A typo'd variable name in an image is invisible until the limit does not apply."""
    import re

    import dataclasses

    from repobridge import config

    known = set()
    for cls in (
        config.GitHubConfig, config.DatabaseConfig, config.ExtractionConfig,
        config.SummarizationConfig, config.DeploymentConfig,
    ):
        instance = cls()
        for field in dataclasses.fields(cls):
            if field.name.endswith("_env_var"):
                known.add(getattr(instance, field.name))
            if field.name.endswith("_env_vars"):
                known.update(getattr(instance, field.name))

    # Python's own, plus pip's, which the app does not read and should not have to.
    runtime = {"PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "PIP_NO_CACHE_DIR"}

    for name in re.findall(r"^ENV ([A-Z_][A-Z0-9_]*)=", _dockerfile(), re.M):
        assert name in known or name in runtime, (
            f"the Dockerfile sets {name}, which nothing in config.py reads"
        )


def test_the_database_url_the_dockerfile_sets_parses_to_the_directory_it_creates():
    """
    The four-slash absolute-path form is easy to get wrong by one character, and the
    failure is `unable to open database file` at startup with no other clue.
    """
    import re

    from repobridge.infra.db import sqlite_path

    match = re.search(r"^ENV REPOBRIDGE_DATABASE_URL=(\S+)", _dockerfile(), re.M)
    assert match, "the image must pin the database somewhere other than the working directory"

    url = match.group(1)
    # The path *inside the image*, not resolved against this host's filesystem --
    # `sqlite_path` resolves, which is right for telling a user which file to delete and
    # wrong for checking what a Linux container will open.
    _, _, in_image = url.partition(":///")
    assert in_image == "/data/repobridge.db", in_image
    assert sqlite_path(url) is not None, "and the URL is one this project can parse at all"

    assert "RUN mkdir -p /data" in _dockerfile(), "the directory must exist and be writable"
    assert "chown" in _dockerfile() and "nobody" in _dockerfile()


def test_the_image_entrypoint_exists_and_reads_the_platform_port():
    import importlib

    dockerfile = _dockerfile()
    assert 'CMD ["python", "-m", "repobridge"]' in dockerfile
    assert importlib.util.find_spec("repobridge.__main__") is not None

    # and the module it runs is the one that honours PORT
    from repobridge import __main__ as entry

    assert hasattr(entry, "main")
    assert "ENV PORT=" in dockerfile


def test_everything_the_dockerfile_copies_exists():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for line in re.findall(r"^COPY (.+)$", _dockerfile(), re.M):
        parts = line.split()
        for source in parts[:-1]:          # the last token is the destination
            assert (root / source).exists(), f"Dockerfile copies {source}, which is absent"


def test_the_image_does_not_bake_in_a_key():
    """A key in a layer is a key you cannot revoke by deleting the container."""
    dockerfile = _dockerfile()
    for secret in ("REPOBRIDGE_GITHUB_TOKEN=", "REPOBRIDGE_GEMINI_API_KEY="):
        for line in dockerfile.splitlines():
            stripped = line.strip()
            if stripped.startswith(("ENV", "ARG")) and secret in stripped:
                raise AssertionError(f"the image sets {secret} at build time")
