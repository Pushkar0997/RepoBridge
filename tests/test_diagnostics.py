"""
Diagnostics: the ordered account of a run.

These tests hold the timeline to `evals.md`'s Milestone 7 criteria rather than to the
implementation. The criteria, verbatim:

    What to verify:  the diagnostics view shows each major stage; skipped files and
                     failure reasons are visible; partial success is explicitly
                     represented; error cases are understandable without reading logs.
    Success:         every meaningful failure has a trace; diagnostics help explain what
                     happened; the system does not hide limitations; **rate-limit
                     conditions are visible in diagnostics**.
    Failure signals: missing stage events; empty or vague diagnostics; runs that appear
                     successful despite major failures.

The rate-limit criterion is the one moved into Milestone 7 from Milestone 2 by the
2026-08-17 amendment, because Milestone 2 builds no diagnostics to show it in. It is
tested here as a first-class requirement, in its own section.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.api import routes_runs
from repobridge.core.diagnostics import Level, Recorder, Stage, redact
from repobridge.main import app
from tests.test_api import FILE_CONTENTS, REPO_URL, _blob, _contents_response, _dir, _install, _tree_body

client = TestClient(app)


@pytest.fixture(autouse=True)
def _api_database(isolated_database):
    return isolated_database


@pytest.fixture
def provider(monkeypatch):
    def install(text="A grounded summary.", error=None):
        async def call(prompt: str) -> str:
            if error is not None:
                raise error
            return text

        monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
        app.dependency_overrides[routes_runs.get_summary_provider] = lambda: call

    try:
        yield install
    finally:
        app.dependency_overrides.pop(routes_runs.get_summary_provider, None)


def _entries():
    return [
        _dir("src"),
        _blob("README.md", 40),
        _blob("src/app.py", 40),
        _blob("nb.ipynb", 400),
        _blob("assets/logo.png", 4000),   # skipped, never read
        _blob("package-lock.json", 900),  # skipped, lockfile
    ]


def _analyze(install_transport, entries=None, content_responder=None, tree_responder=None):
    _install(
        install_transport,
        tree_responder or (lambda ref: httpx.Response(200, json=_tree_body(entries or _entries()))),
        content_responder=content_responder,
    )
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()


def _diagnostics(run_id, **params):
    r = client.get(f"/api/runs/{run_id}/diagnostics", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _stages(payload):
    return [e["stage"] for e in payload["items"]]


def _find(payload, *, stage=None, level=None, contains=None, path=None):
    out = payload["items"]
    if stage:
        out = [e for e in out if e["stage"] == stage]
    if level:
        out = [e for e in out if e["level"] == level]
    if contains:
        out = [e for e in out if contains.lower() in e["message"].lower()]
    if path:
        out = [e for e in out if e["path"] == path]
    return out


# --------------------------------------------------------------------------
# "the diagnostics view shows each major stage"
# --------------------------------------------------------------------------


def test_every_stage_of_a_complete_run_is_recorded(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    payload = _diagnostics(body["run_id"])

    for stage in ("validation", "metadata", "tree", "classification",
                  "content", "extraction", "summarization", "persistence"):
        assert stage in _stages(payload), f"no event for stage {stage}"


def test_events_are_returned_in_pipeline_order(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    payload = _diagnostics(body["run_id"])

    sequences = [e["sequence"] for e in payload["items"]]
    assert sequences == sorted(sequences)
    stages = _stages(payload)
    assert stages.index("validation") < stages.index("metadata") < stages.index("tree")


def test_the_stage_rollup_names_each_stage_with_its_worst_level(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    payload = _diagnostics(body["run_id"])

    stages = {row["stage"]: row for row in payload["stages"]}
    assert "classification" in stages
    assert stages["classification"]["events"] >= 1
    assert stages["classification"]["worst_level"] == "partial"  # 2 files skipped


def test_a_stage_that_never_ran_is_absent_rather_than_shown_as_healthy(install_transport):
    """For a run that failed at metadata, the absence of a tree stage is the information."""
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["error"]["details"]["run_id"]
    payload = _diagnostics(run_id)

    assert "tree" not in _stages(payload)
    assert "classification" not in _stages(payload)
    assert _find(payload, stage="metadata", level="error")


# --------------------------------------------------------------------------
# "every meaningful failure has a trace" / "why not if it failed"
# --------------------------------------------------------------------------


def test_a_degraded_runs_tree_failure_appears_with_its_reason(install_transport, provider):
    provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    body = _analyze(install_transport, tree_responder=responder)
    payload = _diagnostics(body["run_id"])

    failures = _find(payload, stage="tree", level="degraded")
    assert failures, "a tree failure must appear in diagnostics"
    event = failures[0]
    assert "Could not reach the GitHub API" in event["message"]
    assert event["details"]["reason"] == "github_error"
    # and the consequence is recorded too, not left to be inferred
    assert _find(payload, stage="classification", contains="nothing to classify")


def test_a_bad_ref_is_an_error_naming_the_ref(install_transport):
    """
    A named ref that does not exist must leave a trace, not vanish.

    This asserts the stored run and its stored timeline, not a recorder built inside the
    test: the previous version of this test constructed its own `Recorder`, recorded an
    event into it and asserted the event was there, which was true no matter what the
    pipeline did.
    """
    _install(
        install_transport,
        lambda ref: httpx.Response(404, json={"message": "Not Found"}),
    )
    resp = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "no-such-branch"}
    )
    assert resp.status_code == 404

    # the failed run is reachable from the error, as it is for a metadata failure
    run_id = resp.json()["error"]["details"]["run_id"]
    payload = _diagnostics(run_id)

    hits = _find(payload, stage="tree", level="error")
    assert hits, "a ref that does not exist must appear in diagnostics"
    assert "no-such-branch" in hits[0]["message"]
    assert hits[0]["details"]["reason"] == "ref_not_found"
    assert hits[0]["details"]["requested_ref"] == "no-such-branch"

    # and the run itself says it failed, rather than being absent
    assert payload["run_status"] == "failed"
    assert payload["outcome"]["has_failures"] is True
    assert payload["outcome"]["clean"] is False


def test_a_bad_ref_run_records_that_the_repository_itself_resolved(install_transport):
    """
    The distinction worth storing: the repo was real, the ref was not.

    Metadata succeeded before the tree call failed, so the stored run carries it. A bare
    failure would leave a user unable to tell a typo'd branch from a typo'd repository.
    """
    _install(
        install_transport,
        lambda ref: httpx.Response(404, json={"message": "Not Found"}),
    )
    resp = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "no-such-branch"}
    )
    run_id = resp.json()["error"]["details"]["run_id"]
    payload = _diagnostics(run_id)

    # metadata is an info event, not an error: that stage did its job
    assert _find(payload, stage="metadata", level="info")
    assert not _find(payload, stage="metadata", level="error")
    # and the stored run kept what metadata returned
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["metadata"]["default_branch"] == "main"
    assert run["status"] == "failed"
    assert run["resolved_ref"] is None       # nothing was ever confirmed
    assert "no-such-branch" in run["error"]


def test_a_bad_ref_leaves_a_readable_run_page(install_transport):
    """The failure must be understandable from the UI, not only from the logs."""
    _install(
        install_transport,
        lambda ref: httpx.Response(404, json={"message": "Not Found"}),
    )
    resp = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "no-such-branch"}
    )
    run_id = resp.json()["error"]["details"]["run_id"]

    page = client.get(f"/runs/{run_id}/diagnostics").text
    assert "no-such-branch" in page
    assert "This run failed" in page


def test_a_per_file_failure_is_findable_by_path(install_transport, provider):
    provider()

    def content_responder(path: str) -> httpx.Response:
        if path == "src/app.py":
            return httpx.Response(404, json={"message": "Not Found"})
        return _contents_response(path, FILE_CONTENTS.get(path, "x\n"))

    body = _analyze(install_transport, content_responder=content_responder)
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, path="src/app.py")
    assert len(hits) == 1, "the file that failed must have its own event"
    assert hits[0]["level"] == "degraded"
    assert hits[0]["stage"] == "content"
    assert hits[0]["details"]["reason"] == "read_failed"


def test_a_summary_provider_failure_is_recorded(install_transport, provider):
    from repobridge.core.summarization import SummarizationError

    provider(error=SummarizationError("The summarisation provider returned status 503."))
    body = _analyze(install_transport)
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, stage="summarization", level="degraded")
    assert hits and "503" in hits[0]["message"]


def test_a_missing_key_is_visible_as_a_reason_not_a_silence(install_transport):
    body = _analyze(install_transport)  # no key configured
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, stage="summarization", level="degraded")
    assert hits and hits[0]["details"]["reason"] == "not_configured"


# --------------------------------------------------------------------------
# "partial success is explicitly represented" / "does not hide limitations"
# --------------------------------------------------------------------------


def test_skipped_files_are_visible_with_their_reasons(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, stage="classification", level="partial")
    assert hits
    details = hits[0]["details"]
    assert details["skipped_non_text_asset"] == 1
    assert details["skipped_lockfile"] == 1


def test_the_read_cap_is_reported_as_partial_with_numbers(install_transport, provider, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body = _analyze(install_transport, entries)
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, stage="content", level="partial")
    assert hits
    assert hits[0]["details"]["not_fetched"] == 8
    assert hits[0]["details"]["read_cap"] == 2
    assert payload["outcome"]["is_partial"] is True


def test_truncation_is_reported_as_partial(install_transport, provider):
    provider()
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(_entries(), truncated=True)),
    )
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, stage="tree", level="partial")
    assert hits and hits[0]["details"]["truncated"] is True
    assert "never saw" in hits[0]["message"]


def test_a_partial_event_always_carries_numbers(install_transport, provider, monkeypatch):
    """
    The rule that keeps PARTIAL from becoming the vague catch-all `evals.md` warns about:
    if an event cannot say how much was lost, it is not PARTIAL.
    """
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body = _analyze(install_transport, entries)
    payload = _diagnostics(body["run_id"])

    for event in _find(payload, level="partial"):
        numeric = [v for v in (event["details"] or {}).values() if isinstance(v, int)]
        assert numeric or any(ch.isdigit() for ch in event["message"]), event


def test_a_clean_run_says_so(install_transport, provider):
    provider()
    entries = [_blob("README.md", 40)]
    body = _analyze(install_transport, entries)
    payload = _diagnostics(body["run_id"])

    assert payload["outcome"]["clean"] is True
    assert payload["outcome"]["has_failures"] is False
    assert payload["counts_by_level"]["error"] == 0


def test_a_run_with_failures_never_reports_itself_clean(install_transport, provider):
    """`evals.md` failure signal: runs that appear successful despite major failures."""
    provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    body = _analyze(install_transport, tree_responder=responder)
    payload = _diagnostics(body["run_id"])

    assert payload["outcome"]["clean"] is False
    assert payload["outcome"]["has_failures"] is True


def test_filtering_narrows_events_but_never_the_totals(install_transport, provider):
    """A reader must not be able to narrow the view until a run looks clean."""
    provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    body = _analyze(install_transport, tree_responder=responder)
    unfiltered = _diagnostics(body["run_id"])
    filtered = _diagnostics(body["run_id"], level="info")

    assert len(filtered["items"]) < len(unfiltered["items"])
    assert filtered["counts_by_level"] == unfiltered["counts_by_level"]
    assert filtered["outcome"]["has_failures"] is True


# --------------------------------------------------------------------------
# rate limits: the criterion moved from Milestone 2
# --------------------------------------------------------------------------


def _rate_limited(reset_epoch="1787056707"):
    return httpx.Response(
        403,
        headers={
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Limit": "60",
            "X-RateLimit-Used": "60",
            "X-RateLimit-Reset": reset_epoch,
            "X-RateLimit-Resource": "core",
        },
        json={"message": "API rate limit exceeded"},
    )


def test_a_metadata_rate_limit_is_visible_in_diagnostics(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: _rate_limited(),
    )
    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})
    assert resp.status_code == 429

    payload = _diagnostics(resp.json()["error"]["details"]["run_id"])
    hits = _find(payload, stage="metadata", level="error")
    assert hits, "a rate limit must appear in diagnostics, not only in the HTTP response"
    assert hits[0]["details"]["reason"] == "rate_limit"


def test_the_rate_limit_event_says_which_quota_and_when_it_resets(install_transport, monkeypatch):
    # unauthenticated on purpose: the 60/hour quota is the case where "authenticate" is
    # the useful action, and the assertion must not depend on the developer's own token
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: _rate_limited(),
    )
    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})
    details = _find(_diagnostics(resp.json()["error"]["details"]["run_id"]), stage="metadata")[0]["details"]

    assert details["kind"] == "primary"
    assert details["resource"] == "core"          # which quota
    assert details["limit"] == "60"
    assert details["remaining"] == "0"
    assert "reset_at" in details and "UTC" in details["reset_at"]   # when it resets
    assert details["authenticated"] is False       # actionable: authenticate


def test_a_tree_rate_limit_degrades_the_run_and_is_visible(install_transport):
    """The live case from `smoke.md` Run 1: metadata succeeded, the tree was rate-limited."""
    _install(install_transport, lambda ref: _rate_limited())
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()

    payload = _diagnostics(body["run_id"])
    hits = _find(payload, stage="tree", level="degraded")
    assert hits
    assert hits[0]["details"]["reason"] == "rate_limit"
    assert hits[0]["details"]["resource"] == "core"


def test_a_secondary_rate_limit_is_distinguished_from_a_primary_one(install_transport):
    secondary = httpx.Response(
        403,
        headers={"Retry-After": "60", "X-RateLimit-Remaining": "4321", "X-RateLimit-Resource": "core"},
        json={"message": "secondary rate limit"},
    )
    _install(install_transport, lambda ref: secondary)
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()

    details = _find(_diagnostics(body["run_id"]), stage="tree")[0]["details"]
    assert details["kind"] == "secondary"
    assert details["retry_after_seconds"] == "60"


def test_the_gemini_daily_quota_decision_is_visible_in_the_timeline(install_transport, provider):
    """
    Not a provider_error string: the *decision* not to retry, and why, as fields.

    A daily-quota 429 advertises a ~58s retryDelay while the allowance does not return
    until the quota-day boundary. That RepoBridge recognised this and deliberately failed
    fast is what a reader needs; "provider returned an error" would not distinguish it from
    an outage.
    """
    from repobridge.core.summarization import SummarizationError

    provider(error=SummarizationError(
        "The summarisation provider's daily request quota is exhausted.",
        {
            "kind": "daily_quota",
            "quota_id": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "model": "gemini-3.5-flash-lite",
            "attempts": 1,
            "retry_decision": "fail_fast",
            "advertised_retry_delay_seconds": 58.0,
        },
    ))
    body = _analyze(install_transport)
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, stage="summarization", level="degraded")
    assert hits
    details = hits[0]["details"]
    assert details["reason"] == "daily_quota"
    assert details["retry_decision"] == "fail_fast"
    assert details["quota_id"] == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    assert details["advertised_retry_delay_seconds"] == 58.0


async def test_the_summarization_error_carries_structured_detail_from_the_provider(
    real_provider_call,
):
    """The detail the timeline shows is built where the decision is made, not guessed."""
    from repobridge.config import SummarizationConfig
    from repobridge.core.summarization import SummarizationError

    body = {
        "error": {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "58s"},
            ]
        }
    }

    class _Mocked(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(429, json=body))
            super().__init__(*a, **kw)

    import repobridge.core.summarization as summarization

    original = summarization.httpx.AsyncClient
    summarization.httpx.AsyncClient = _Mocked
    try:
        with pytest.raises(SummarizationError) as excinfo:
            await real_provider_call("prompt", SummarizationConfig(), "key")
    finally:
        summarization.httpx.AsyncClient = original

    detail = excinfo.value.detail
    assert detail["kind"] == "daily_quota"
    assert detail["retry_decision"] == "fail_fast"
    assert detail["advertised_retry_delay_seconds"] == 58.0
    assert detail["quota_id"] == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


# --------------------------------------------------------------------------
# volume: aggregates, not a row per entry
# --------------------------------------------------------------------------


def test_a_large_run_does_not_write_a_row_per_entry(install_transport, provider):
    """
    2,000 entries of which 1,000 are skipped. kubernetes/kubernetes is 37,393; the shape of
    the guarantee is the same and this keeps the test fast.
    """
    provider()
    entries = (
        [_blob(f"src/file_{i:04d}.py", 40) for i in range(1000)]
        + [_blob(f"assets/img_{i:04d}.png", 40) for i in range(1000)]
    )
    body = _analyze(install_transport, entries)
    payload = _diagnostics(body["run_id"])

    assert body["classification"]["total_entries"] == 2000
    assert body["classification"]["skipped_count"] == 1000
    assert payload["total"] < 30, (
        f"{payload['total']} events for a 2,000-entry run; diagnostics must "
        "aggregate rather than write a row per entry"
    )
    # and the aggregate is still exact
    hit = _find(payload, stage="classification", level="partial")[0]
    assert hit["details"]["skipped_non_text_asset"] == 1000


def test_per_file_failure_events_are_capped_and_the_remainder_counted(install_transport, provider):
    provider()

    def content_responder(path: str) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(80)]
    body = _analyze(install_transport, entries, content_responder=content_responder)
    payload = _diagnostics(body["run_id"])

    per_file = [e for e in payload["items"] if e["path"]]
    assert len(per_file) == 50, f"expected the cap of 50, got {len(per_file)}"

    overflow = _find(payload, contains="not listed individually")
    assert overflow, "the suppressed remainder must still be counted"
    assert overflow[0]["details"]["suppressed"] == 30
    # the exact total is still reported by the stage aggregate
    assert _find(
        payload, stage="content", contains="could not be retrieved"
    )[0]["details"]["failed"] == 80


def test_a_file_that_succeeded_gets_no_row_of_its_own(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    payload = _diagnostics(body["run_id"])

    assert [e for e in payload["items"] if e["path"]] == []


# --------------------------------------------------------------------------
# secrets
# --------------------------------------------------------------------------

GITHUB_TOKEN = "ghp_DIAGNOSTICSTOKENMUSTNEVERBELOGGED0000"
GEMINI_KEY = "AIzaSyDIAGNOSTICSKEYMUSTNEVERBELOGGED00000"


def test_no_secret_value_appears_in_any_event(install_transport, monkeypatch, provider):
    """
    A value scan, as the storage layer is tested -- not a check that the *names* are absent.
    Scans every column of every stored event, not just the message.
    """
    from sqlalchemy import select

    from repobridge.infra.schemas import AnalysisEvent

    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", GITHUB_TOKEN)
    provider()
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", GEMINI_KEY)

    body = _analyze(install_transport)

    async def scan(database):
        async with database.session() as session:
            rows = (await session.execute(select(AnalysisEvent))).scalars().all()
            assert rows, "the run recorded no events, so this test proves nothing"
            for row in rows:
                for column in AnalysisEvent.__table__.columns:
                    value = str(getattr(row, column.name))
                    assert GITHUB_TOKEN not in value
                    assert GEMINI_KEY not in value

    import asyncio

    from repobridge.infra.db import get_database

    asyncio.run(scan(get_database()))
    # and not through the API either
    assert GITHUB_TOKEN not in client.get(f"/api/runs/{body['run_id']}/diagnostics").text
    assert GEMINI_KEY not in client.get(f"/runs/{body['run_id']}/diagnostics").text


def test_a_secret_that_reaches_an_event_is_redacted(monkeypatch):
    """
    The defensive layer. Nothing should put a token in an event; if something does -- an
    exception carrying a URL, say -- it is scrubbed rather than stored.
    """
    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", GITHUB_TOKEN)
    events = Recorder()
    event = events.record(
        Stage.METADATA,
        Level.ERROR,
        f"Request failed for https://x@{GITHUB_TOKEN}/repos",
        url=f"https://api.github.com?token={GITHUB_TOKEN}",
        nested={"header": f"Bearer {GITHUB_TOKEN}"},
    )

    assert GITHUB_TOKEN not in event.message
    assert "[redacted]" in event.message
    assert GITHUB_TOKEN not in str(event.details)


def test_redact_leaves_ordinary_text_alone(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REPOBRIDGE_GEMINI_API_KEY", raising=False)
    assert redact("nothing secret here") == "nothing secret here"


# --------------------------------------------------------------------------
# the endpoint and the page
# --------------------------------------------------------------------------


def test_the_endpoint_404s_on_an_unknown_run():
    assert client.get("/api/runs/nope/diagnostics").status_code == 404


def test_the_page_404s_on_an_unknown_run():
    assert client.get("/runs/nope/diagnostics").status_code == 404


def test_the_page_renders_a_timeline(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    page = client.get(f"/runs/{body['run_id']}/diagnostics").text

    assert "Timeline" in page
    assert "classification" in page
    assert "Diagnostics" in page


def test_the_page_makes_a_partial_run_obvious(install_transport, provider, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body = _analyze(install_transport, entries)

    page = client.get(f"/runs/{body['run_id']}/diagnostics").text
    assert "This run is partial" in page


def test_the_banner_states_both_conditions_when_a_run_is_partial_and_degraded(
    install_transport, monkeypatch
):
    """
    The combined case. Neither single-condition test covers it, and neither caught it.

    `smoke.md` Run 10 Case 4, live: 87 of 107 selected files unread (partial) *and* no
    summary (degraded). The banner was one if/elif chain on the worst level, so it
    announced only "completed with failures" and never that 81% of the selected files were
    never opened. Everything else on the page carried it; the banner is the line a reader
    actually reads.

    No `provider` fixture here on purpose: the withheld key is what supplies the degraded
    half, exactly as in Run 10.
    """
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body = _analyze(install_transport, entries)
    payload = _diagnostics(body["run_id"])

    # both conditions genuinely hold, so the assertion below is about the banner and not
    # about having accidentally built a run that is only one of the two
    assert payload["outcome"]["is_partial"] is True
    assert payload["outcome"]["has_failures"] is True

    page = client.get(f"/runs/{body['run_id']}/diagnostics").text
    assert "completed with failures" in page
    assert "also partial" in page, "the banner must not drop the partiality"


def test_a_failed_run_that_is_also_partial_says_both(install_transport, monkeypatch):
    """The same combination one level up, where the run ends rather than continues."""
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(
            [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)], truncated=True)),
    )
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()
    payload = _diagnostics(body["run_id"])

    assert payload["outcome"]["is_partial"] is True
    assert payload["outcome"]["has_failures"] is True
    page = client.get(f"/runs/{body['run_id']}/diagnostics").text
    assert "also partial" in page


def test_a_run_with_failures_but_no_shortfall_does_not_claim_partiality(
    install_transport, provider
):
    """The other half of the fix: the clause is additive, not always-on."""
    provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    body = _analyze(install_transport, tree_responder=responder)
    payload = _diagnostics(body["run_id"])

    assert payload["outcome"]["has_failures"] is True
    assert payload["outcome"]["is_partial"] is False
    page = client.get(f"/runs/{body['run_id']}/diagnostics").text
    assert "completed with failures" in page
    assert "also partial" not in page


def test_a_purely_partial_run_keeps_its_own_wording(install_transport, provider, monkeypatch):
    """
    A partial run with nothing failed still says "every stage completed", which is why the
    combined case needed a separate clause rather than concatenating this one.
    """
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body = _analyze(install_transport, entries)
    payload = _diagnostics(body["run_id"])

    assert payload["outcome"]["has_failures"] is False
    page = client.get(f"/runs/{body['run_id']}/diagnostics").text
    assert "This run is partial" in page
    assert "Every stage completed" in page
    assert "also partial" not in page


def test_the_page_makes_a_failed_stage_obvious(install_transport, provider):
    provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    body = _analyze(install_transport, tree_responder=responder)
    page = client.get(f"/runs/{body['run_id']}/diagnostics").text

    assert "completed with failures" in page


def test_the_page_says_so_when_a_run_is_complete(install_transport, provider):
    provider()
    body = _analyze(install_transport, [_blob("README.md", 40)])
    page = client.get(f"/runs/{body['run_id']}/diagnostics").text

    assert "This run is complete" in page


def test_the_run_detail_page_links_to_diagnostics(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    page = client.get(f"/runs/{body['run_id']}").text
    assert f"/runs/{body['run_id']}/diagnostics" in page


def test_re_summarising_appends_to_the_timeline_rather_than_reordering_it(
    install_transport, provider
):
    """
    The ordering assertion, made on ORDER and not on message content.

    The bug this pins: a fresh `Recorder` numbers from zero, so re-summarised events used
    to be stored with sequences 0 and 1 against a run that already held eight. Ordering by
    sequence then sorted "Re-summarising from stored content" in *before* the tree was
    retrieved. Every assertion here is positional; the previous test searched by substring
    and passed throughout.
    """
    provider()
    body = _analyze(install_transport, [_blob("README.md", 40)])
    run_id = body["run_id"]

    before = [e["sequence"] for e in _diagnostics(run_id)["items"]]
    assert before == sorted(before)
    assert before == list(range(len(before))), "the first write should number from zero"

    client.post(f"/api/runs/{run_id}/summarize")
    after = _diagnostics(run_id)["items"]
    sequences = [e["sequence"] for e in after]

    # strictly increasing: no restart, and no two events claiming the same position
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences)), f"duplicate sequences: {sequences}"
    # append-only: everything already stored keeps its position, and the new events
    # land after all of it rather than in the middle
    assert sequences[: len(before)] == before
    assert min(s["sequence"] for s in after if "Re-summarising" in s["message"]) > max(before)
    # the run still begins where it began
    assert after[0]["stage"] == "validation"
    assert [e["stage"] for e in after].index("tree") < [
        e["stage"] for e in after
    ].index("persistence")


def test_re_summarising_twice_keeps_extending_the_same_timeline(install_transport, provider):
    """Two appends, not two restarts: the guarantee has to survive repetition."""
    provider()
    run_id = _analyze(install_transport, [_blob("README.md", 40)])["run_id"]

    client.post(f"/api/runs/{run_id}/summarize")
    client.post(f"/api/runs/{run_id}/summarize")

    sequences = [e["sequence"] for e in _diagnostics(run_id)["items"]]
    assert sequences == sorted(set(sequences)), f"not strictly increasing: {sequences}"
    assert len([e for e in _diagnostics(run_id)["items"]
                if "Re-summarising" in e["message"]]) == 2


def test_re_summarising_records_its_own_events(install_transport, provider):
    provider(error=__import__(
        "repobridge.core.summarization", fromlist=["SummarizationError"]
    ).SummarizationError("provider down"))
    body = _analyze(install_transport)

    provider("Recovered.")
    client.post(f"/api/runs/{body['run_id']}/summarize")

    payload = _diagnostics(body["run_id"])
    assert _find(payload, stage="summarization", contains="Re-summarising from stored content")
    assert _find(payload, stage="summarization", contains="Summary generated by")


# --------------------------------------------------------------------------
# a parse failure is not a read failure
# --------------------------------------------------------------------------


def _malformed_notebook_responder(bad="bad.ipynb"):
    def responder(path: str) -> httpx.Response:
        if path == bad:
            return _contents_response(path, "{ not valid json ")
        return _contents_response(path, FILE_CONTENTS.get(path, "# hi" + chr(10)))

    return responder


def test_a_malformed_file_is_an_extraction_failure_not_a_read_failure(
    install_transport, provider
):
    """
    `spec.md` section 7 lists extraction and parsing outcomes as their own diagnostic
    category. A notebook that arrived intact and would not parse is not a read failure:
    filing it as one names the wrong stage and sends a reader to look at the network.
    """
    provider()
    entries = [_blob("bad.ipynb", 400), _blob("README.md", 40)]
    body = _analyze(
        install_transport, entries, content_responder=_malformed_notebook_responder()
    )
    payload = _diagnostics(body["run_id"])

    hits = _find(payload, path="bad.ipynb")
    assert len(hits) == 1
    assert hits[0]["stage"] == "extraction", "a parse failure belongs to extraction"
    assert hits[0]["details"]["reason"] == "extraction_failed"
    assert "not valid JSON" in hits[0]["message"]
    # and it is not also reported as a content failure
    assert not _find(payload, stage="content", path="bad.ipynb")


def test_the_extraction_stage_can_report_a_failure_at_all(install_transport, provider):
    """Before this, `extraction` emitted exactly one INFO event and could never fail."""
    provider()
    entries = [_blob("bad.ipynb", 400), _blob("README.md", 40)]
    body = _analyze(
        install_transport, entries, content_responder=_malformed_notebook_responder()
    )
    payload = _diagnostics(body["run_id"])

    rollup = {row["stage"]: row for row in payload["stages"]}
    assert rollup["extraction"]["worst_level"] == "degraded"
    partial = _find(payload, stage="extraction", level="partial")
    assert partial and partial[0]["details"]["failed"] == 1


def test_read_and_parse_failures_are_reported_separately_in_the_same_run(
    install_transport, provider
):
    """One of each, in one run: the counts must not merge back together."""
    provider()

    def content_responder(path: str) -> httpx.Response:
        if path == "bad.ipynb":
            return _contents_response(path, "{ not valid json ")
        if path == "gone.py":
            return httpx.Response(404, json={"message": "Not Found"})
        return _contents_response(path, "# hi" + chr(10))

    entries = [_blob("bad.ipynb", 400), _blob("gone.py", 40), _blob("README.md", 40)]
    body = _analyze(install_transport, entries, content_responder=content_responder)
    payload = _diagnostics(body["run_id"])

    assert _find(payload, stage="content", path="gone.py")[0]["details"][
        "reason"
    ] == "read_failed"
    assert _find(payload, stage="extraction", path="bad.ipynb")[0]["details"][
        "reason"
    ] == "extraction_failed"
    # each aggregate counts only its own kind
    assert _find(payload, stage="content", level="partial")[0]["details"]["failed"] == 1
    assert _find(payload, stage="extraction", level="partial")[0]["details"]["failed"] == 1


def test_the_page_names_the_extraction_stage_for_a_parse_failure(install_transport, provider):
    provider()
    entries = [_blob("bad.ipynb", 400), _blob("README.md", 40)]
    body = _analyze(
        install_transport, entries, content_responder=_malformed_notebook_responder()
    )
    page = client.get(f"/runs/{body['run_id']}/diagnostics").text

    assert "extraction_failed" in page
    assert "bad.ipynb" in page
