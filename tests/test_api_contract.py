"""
Milestone 8: the API as a contract rather than as nine separate habits.

These tests hold the whole surface to one shape at once. They are deliberately written to
iterate over *every* endpoint rather than to check a representative one: the defect this
milestone exists to fix is not that any single endpoint was wrong, it is that endpoints
grown across seven milestones each solved the same problem their own way. A test that
checks one endpoint cannot catch that.

The README conformance test at the bottom is the one worth reading twice. `evals.md`
Milestone 8 asks that "all documented endpoints behave as expected"; the README had been
wrong by two milestones when this was written, claiming extraction, summaries and
diagnostics were "not built yet" long after they shipped. A prose claim nobody executes
rots. This makes the README executable.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.api import routes_runs
from repobridge.main import app
from tests.test_api import REPO_URL, _blob, _dir, _install, _tree_body

client = TestClient(app)

README = Path(__file__).resolve().parents[1] / "README.md"


@pytest.fixture(autouse=True)
def _api_database(isolated_database):
    return isolated_database


@pytest.fixture
def provider(monkeypatch):
    def install(text="A grounded summary."):
        async def call(prompt: str) -> str:
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
        _blob("assets/logo.png", 4000),
        _blob("package-lock.json", 900),
    ]


def _run(install_transport, entries=None):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(entries or _entries())),
    )
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]


#: Every list endpoint, as (name, url template). Kept in one place so a new list endpoint
#: added without the shared shape fails several tests at once rather than none.
LIST_ENDPOINTS = [
    ("runs", "/api/runs"),
    ("files", "/api/runs/{run_id}/files"),
    ("chunks", "/api/runs/{run_id}/chunks"),
    ("diagnostics", "/api/runs/{run_id}/diagnostics"),
]

#: Every endpoint that takes a run id, for the 404 sweep.
RUN_SCOPED = [
    ("get", "/api/runs/{run_id}"),
    ("get", "/api/runs/{run_id}/files"),
    ("get", "/api/runs/{run_id}/chunks"),
    ("get", "/api/runs/{run_id}/summary"),
    ("get", "/api/runs/{run_id}/diagnostics"),
    ("post", "/api/runs/{run_id}/summarize"),
]


# --------------------------------------------------------------------------
# the error envelope: identical everywhere
# --------------------------------------------------------------------------


def _assert_envelope(payload, status: int, code: str | None = None):
    """The shape every error must have, asserted structurally rather than by eye."""
    assert set(payload) == {"error"}, f"error responses carry only 'error': {payload}"
    err = payload["error"]
    assert set(err) == {"status", "code", "message", "details"}, err
    assert err["status"] == status
    assert isinstance(err["code"], str) and err["code"]
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["details"], dict), "details is always an object, never a list"
    if code:
        assert err["code"] == code
    return err


@pytest.mark.parametrize("method,template", RUN_SCOPED)
def test_every_run_scoped_endpoint_404s_with_the_same_envelope(method, template):
    resp = getattr(client, method)(template.format(run_id="no-such-run"))
    assert resp.status_code == 404
    err = _assert_envelope(resp.json(), 404, "run_not_found")
    assert err["details"]["run_id"] == "no-such-run"
    assert "no-such-run" in err["message"]


def test_the_404_message_is_identical_across_every_endpoint():
    """Six endpoints used to carry six copies of this f-string. One copy, one wording."""
    messages = {
        getattr(client, m)(t.format(run_id="x")).json()["error"]["message"]
        for m, t in RUN_SCOPED
    }
    assert len(messages) == 1, f"the same failure is worded {len(messages)} ways: {messages}"


def test_a_rejected_filter_value_uses_the_envelope_and_lists_what_is_valid(install_transport):
    run_id = _run(install_transport)
    for url, field in [
        (f"/api/runs/{run_id}/files?status=bogus", "status"),
        (f"/api/runs/{run_id}/files?reason=bogus", "reason"),
        (f"/api/runs/{run_id}/chunks?chunk_type=bogus", "chunk_type"),
        ("/api/runs?status=bogus", "status"),
    ]:
        resp = client.get(url)
        assert resp.status_code == 400, url
        err = _assert_envelope(resp.json(), 400, "invalid_value")
        assert err["details"]["field"] == field
        assert err["details"]["value"] == "bogus"
        # the accepted set travels as data, not only inside an English sentence
        assert isinstance(err["details"]["valid"], list) and err["details"]["valid"]


def test_a_schema_violation_uses_the_same_envelope_as_everything_else(install_transport):
    """
    The defect this closes: FastAPI's own validation errors returned `{"detail": [...]}`
    while ours returned `{"detail": {...}}` — one key, two incompatible types, so no
    consumer could write a single parser.
    """
    run_id = _run(install_transport)
    resp = client.get(f"/api/runs/{run_id}/files?limit=99999")
    assert resp.status_code == 422
    err = _assert_envelope(resp.json(), 422, "invalid_request")
    assert isinstance(err["details"]["fields"], list) and err["details"]["fields"]
    assert "location" in err["details"]["fields"][0]


def test_an_unparseable_body_uses_the_envelope():
    resp = client.post("/api/analyze", json={"repo_url": "not-a-url"})
    assert resp.status_code == 422
    _assert_envelope(resp.json(), 422, "invalid_request")


def test_a_well_formed_url_pointing_at_the_wrong_host_is_a_400_not_a_422():
    """
    The line between 400 and 422, which is the one place two codes survive on purpose:
    422 means "I could not parse your request", 400 means "I parsed it and it is not
    acceptable". Both share the envelope, so a consumer reads `code`, not the status.
    """
    resp = client.post("/api/analyze", json={"repo_url": "https://gitlab.com/a/b"})
    assert resp.status_code == 400
    _assert_envelope(resp.json(), 400, "invalid_repo_url")


def test_an_unrouted_path_also_uses_the_envelope():
    """Starlette's own 404, which never passes through our helpers."""
    resp = client.get("/api/no-such-thing")
    assert resp.status_code == 404
    _assert_envelope(resp.json(), 404)


def test_a_wrong_method_also_uses_the_envelope():
    resp = client.post("/api/runs")
    assert resp.status_code == 405
    _assert_envelope(resp.json(), 405)


def test_an_internal_failure_blames_this_application_and_leaks_nothing(monkeypatch):
    """
    500, not a 4xx invented to describe a bug of ours — and the exception text stays in
    the log. An unhandled exception is the error path nobody wrote on purpose, so it is
    the one least likely to have been checked for a token in its message.
    """
    def boom(*a, **kw):
        raise RuntimeError("secret-bearing detail ghp_TOKENLIKESTRING")

    monkeypatch.setattr(routes_runs.storage, "list_runs", boom)
    quiet = TestClient(app, raise_server_exceptions=False)
    resp = quiet.get("/api/runs")

    assert resp.status_code == 500
    err = _assert_envelope(resp.json(), 500, "internal_error")
    assert "ghp_TOKENLIKESTRING" not in resp.text
    assert "RuntimeError" not in resp.text
    assert err["details"] == {}


# --------------------------------------------------------------------------
# no secret reaches a log line (CONTRACT I-6)
# --------------------------------------------------------------------------

#: Distinctive enough that a substring match cannot be a coincidence, and long enough
#: that an 8-character window slides across it many times.
LOG_GITHUB_TOKEN = "ghp_LOGTOKENMUSTNEVERREACHALOGLINE000000"
LOG_GEMINI_KEY = "AIzaSyLOGKEYMUSTNEVERREACHALOGLINE000000"


def _assert_no_secret_in(text: str, where: str) -> None:
    """
    The same scan the rendered-page test applies, against captured log output.

    Whole value first, then every 8-character window of it. The fragment half is not
    theoretical here: the GitHub error path logs the upstream body truncated to 500
    characters, and truncating a token leaves precisely such a fragment.
    """
    for name, secret in (("GitHub token", LOG_GITHUB_TOKEN), ("Gemini key", LOG_GEMINI_KEY)):
        assert secret not in text, f"the {name} reached {where}"
        for start in range(0, len(secret) - 8):
            assert secret[start : start + 8] not in text, (
                f"an 8-character fragment of the {name} reached {where}"
            )


@pytest.fixture
def keys_set(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", LOG_GITHUB_TOKEN)
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", LOG_GEMINI_KEY)


@pytest.fixture
def logs(caplog):
    """Capture everything RepoBridge logs, at every level, including DEBUG."""
    import logging

    caplog.set_level(logging.DEBUG, logger="repobridge")
    caplog.set_level(logging.DEBUG)
    return caplog


def test_a_clean_run_puts_no_secret_in_a_log_line(install_transport, keys_set, logs, provider):
    """The ordinary path: metadata, tree, classification, reads, chunks, a summary."""
    provider()
    run_id = _run(install_transport)
    for path in (f"/api/runs/{run_id}", f"/api/runs/{run_id}/diagnostics", "/api/runs"):
        client.get(path)

    assert logs.text, "nothing was captured, so this test proves nothing"
    _assert_no_secret_in(logs.text, "a log line during a clean run")


def test_an_upstream_body_echoing_the_token_is_redacted_before_it_is_logged(
    install_transport, keys_set, logs
):
    """
    GitHub's raw error body is logged for debugging. If it quotes the request's own
    Authorization header back -- which is exactly what a misconfigured proxy or a verbose
    upstream does -- the token lands in the log unless something scrubs it.
    """
    body = f"upstream failure; authorization=Bearer {LOG_GITHUB_TOKEN}; retry later"
    _install(install_transport, lambda ref: httpx.Response(500, text=body))
    client.post("/api/analyze", json={"repo_url": REPO_URL})

    assert "upstream failure" in logs.text, "the body was not logged at all; scan is vacuous"
    _assert_no_secret_in(logs.text, "the GitHub error-body log line")


def test_a_token_split_by_truncation_still_does_not_leak_a_fragment(
    install_transport, keys_set, logs
):
    """
    The reason redaction runs *before* truncation, pinned.

    The upstream body is cut at 500 characters. Put the token so it straddles the cut and
    a scrub-then-truncate order is safe while truncate-then-scrub leaves a live fragment
    that no whole-value check would ever notice.
    """
    padding = "x" * 480
    _install(
        install_transport,
        lambda ref: httpx.Response(500, text=f"{padding}{LOG_GITHUB_TOKEN}{padding}"),
    )
    client.post("/api/analyze", json={"repo_url": REPO_URL})

    _assert_no_secret_in(logs.text, "a truncated upstream body")


def test_an_unhandled_traceback_is_redacted_before_it_reaches_the_log(
    monkeypatch, keys_set, logs
):
    """
    The path that had no guard at all. An unhandled exception is the one nobody wrote on
    purpose, so it is the one least likely to have been checked -- and `logger.exception`
    defers formatting past the last point this code controls.
    """

    def boom(*a, **kw):
        raise RuntimeError(f"connecting with token={LOG_GITHUB_TOKEN} failed")

    monkeypatch.setattr(routes_runs.storage, "list_runs", boom)
    quiet = TestClient(app, raise_server_exceptions=False)
    assert quiet.get("/api/runs").status_code == 500

    assert "RuntimeError" in logs.text, "the traceback was not logged; scan is vacuous"
    assert "Unhandled error serving" in logs.text
    _assert_no_secret_in(logs.text, "the unhandled-exception traceback")


def test_a_provider_failure_puts_no_secret_in_a_log_line(install_transport, keys_set, logs):
    """The summariser logs its own failure, and its message comes from the provider."""

    async def call(prompt: str) -> str:
        raise RuntimeError(f"provider refused key={LOG_GEMINI_KEY}")

    app.dependency_overrides[routes_runs.get_summary_provider] = lambda: call
    try:
        _run(install_transport)
    finally:
        app.dependency_overrides.pop(routes_runs.get_summary_provider, None)

    _assert_no_secret_in(logs.text, "a log line after a provider failure")


# --------------------------------------------------------------------------
# pagination: one shape everywhere
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name,template", LIST_ENDPOINTS)
def test_every_list_endpoint_returns_the_same_pagination_fields(
    name, template, install_transport, provider
):
    provider()
    run_id = _run(install_transport)
    payload = client.get(template.format(run_id=run_id)).json()

    for field in ("total", "unfiltered_total", "limit", "offset", "items", "filters"):
        assert field in payload, f"{name} is missing '{field}'"
    assert isinstance(payload["items"], list), f"{name} must call its list 'items'"
    assert isinstance(payload["filters"], dict)
    assert payload["offset"] == 0
    assert payload["total"] <= payload["unfiltered_total"]


@pytest.mark.parametrize("name,template", LIST_ENDPOINTS)
def test_limit_and_offset_behave_identically_everywhere(
    name, template, install_transport, provider
):
    provider()
    run_id = _run(install_transport)
    # two runs, so `/api/runs` has something to page through as well
    _run(install_transport)
    url = template.format(run_id=run_id)

    full = client.get(url, params={"limit": 100}).json()
    assert full["total"] >= 2, f"{name} has too few rows to prove paging"

    first = client.get(url, params={"limit": 1, "offset": 0}).json()
    second = client.get(url, params={"limit": 1, "offset": 1}).json()

    assert len(first["items"]) == 1 and len(second["items"]) == 1
    assert first["items"] != second["items"]
    # a page never changes the totals
    assert first["total"] == second["total"] == full["total"]
    assert first["unfiltered_total"] == full["unfiltered_total"]
    assert second["offset"] == 1


@pytest.mark.parametrize("name,template", LIST_ENDPOINTS)
def test_an_out_of_range_limit_is_rejected_the_same_way_everywhere(
    name, template, install_transport
):
    run_id = _run(install_transport)
    resp = client.get(template.format(run_id=run_id), params={"limit": 100000})
    assert resp.status_code == 422, name
    _assert_envelope(resp.json(), 422, "invalid_request")


def test_diagnostics_paginates_like_the_others(install_transport, provider):
    """
    Diagnostics used to return everything under `events`/`total_events`, on the reasoning
    that the volume rules keep a run to tens of events. That covers one analysis, not one
    run: re-summarising appends to the same timeline and nothing caps how often.
    """
    provider()
    run_id = _run(install_transport)
    before = client.get(f"/api/runs/{run_id}/diagnostics").json()["unfiltered_total"]

    for _ in range(3):
        client.post(f"/api/runs/{run_id}/summarize")

    after = client.get(f"/api/runs/{run_id}/diagnostics").json()
    assert after["unfiltered_total"] > before, "re-summarising grows the timeline"
    page = client.get(f"/api/runs/{run_id}/diagnostics", params={"limit": 2}).json()
    assert len(page["items"]) == 2
    assert page["total"] == after["unfiltered_total"]


# --------------------------------------------------------------------------
# filters on /api/runs, and the honesty rule about totals
# --------------------------------------------------------------------------


def _make_runs(install_transport):
    """Two completed runs for one owner, one failed run for another."""
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_entries())))
    a = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]
    b = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    failed = client.post(
        "/api/analyze", json={"repo_url": "https://github.com/other/missing"}
    ).json()["error"]["details"]["run_id"]
    return a, b, failed


def test_status_filter_selects_and_never_misreports_the_total(install_transport):
    a, b, failed = _make_runs(install_transport)

    all_runs = client.get("/api/runs").json()
    assert all_runs["total"] == all_runs["unfiltered_total"] == 3

    only_failed = client.get("/api/runs", params={"status": "failed"}).json()
    assert [r["run_id"] for r in only_failed["items"]] == [failed]
    assert only_failed["total"] == 1
    # the honesty rule: a filtered total must never read as an unfiltered one
    assert only_failed["unfiltered_total"] == 3
    assert only_failed["filters"]["status"] == "failed"


def test_owner_filter_is_case_insensitive(install_transport):
    _make_runs(install_transport)
    lower = client.get("/api/runs", params={"owner": "octo"}).json()
    upper = client.get("/api/runs", params={"owner": "OCTO"}).json()

    assert lower["total"] == upper["total"] == 2
    assert [r["run_id"] for r in lower["items"]] == [r["run_id"] for r in upper["items"]]
    assert lower["unfiltered_total"] == 3


def test_date_filters_bound_the_result(install_transport):
    _make_runs(install_transport)

    future = client.get("/api/runs", params={"since": "2099-01-01"}).json()
    assert future["total"] == 0
    assert future["items"] == []
    assert future["unfiltered_total"] == 3, "an empty page must not zero the whole count"

    past = client.get("/api/runs", params={"since": "2000-01-01"}).json()
    assert past["total"] == 3

    assert client.get("/api/runs", params={"until": "2000-01-01"}).json()["total"] == 0


def test_filters_combine(install_transport):
    _make_runs(install_transport)
    both = client.get(
        "/api/runs", params={"owner": "octo", "status": "completed", "since": "2000-01-01"}
    ).json()
    assert both["total"] == 2
    assert both["unfiltered_total"] == 3
    assert both["filters"] == {
        "status": "completed", "owner": "octo", "since": "2000-01-01", "until": None,
    }


def test_a_malformed_date_is_a_400_naming_the_field():
    resp = client.get("/api/runs", params={"since": "last tuesday"})
    assert resp.status_code == 400
    err = _assert_envelope(resp.json(), 400, "invalid_value")
    assert err["details"]["field"] == "since"


def test_filtered_totals_on_files_and_chunks_never_read_as_whole_ones(
    install_transport, provider
):
    """The same rule one level down, where it was already honoured — pinned so it stays."""
    provider()
    run_id = _run(install_transport)

    everything = client.get(f"/api/runs/{run_id}/files").json()
    skipped = client.get(f"/api/runs/{run_id}/files", params={"status": "skipped"}).json()

    assert skipped["total"] < everything["total"]
    assert skipped["unfiltered_total"] == everything["unfiltered_total"]
    # and the tree's own count is still reported, unchanged, alongside it
    assert skipped["run_entry_count"] == everything["run_entry_count"]


# --------------------------------------------------------------------------
# the honesty fields survived the tidying
# --------------------------------------------------------------------------


def test_the_honesty_fields_are_all_still_present_and_still_mean_what_they_meant(
    install_transport, provider, monkeypatch
):
    """
    Every field named here exists because a specific failure was found live and recorded
    in `smoke.md`. Consolidation is allowed to add fields; it is not allowed to quietly
    drop or repurpose one of these.
    """
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(6)]
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(entries, truncated=True)),
    )
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()
    run_id = body["run_id"]

    # tree truncation (Milestone 2)
    assert body["tree_truncated"] is True
    assert "truncat" in (body["tree_error"] or "").lower()
    # the accounting identity (Milestone 3)
    assert body["classification"]["accounts_for_every_entry"] is True
    # the read cap and its partition (Milestone 5, Run 8/9)
    ex = body["extraction"]
    assert ex["read_cap"] == 2 and ex["cap_applied"] is True
    assert ex["files_not_fetched"] == 4
    assert ex["accounts_for_every_selected_file"] is True
    assert ex["read_of_selected"] == "read 2 of 6 selected files"
    # summary provenance (Milestone 6)
    prov = body["summary"]["provenance"]
    assert prov["read_cap"] == 2 and prov["files_not_fetched"] == 4
    assert prov["is_partial"] is True and prov["limitations"]
    # the run's own counts, still on the list endpoints (Milestone 4/5)
    files = client.get(f"/api/runs/{run_id}/files").json()
    assert files["run_entry_count"] == body["tree_entry_count"]
    chunks = client.get(f"/api/runs/{run_id}/chunks").json()
    assert chunks["run_chunk_count"] == ex["chunk_count"]
    assert chunks["run_files_read"] == ex["files_read"]
    # diagnostics quantifies the same shortfall (Milestone 7)
    diag = client.get(f"/api/runs/{run_id}/diagnostics").json()
    partials = [e for e in diag["items"] if e["level"] == "partial"]
    assert partials and any(e["details"].get("not_fetched") == 4 for e in partials)


# --------------------------------------------------------------------------
# the README is a contract, so it is executed
# --------------------------------------------------------------------------


def _documented_endpoints() -> set[tuple[str, str]]:
    """Endpoints the README documents, as `### GET /api/...` headings."""
    text = README.read_text(encoding="utf-8")
    return {
        (m.group(1), m.group(2))
        for m in re.finditer(r"^#{2,4} (GET|POST|PUT|PATCH|DELETE) (/\S*)$", text, re.M)
    }


def _actual_endpoints() -> set[tuple[str, str]]:
    """
    JSON endpoints the app actually serves, read from its own OpenAPI schema.

    Read from `app.openapi()` rather than by walking `app.routes`: the route list holds
    router wrappers whose paths are not directly exposed, and the schema is the same thing
    FastAPI serves at `/docs`, so this checks the README against what a consumer is
    actually told. HTML pages are excluded — they are the UI, not the API.
    """
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api") or path == "/health"
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }


def test_the_readme_documents_every_endpoint_that_exists():
    """
    The README was wrong by two milestones before this test existed — it claimed
    extraction, summaries and diagnostics were "not built yet" long after they shipped.
    A prose claim nobody executes rots. This fails the build when it drifts again.
    """
    missing = _actual_endpoints() - _documented_endpoints()
    assert not missing, (
        "these endpoints exist but the README does not document them: "
        + ", ".join(f"{m} {p}" for m, p in sorted(missing))
    )


def test_the_readme_documents_no_endpoint_that_does_not_exist():
    """The other direction: a documented endpoint that was renamed or never built."""
    invented = _documented_endpoints() - _actual_endpoints()
    assert not invented, (
        "the README documents these, but they do not exist: "
        + ", ".join(f"{m} {p}" for m, p in sorted(invented))
    )


@pytest.mark.parametrize("method,path", sorted(_actual_endpoints()))
def test_every_documented_endpoint_answers(method, path, install_transport, provider):
    """
    Not just that the route is registered — that it responds. A documented endpoint that
    500s is as wrong as one that does not exist.
    """
    provider()
    run_id = _run(install_transport)
    url = path.replace("{run_id}", run_id)

    if method == "POST" and url.endswith("/analyze"):
        resp = client.post(url, json={"repo_url": REPO_URL})
    elif method == "POST":
        resp = client.post(url)
    else:
        resp = client.get(url)

    assert resp.status_code == 200, f"{method} {path} -> {resp.status_code}: {resp.text[:200]}"
    assert resp.headers["content-type"].startswith("application/json")


def test_the_readme_documents_the_error_codes_the_api_actually_raises():
    """Every `code` the helpers can emit must appear in the README's error table."""
    text = README.read_text(encoding="utf-8")
    for code in (
        "invalid_request", "invalid_repo_url", "invalid_value", "run_not_found",
        "repo_not_found", "ref_not_found", "rate_limited", "github_error", "internal_error",
    ):
        assert f"`{code}`" in text, f"error code '{code}' is undocumented"


def test_the_readme_documents_every_environment_variable_config_reads():
    """A config knob nobody can discover is a config knob nobody has."""
    import dataclasses

    from repobridge import config

    text = README.read_text(encoding="utf-8")
    for cls in (
        config.GitHubConfig, config.DatabaseConfig,
        config.ExtractionConfig, config.SummarizationConfig,
    ):
        for field in dataclasses.fields(cls):
            if not field.name.endswith("_env_var"):
                continue
            name = getattr(cls(), field.name)
            assert f"`{name}`" in text, f"environment variable '{name}' is undocumented"


def test_the_readme_no_longer_claims_unbuilt_features():
    """The specific regression: a README that understates the project."""
    text = README.read_text(encoding="utf-8").lower()
    assert "not built yet:** content extraction" not in text
    for built in ("/chunks", "/diagnostics", "/summary", "/summarize"):
        assert built in text, f"{built} is built but undocumented"
