"""
Milestone 9: the four views as one set.

Two things these tests do that the per-milestone tests did not.

**Every page against every run shape.** The pages were built one milestone at a time, each
against the run shape that milestone produced, so nothing ever asserted that the tree page
survives a failed run or that diagnostics renders for a degraded one. `ALL_PAGES` and
`RUN_SHAPES` are crossed deliberately: a page that 500s on a shape it was not written for
is exactly the kind of gap a representative test cannot see.

**The honesty elements are pinned by their words**, the way `test_api_contract.py` pinned
the API's honesty fields. The tree scope line, the diagnostics verdict banner, the summary
provenance block and the accounting identity each exist because a specific failure was
found live and recorded in `smoke.md`. Presentation may change; what they *say* may not,
and these assertions are what makes that a rule rather than an intention.
"""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.api import routes_runs
from repobridge.main import app
from tests.test_api import REPO_URL, _blob, _dir, _install, _tree_body

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ui_database(isolated_database):
    return isolated_database


@pytest.fixture
def provider(monkeypatch):
    def install(text="A grounded summary of the repository."):
        async def call(prompt: str) -> str:
            return text

        monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
        app.dependency_overrides[routes_runs.get_summary_provider] = lambda: call

    try:
        yield install
    finally:
        app.dependency_overrides.pop(routes_runs.get_summary_provider, None)


def _entries(n=4):
    base = [_dir("src"), _blob("README.md", 40), _blob("assets/logo.png", 4000)]
    return base + [_blob(f"src/file_{i:03d}.py", 40) for i in range(n)]


# --------------------------------------------------------------------------
# the five run shapes
# --------------------------------------------------------------------------


def make_completed(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_entries())))
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]


def make_truncated(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(_entries(), truncated=True)),
    )
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]


def make_partial(install_transport, monkeypatch=None):
    """Capped: more selected files than the run is allowed to read."""
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_entries(8))))
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]


def make_degraded(install_transport):
    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]


def make_failed(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})
    return resp.json()["error"]["details"]["run_id"]


RUN_SHAPES = ["completed", "truncated", "partial", "degraded", "failed"]

ALL_PAGES = ["/runs/{run_id}", "/runs/{run_id}/tree", "/runs/{run_id}/diagnostics"]


@pytest.fixture
def shape(request, install_transport, monkeypatch):
    """Build one of the five run shapes by name."""
    name = request.param
    if name == "partial":
        monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    builder = {
        "completed": make_completed,
        "truncated": make_truncated,
        "partial": make_partial,
        "degraded": make_degraded,
        "failed": make_failed,
    }[name]
    return name, builder(install_transport)


# --------------------------------------------------------------------------
# every page renders for every run shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize("shape", RUN_SHAPES, indirect=True)
@pytest.mark.parametrize("page", ALL_PAGES)
def test_every_page_renders_for_every_run_shape(shape, page, provider):
    provider()
    name, run_id = shape
    resp = client.get(page.format(run_id=run_id))
    assert resp.status_code == 200, f"{page} on a {name} run: {resp.status_code}"
    assert resp.headers["content-type"].startswith("text/html")
    assert "<main" in resp.text and "</html>" in resp.text


@pytest.mark.parametrize("shape", RUN_SHAPES, indirect=True)
def test_the_home_page_renders_with_every_run_shape_in_the_list(shape, provider):
    provider()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Recent runs" in resp.text


def test_the_home_page_renders_with_no_runs_at_all():
    """The empty state `plan.md` asks for."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No runs yet" in resp.text


# --------------------------------------------------------------------------
# navigation: the four views are one set
# --------------------------------------------------------------------------


def _links(html: str) -> set[str]:
    return set(re.findall(r'href="([^"]+)"', html))


@pytest.mark.parametrize("page", ALL_PAGES)
def test_every_run_page_reaches_every_sibling_view(page, install_transport, provider):
    """
    The gap this closes: the tree page linked only back to the run detail page, so from a
    37,393-entry listing there was no way to that run's diagnostics without editing a URL.
    """
    provider()
    run_id = make_completed(install_transport)
    html = client.get(page.format(run_id=run_id)).text
    links = _links(html)

    assert "/" in links, "every run page must link home"
    for sibling in (f"/runs/{run_id}", f"/runs/{run_id}/tree", f"/runs/{run_id}/diagnostics"):
        if sibling == page.format(run_id=run_id):
            continue  # the current page is marked, not linked
        assert sibling in links, f"{page} does not link to {sibling}"


@pytest.mark.parametrize("page", ALL_PAGES)
def test_the_current_view_is_marked_rather_than_linked(page, install_transport, provider):
    """`aria-current` marks it, so the active view is not conveyed by weight alone."""
    provider()
    run_id = make_completed(install_transport)
    html = client.get(page.format(run_id=run_id)).text
    assert 'aria-current="page"' in html


@pytest.mark.parametrize("shape", RUN_SHAPES, indirect=True)
@pytest.mark.parametrize("page", ALL_PAGES)
def test_every_navigation_link_on_every_page_resolves(shape, page, provider):
    """No broken navigation — `evals.md`'s named failure signal, checked by following."""
    provider()
    name, run_id = shape
    html = client.get(page.format(run_id=run_id)).text

    for href in sorted(_links(html)):
        if href.startswith(("http://", "https://", "#", "mailto:")):
            continue
        resp = client.get(href)
        assert resp.status_code == 200, f"{page} ({name}) links to {href} -> {resp.status_code}"


def test_recent_runs_link_to_more_than_the_detail_page(install_transport, provider):
    provider()
    run_id = make_completed(install_transport)
    links = _links(client.get("/").text)

    assert f"/runs/{run_id}" in links
    assert f"/runs/{run_id}/tree" in links, "the runs list must reach the file listing"
    assert f"/runs/{run_id}/diagnostics" in links, "the runs list must reach diagnostics"


# --------------------------------------------------------------------------
# the home-page filters, and the honesty rule about totals
# --------------------------------------------------------------------------


def _make_mixed(install_transport):
    completed = make_completed(install_transport)
    failed = make_failed(install_transport)
    return completed, failed


def test_the_scope_line_names_both_counts_when_filtered(install_transport):
    completed, failed = _make_mixed(install_transport)
    html = client.get("/", params={"status": "failed"}).text

    assert "Showing <strong>1</strong> of <strong>1</strong>" in html
    assert "matching run" in html
    # the honesty rule: the whole is named alongside the match
    assert "of 2 stored" in html


def test_an_unfiltered_list_does_not_claim_to_be_filtered(install_transport):
    _make_mixed(install_transport)
    html = client.get("/").text
    assert "stored run" in html
    assert "matching run" not in html


def test_status_filter_selects(install_transport):
    completed, failed = _make_mixed(install_transport)
    html = client.get("/", params={"status": "completed"}).text
    assert f"/runs/{completed}" in html
    assert f"/runs/{failed}" not in html


def test_owner_filter_is_case_insensitive(install_transport):
    make_completed(install_transport)
    assert "octo" in client.get("/", params={"owner": "OCTO"}).text.lower()
    empty = client.get("/", params={"owner": "nobody"}).text
    assert "No runs match these filters" in empty


def test_date_filters_bound_the_list(install_transport):
    _make_mixed(install_transport)
    future = client.get("/", params={"since": "2099-01-01"}).text
    assert "No runs match these filters" in future
    # and the empty result still names the whole
    assert "2 runs stored in total" in future


def test_an_empty_filtered_list_never_reads_as_an_empty_database(install_transport):
    _make_mixed(install_transport)
    filtered = client.get("/", params={"owner": "nobody"}).text
    assert "No runs yet" not in filtered, "an empty filter must not read as no data"
    assert "show all" in filtered


def test_a_malformed_date_does_not_break_the_page(install_transport):
    """
    The API answers a bad date with a 400. A page must not: a person who mistyped a date
    wants the list plus a note, not an error document.
    """
    _make_mixed(install_transport)
    resp = client.get("/", params={"since": "last tuesday"})
    assert resp.status_code == 200
    assert "Ignored an unreadable date" in resp.text
    assert "Recent runs" in resp.text


def test_filters_are_reflected_back_in_the_form(install_transport):
    _make_mixed(install_transport)
    html = client.get("/", params={"status": "failed", "owner": "octo"}).text
    assert 'value="failed" selected' in html
    assert 'value="octo"' in html
    assert "clear" in html


# --------------------------------------------------------------------------
# state legible at a glance
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape,expected",
    [("completed", "completed"), ("degraded", "degraded"), ("failed", "failed")],
    indirect=["shape"],
)
def test_the_run_status_is_stated_in_words_not_only_in_colour(shape, expected, provider):
    provider()
    name, run_id = shape
    for page in ALL_PAGES:
        html = client.get(page.format(run_id=run_id)).text
        assert f">{expected}</span>" in html, f"{page} does not name the status in text"


def test_a_truncated_run_is_flagged_everywhere_it_appears(install_transport, provider):
    provider()
    run_id = make_truncated(install_transport)
    assert "truncated" in client.get("/").text
    for page in ALL_PAGES:
        assert "truncated" in client.get(page.format(run_id=run_id)).text.lower()


def test_a_capped_run_is_flagged_in_the_runs_list(install_transport, provider, monkeypatch):
    """
    The gap this closes: a run that read 2 of 8 files looked identical in the list to one
    that read everything. `status` is `completed` for both.
    """
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    make_partial(install_transport)
    html = client.get("/").text
    assert "capped" in html
    assert "completed" in html, "the status is still stated; the flag adds to it"


def test_a_clean_complete_run_carries_no_flags(install_transport, provider):
    """Absence is the signal; a row of green 'all fine' badges would be noise."""
    provider()
    make_completed(install_transport)
    html = client.get("/").text
    for flag in (">truncated<", ">capped<", ">read errors<", ">no summary<"):
        assert flag not in html


def test_a_run_without_a_summary_says_so_in_the_list(install_transport):
    make_completed(install_transport)  # no provider configured
    assert "no summary" in client.get("/").text


# --------------------------------------------------------------------------
# accessibility
# --------------------------------------------------------------------------


def test_the_home_page_ships_no_prewritten_error_prose():
    """
    The Milestone 4 debt. The error box used to ship on every render carrying the words
    "Analysis failed." and "The attempt was still recorded", kept out of sight with
    `hidden`. It now ships empty and the script fills it.
    """
    html = client.get("/").text
    assert "Analysis failed." not in html
    assert "The attempt was still recorded" not in html
    assert 'id="analyze-error"' in html, "the container still exists, it is just empty"


def test_the_error_region_is_announced_when_it_appears():
    """An empty container is not enough: it has to be live, or it appears silently."""
    html = client.get("/").text
    box = re.search(r'<div id="analyze-error"[^>]*>', html).group(0)
    assert 'role="alert"' in box
    assert 'tabindex="-1"' in box, "it is focused when shown, so keyboard users land on it"


def test_every_form_control_has_a_label():
    html = client.get("/").text
    ids = re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', html)
    labelled = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    assert ids, "the page has form controls"
    for control_id in ids:
        assert control_id in labelled, f"control '{control_id}' has no label"


def test_the_progress_region_is_polite_and_the_clock_is_not_announced():
    html = client.get("/").text
    assert 'id="analyze-status"' in html and 'aria-live="polite"' in html
    elapsed = re.search(r'<span id="analyze-elapsed"[^>]*>', html).group(0)
    assert 'aria-hidden="true"' in elapsed, "a clock read aloud every second is noise"


def test_there_is_a_skip_link_and_a_main_landmark():
    html = client.get("/").text
    assert 'class="skip-link"' in html
    assert '<main id="main"' in html


def test_the_wordmark_links_home(install_transport, provider):
    provider()
    run_id = make_completed(install_transport)
    for page in ALL_PAGES:
        html = client.get(page.format(run_id=run_id)).text
        assert '<h1><a href="/">RepoBridge</a></h1>' in html


def test_table_rows_repeating_a_link_label_distinguish_them_for_screen_readers(
    install_transport, provider
):
    """Two columns of "files" and "diagnostics" links need more than their visible text."""
    provider()
    make_completed(install_transport)
    html = client.get("/").text
    assert 'class="sr-only"> for octo/demo</span>' in html


# --------------------------------------------------------------------------
# the honesty elements: present, and still saying what they said
# --------------------------------------------------------------------------


def test_the_tree_scope_line_survives_unchanged(install_transport, provider):
    """`smoke.md` Run 5: a page of 100 of 37,393 entries must never read as the whole."""
    provider()
    run_id = make_completed(install_transport)
    html = client.get(f"/runs/{run_id}/tree").text

    assert "Showing <strong>1&ndash;" in html
    assert "entries" in html
    # and with a filter, both numbers
    filtered = client.get(f"/runs/{run_id}/tree", params={"status": "skipped"}).text
    assert "matching entries (of" in filtered
    assert "in this run)" in filtered


def test_the_truncation_warning_on_the_tree_page_survives_unchanged(
    install_transport, provider
):
    provider()
    run_id = make_truncated(install_transport)
    html = client.get(f"/runs/{run_id}/tree").text
    assert "GitHub truncated this tree" in html
    assert "the repository contains" in html


def test_the_accounting_identity_survives_unchanged(install_transport, provider):
    """`smoke.md` Run 4: every entry accounted for, shown as the sum it is."""
    provider()
    run_id = make_completed(install_transport)
    html = client.get(f"/runs/{run_id}").text
    assert "Every entry GitHub returned is accounted for" in html
    assert "directories +" in html and "selected" in html and "= " in html


def test_the_summary_provenance_block_survives_unchanged(install_transport, provider):
    """`smoke.md` Run 7/8: the prose is only trustworthy beside what it was built from."""
    provider()
    run_id = make_completed(install_transport)
    html = client.get(f"/runs/{run_id}").text

    assert "What this summary is based on:" in html
    assert "selected files were read" in html
    assert "Claims in the prose should be checkable against the file inventory below." in html


def test_the_partial_coverage_notice_survives_unchanged(
    install_transport, provider, monkeypatch
):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    run_id = make_partial(install_transport)
    html = client.get(f"/runs/{run_id}").text
    assert "This summary is based on partial coverage." in html


def test_the_diagnostics_banner_survives_unchanged(install_transport, provider):
    """`smoke.md` Run 10: the verdict a reader actually reads. All four branches."""
    provider()

    # clean: nothing skipped, nothing capped, a summary generated
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body([_blob("README.md", 40)])))
    clean = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]
    assert "This run is complete." in client.get(f"/runs/{clean}/diagnostics").text

    # partial only: entries skipped, nothing failed
    partial = make_completed(install_transport)   # carries a skipped .png
    assert "This run is partial." in client.get(f"/runs/{partial}/diagnostics").text

    # failed: the run ended
    assert "This run failed." in client.get(
        f"/runs/{make_failed(install_transport)}/diagnostics"
    ).text

    # partial *and* degraded: both stated, the Milestone 7 combined-banner fix
    no_key = make_completed(install_transport)
    app.dependency_overrides.pop(routes_runs.get_summary_provider, None)
    both = client.get(f"/runs/{no_key}/diagnostics").text
    assert "completed with failures" in both or "This run is partial." in both


def test_the_diagnostics_event_count_line_survives_the_variable_rename(
    install_transport, provider
):
    """
    The template context key changed from `total_events` to `total` to match the API's
    pagination envelope. The rendered sentence must be identical, character for character.
    """
    provider()
    run_id = make_completed(install_transport)
    html = client.get(f"/runs/{run_id}/diagnostics").text
    assert re.search(r"\d+ events, in the order the pipeline produced them\.", html)

    filtered = client.get(f"/runs/{run_id}/diagnostics", params={"level": "info"}).text
    assert re.search(r"Showing \d+ of \d+ events", filtered)
    assert "The counts above always describe the whole run, never the filtered view." in filtered


def test_the_extracted_content_scope_line_survives_unchanged(
    install_transport, provider, monkeypatch
):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    run_id = make_partial(install_transport)
    html = client.get(f"/runs/{run_id}").text
    assert "selected files were read, producing" in html
    assert "were not read: this run reads at most" in html


def test_the_chunk_sample_still_says_it_is_a_sample(install_transport, provider):
    provider()
    run_id = make_completed(install_transport)
    html = client.get(f"/runs/{run_id}").text
    assert "chunk" in html and "ordered by source path" in html
    assert "Every chunk records where it came from and where in that file." in html


def test_a_failed_run_says_which_kind_of_failure_it_was(install_transport):
    """
    Found in the Milestone 9 walkthrough, not by a test.

    Milestone 7 made a bad ref store a failed run carrying the metadata that *did*
    succeed. The failure notice still read "The repository never resolved" for both kinds,
    which is false for that one -- and the Repository table below it printed
    `Default branch: master`, so the page contradicted itself on screen.
    """
    # repository never resolved
    missing = make_failed(install_transport)
    html = client.get(f"/runs/{missing}").text
    assert "The repository never resolved" in html

    # repository resolved, ref did not
    _install(install_transport, lambda ref: httpx.Response(404, json={"message": "Not Found"}))
    resp = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "no-such-branch"}
    )
    bad_ref = resp.json()["error"]["details"]["run_id"]
    html = client.get(f"/runs/{bad_ref}").text

    assert "The repository resolved, but the ref that was" in html
    assert "The repository never resolved" not in html, "the page must not contradict itself"
    # the thing that made it a contradiction is still on the page
    assert "Default branch" in html and "main" in html


def test_the_repository_name_is_not_printed_three_times_on_the_detail_page(
    install_transport, provider
):
    provider()
    run_id = make_completed(install_transport)
    html = client.get(f"/runs/{run_id}").text
    assert 'class="run-nav-repo' not in html

    # but the sibling pages, whose headings are "Files" and "Diagnostics", still say it
    for page in (f"/runs/{run_id}/tree", f"/runs/{run_id}/diagnostics"):
        assert 'class="run-nav-repo' in client.get(page).text
