from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.core.input import (
    normalize_github_repo_url,
    RepoURLValidationError,
)
from repobridge.config import (
    get_deployment_config,
    get_extraction_config,
    get_summarization_config,
)
from repobridge.core.limits import client_key, get_limiter
from repobridge.core.models import AnalyzeRequest
from repobridge.core.extraction import ExtractionResult, fetch_and_extract
from repobridge.core.github_client import (
    fetch_file_content,
    open_client,
    fetch_repo_metadata,
    fetch_repo_tree,
    GitHubClientError,
)
from repobridge.api.errors import api_error, invalid_value, run_not_found
from repobridge.core.diagnostics import Level, Recorder, Stage, rate_limit_details
from repobridge.core.selection import ClassificationResult, classify_tree
from repobridge.core.summarization import ChunkRef, SummaryResult, summarise
from repobridge.infra import storage
from repobridge.infra.db import get_session
from repobridge.infra.schemas import RunStatus

router = APIRouter(prefix="/api", tags=["runs"])


#: Keys for the two request-rate windows. `instance` is deliberately a constant: it is
#: one bucket for the whole process, which is what "the operator's quota" means.
INSTANCE_KEY = "instance"


def _limit_refusal(verdict, *, code: str, what: str):
    """
    One refusal, worded the way every other limit in this project is worded.

    Which limit, what it is, how much of it is used, and when it lifts -- as prose *and*
    as fields, so the UI can print a sentence and a script can read numbers. A limiter
    that answered "429, too many requests" would be the only limit here that does not say
    when it resets.
    """
    return api_error(
        429,
        code,
        f"{what} This shared instance allows {verdict.limit} "
        f"analys{'is' if verdict.limit == 1 else 'es'} per hour"
        f"{' per visitor' if code == 'client_limit_reached' else ''}, and "
        f"{verdict.used} ha{'s' if verdict.used == 1 else 've'} been used. "
        f"The limit lifts {verdict.retry_after_human}.",
        limit=verdict.limit,
        used=verdict.used,
        window="1 hour",
        retry_after_seconds=verdict.retry_after_seconds,
        scope=verdict.scope,
    )


def _check_request_limits(request_obj: Request | None, deployment):
    """
    The two rate windows, checked before anything is spent.

    Checked, not consumed: an analysis that fails validation should not cost a visitor
    part of their allowance. `record` happens once the run is under way.
    """
    limiter = get_limiter()
    who = client_key(
        request_obj.headers.get("x-forwarded-for") if request_obj else None,
        request_obj.client.host if request_obj and request_obj.client else None,
    )

    verdict = limiter.check(
        INSTANCE_KEY, deployment.max_analyses_per_hour, scope="instance"
    )
    if not verdict.allowed:
        raise _limit_refusal(
            verdict,
            code="instance_limit_reached",
            what="This instance has reached its hourly analysis limit.",
        )

    verdict = limiter.check(
        f"client:{who}", deployment.max_analyses_per_hour_per_client, scope="client"
    )
    if not verdict.allowed:
        raise _limit_refusal(
            verdict,
            code="client_limit_reached",
            what="You have reached your hourly analysis limit.",
        )
    return who


def _status_for(error: GitHubClientError) -> int:
    """
    Map a GitHub failure onto the status *this* API should return.

    GitHub's status code is not automatically ours: an upstream 500 does not mean
    RepoBridge failed, and a rate limit is not "you are forbidden".
    """
    if error.is_rate_limit:
        return 429
    if error.status_code is None:
        # Never reached GitHub at all (network error, DNS, timeout).
        return 502
    if error.status_code >= 500:
        # Upstream is broken; we are the gateway.
        return 502
    # Genuine client-side answers from GitHub (404, and 401/403 that are real auth
    # failures) are meaningful as-is.
    return error.status_code

# How many tree entries to echo back inline. The full tree is not returned in
# v0.1; this is a preview so callers can sanity-check what was retrieved.
TREE_PREVIEW_LIMIT = 50

# How many classified files to sample per status. Classification runs over the whole
# tree, but the response carries aggregates plus a sample: kubernetes/kubernetes has
# 37,393 entries and nobody wants those inline.
CLASSIFICATION_SAMPLE_LIMIT = 50

#: A summarisation provider: given a prompt, return the generated text.
SummaryProvider = Callable[[str], Awaitable[str]]


def get_summary_provider() -> SummaryProvider | None:
    """
    The summarisation provider for this request.

    Production returns None, which leaves `summarise()` to call its configured Gemini
    endpoint. It exists as a dependency, rather than as a module-level variable a test
    reassigns, so the seam is part of the route's declared interface: a test overrides
    it with `app.dependency_overrides[get_summary_provider]`, scoped to the app and
    undone by clearing the mapping, with no mutable global left in production code.
    """
    return None


def _extraction_payload(result: ExtractionResult | None) -> dict | None:
    """
    Aggregates plus a capped sample, same contract as `_classification_payload`.

    `read_of_selected` is the honesty field: a capped run must say "read 200 of 11,215"
    as plainly as the tree page says "showing 100 of 37,393".
    """
    if result is None:
        return None
    return {
        "selected_total": result.selected_total,
        "files_read": len(result.read),
        "files_failed": len(result.failed),
        "files_not_fetched": len(result.not_fetched),
        "read_cap": result.cap,
        "cap_applied": result.cap_applied,
        "read_of_selected": f"read {len(result.read)} of {result.selected_total} selected files",
        "accounts_for_every_selected_file": result.accounts_for_every_selected_file(),
        "chunk_count": len(result.chunks),
        "sample_limit": CLASSIFICATION_SAMPLE_LIMIT,
        "failed_sample": [
            {"path": f.path, "error": f.error}
            for f in result.failed[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
        "not_fetched_sample": [
            {"path": f.path, "error": f.error}
            for f in result.not_fetched[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
    }


def _summary_payload(result: SummaryResult) -> dict:
    """
    The prose plus the provenance that makes it checkable.

    `provenance` is always present, including on NO_CONTENT and PROVIDER_ERROR: a reader
    should be able to see what *would* have been summarised even when nothing was.
    """
    return {
        "status": result.status.value,
        "text": result.text,
        "model": result.model,
        "error": result.error,
        "prompt_tokens_estimated": result.prompt_tokens_estimated,
        "provenance": result.provenance,
    }


def _classification_payload(result: ClassificationResult) -> dict:
    """
    Aggregate counts plus a capped sample.

    Field names say which is which: `*_count` covers every entry, `*_sample` is capped
    at CLASSIFICATION_SAMPLE_LIMIT. The counts, not the samples, are the source of truth.
    """
    return {
        "total_entries": result.total_entries,
        "directories": result.directories,
        "selected_count": len(result.selected),
        "skipped_count": len(result.skipped),
        "failed_count": len(result.failed),
        "skipped_count_by_reason": result.counts_by_reason(),
        "accounts_for_every_entry": result.accounts_for_every_entry(),
        "sample_limit": CLASSIFICATION_SAMPLE_LIMIT,
        "selected_sample": [
            {"path": f.path, "extension": f.extension, "size": f.size}
            for f in result.selected[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
        "skipped_sample": [
            {
                "path": f.path,
                "reason": f.reason.value if f.reason else None,
                "message": f.message,
            }
            for f in result.skipped[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
        "failed_sample": [
            {"path": f.path, "message": f.message}
            for f in result.failed[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
    }


@router.post("/analyze", response_class=JSONResponse)
async def analyze_repo(
    request: AnalyzeRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    provider: SummaryProvider | None = Depends(get_summary_provider),
):
    """
    Validate the incoming GitHub repo URL, normalize owner/repo, then fetch repository
    metadata and the git tree for the resolved ref.

    v0.1: retrieval, classification, content extraction, persistence and summarisation.
    The run is stored and its id returned as `run_id`.

    Summarisation runs last and cannot fail the request: a provider error, an exhausted
    quota or a missing key is recorded on the run, which stays `completed`. The summary
    can be generated afterwards from stored content via
    `POST /api/runs/{run_id}/summarize`, with no re-fetching.

    Reading is capped at `ExtractionConfig.max_files_per_run`; selected files beyond the
    cap are recorded as `not_fetched`, never dropped. See the 2026-08-18 amendment in
    spec.md section 7.4 for why per-file reads were chosen over a tarball.

    Error policy for the tree step:
    - An explicit branch_or_ref that GitHub cannot resolve is a caller error -> HTTP 404.
      A caller who asked for a specific branch must never receive a 200 implying it exists.
    - Any other tree failure (rate limit, other GitHub errors) is a degraded run -> HTTP 200
      with metadata intact and `tree_error` explaining what did not come through.

    `resolved_ref` is null unless the tree call actually succeeded against that ref. The ref
    we intended to use is always derivable by the caller as `branch_or_ref` when they supplied
    one, else `metadata.default_branch`, so no separate "attempted" field is reported.
    """
    # Diagnostics buffer for this run. Events are stamped with the run id at step 6,
    # because the id does not exist until then -- see core/diagnostics.Recorder.
    events = Recorder()

    # Step 0: spend control. Off entirely unless this instance is configured with limits,
    # so local use is unchanged. Before validation would charge a visitor for a typo;
    # after the GitHub calls would be too late to protect the quota. Here is the point
    # where nothing has been spent and the request is worth counting.
    deployment = get_deployment_config()
    who = _check_request_limits(http_request, deployment)

    # Step 1: validate and normalize URL
    try:
        normalized = normalize_github_repo_url(str(request.repo_url))
    except RepoURLValidationError as e:
        # Deliberately not persisted: nothing reached GitHub and there is no run to attach
        # events to. storage.create_failed_run documents the same boundary.
        events.error(Stage.VALIDATION, e.message, repo_url=str(request.repo_url))
        raise api_error(400, "invalid_repo_url", e.message, repo_url=str(request.repo_url))

    # The URL is real, so this attempt counts against the allowance.
    get_limiter().record(INSTANCE_KEY)
    get_limiter().record(f"client:{who}")

    events.info(
        Stage.VALIDATION,
        f"Repository URL accepted as {normalized.owner}/{normalized.name}.",
        owner=normalized.owner,
        name=normalized.name,
        requested_ref=request.branch_or_ref,
    )

    # Step 2: fetch basic metadata from GitHub
    try:
        metadata = await fetch_repo_metadata(normalized)
    except GitHubClientError as e:
        if e.is_rate_limit:
            # The moved Milestone 2 criterion: a rate limit must be visible here, with
            # which quota and when it resets, from the failing response's own headers.
            events.error(
                Stage.METADATA,
                e.message,
                reason="rate_limit",
                **rate_limit_details(e),
            )
        else:
            events.error(
                Stage.METADATA,
                e.message,
                reason="not_found" if e.status_code == 404 else "github_error",
                status_code=e.status_code,
            )
        # Record the attempt before failing the request. A repo that never resolved is
        # otherwise the one outcome that leaves no trace, and it is exactly what a user
        # comes back to ask about.
        failed_run_id = await storage.create_failed_run(
            session,
            repo_url=str(request.repo_url),
            owner=normalized.owner,
            name=normalized.name,
            branch_or_ref=request.branch_or_ref,
            error=e.message,
        )
        events.info(
            Stage.PERSISTENCE,
            "The failed run was stored so the attempt leaves a trace.",
            run_status="failed",
        )
        events.flush_suppressed()
        await storage.persist_events(session, failed_run_id, events)

        # the run_id travels with the error so a caller can open the failed run: it is
        # still a run, and it is the record of what went wrong
        raise api_error(
            _status_for(e),
            "rate_limited" if e.is_rate_limit
            else "repo_not_found" if e.status_code == 404
            else "github_error",
            e.message,
            run_id=failed_run_id,
            github_status=e.status_code,
        )

    events.info(
        Stage.METADATA,
        f"Repository metadata retrieved for {metadata.get('full_name') or normalized.owner}.",
        default_branch=metadata.get("default_branch"),
        language=metadata.get("language"),
        archived=metadata.get("archived"),
        fork=metadata.get("fork"),
    )

    # Step 3: decide which ref to ask GitHub for.
    # Explicit request wins; otherwise fall back to the repo's default branch.
    # This is what we *attempt*; it is not reported as resolved until GitHub confirms it.
    requested_ref = request.branch_or_ref
    attempted_ref = requested_ref or metadata.get("default_branch") or "HEAD"

    # Step 4: fetch the tree for that ref
    resolved_ref: str | None = None
    tree_preview: list[dict] = []
    tree_entry_count = 0
    tree_truncated = False
    tree_error: str | None = None
    # None, not an empty summary: if the tree never arrived there is nothing to
    # classify, and zero counts would read as "we looked and found nothing".
    classification: dict | None = None
    classification_result: ClassificationResult | None = None

    try:
        tree = await fetch_repo_tree(normalized, attempted_ref)
    except GitHubClientError as e:
        if e.is_rate_limit:
            events.degraded(
                Stage.TREE, e.message, reason="rate_limit", **rate_limit_details(e)
            )
        elif requested_ref and e.status_code == 404:
            events.error(
                Stage.TREE,
                f"Branch or ref '{requested_ref}' was not found.",
                reason="ref_not_found",
                requested_ref=requested_ref,
                status_code=404,
            )
        else:
            events.degraded(
                Stage.TREE, e.message, reason="github_error", status_code=e.status_code
            )

        if requested_ref and e.status_code == 404:
            # The caller named a ref that does not exist. Do not pretend this succeeded.
            #
            # Store the attempt, exactly as the metadata-404 path above does and for the
            # same reason: this is a run that failed, and a failure that leaves no trace
            # is the one thing this tool exists not to do. The metadata *did* succeed
            # here, so it is stored too -- "the repository is real, the ref was not" is
            # more useful than a bare failure, and it is what the timeline can then say.
            ref_message = (
                f"Branch or ref '{requested_ref}' was not found in "
                f"{normalized.owner}/{normalized.name}."
            )
            failed_run_id = await storage.create_failed_run(
                session,
                repo_url=str(request.repo_url),
                owner=normalized.owner,
                name=normalized.name,
                branch_or_ref=request.branch_or_ref,
                error=ref_message,
                metadata=metadata,
            )
            events.info(
                Stage.PERSISTENCE,
                "The failed run was stored so the attempt leaves a trace.",
                run_status="failed",
                requested_ref=requested_ref,
            )
            events.flush_suppressed()
            await storage.persist_events(session, failed_run_id, events)
            # the run_id travels with the error so a caller can open the failed run,
            # as it does for a metadata failure
            raise api_error(
                404, "ref_not_found", ref_message,
                run_id=failed_run_id, requested_ref=requested_ref,
            )
        # Metadata succeeded, so report the run as degraded rather than failed.
        # resolved_ref stays None: we never confirmed the ref exists, and the response
        # must not assert a resolution that did not happen.
        tree_error = f"Tree retrieval failed: {e.message}"
        events.degraded(
            Stage.CLASSIFICATION,
            "Skipped: no tree arrived, so there is nothing to classify.",
            reason="no_tree",
        )
    else:
        # GitHub answered for this ref, so it is now genuinely resolved.
        resolved_ref = attempted_ref
        entries = tree.get("tree") or []
        # Deliberately not called a "total": when GitHub truncates, this is only
        # what the API chose to return.
        tree_entry_count = len(entries)

        # Spend control, part two: how large a repository this instance will accept.
        #
        # Checked here because here is the first moment the size is known, and it is
        # still cheap: two GitHub calls spent, none of the up-to-200 content reads. A
        # 37,393-entry repository costs a refusal rather than the whole read budget.
        # The refusal names the repository's size and the instance's ceiling, so it
        # reads as a policy rather than as a malfunction.
        if deployment.max_repo_entries and tree_entry_count > deployment.max_repo_entries:
            events.error(
                Stage.TREE,
                f"Repository is larger than this instance accepts: {tree_entry_count} "
                f"entries against a limit of {deployment.max_repo_entries}.",
                reason="repo_too_large",
                entries=tree_entry_count,
                limit=deployment.max_repo_entries,
            )
            size_message = (
                f"{normalized.owner}/{normalized.name} has {tree_entry_count:,} tree "
                f"entries. This shared instance accepts repositories up to "
                f"{deployment.max_repo_entries:,} entries, so that reading them cannot "
                "exhaust the operator's GitHub quota. Try a smaller repository."
            )
            # This refusal reached GitHub -- two calls, both successful -- so it leaves a
            # stored trace like every other failure that got that far (CONTRACT I-7). It
            # previously stored nothing, which made this instance's own spend-control
            # policy the one thing a diagnostics tool could not show you.
            #
            # `resolved_ref` and the entry count are both carried through: GitHub answered
            # for this ref and told us exactly how big the repository is. Discarding that
            # would understate what the attempt actually established.
            failed_run_id = await storage.create_failed_run(
                session,
                repo_url=str(request.repo_url),
                owner=normalized.owner,
                name=normalized.name,
                branch_or_ref=request.branch_or_ref,
                error=size_message,
                metadata=metadata,
                resolved_ref=attempted_ref,
                tree_entry_count=tree_entry_count,
            )
            events.info(
                Stage.PERSISTENCE,
                "The refused run was stored so the attempt leaves a trace.",
                run_status="failed",
                reason="repo_too_large",
            )
            events.flush_suppressed()
            await storage.persist_events(session, failed_run_id, events)
            # the run_id travels with the error so a caller can open the refused run, as
            # it does for a metadata failure and for a bad ref
            raise api_error(
                413,
                "repo_too_large",
                size_message,
                run_id=failed_run_id,
                entries=tree_entry_count,
                limit=deployment.max_repo_entries,
                repo=f"{normalized.owner}/{normalized.name}",
            )
        tree_truncated = bool(tree.get("truncated", False))
        tree_preview = [
            {
                "path": entry.get("path"),
                "type": entry.get("type"),
                "size": entry.get("size"),
                "mode": entry.get("mode"),
            }
            for entry in entries[:TREE_PREVIEW_LIMIT]
        ]
        events.info(
            Stage.TREE,
            f"Tree retrieved for ref '{attempted_ref}': {tree_entry_count} entries.",
            resolved_ref=attempted_ref,
            entries=tree_entry_count,
        )

        # Classify every entry GitHub returned, not just the previewed ones.
        classification_result = classify_tree(entries)
        classification = _classification_payload(classification_result)

        # Aggregate, not one event per entry: kubernetes/kubernetes skips 22,924 files and
        # every one of them is already stored with its reason on analysis_files. See the
        # volume rules in core/diagnostics.py.
        events.info(
            Stage.CLASSIFICATION,
            f"Classified {classification_result.total_entries} entries: "
            f"{len(classification_result.selected)} selected, "
            f"{len(classification_result.skipped)} skipped, "
            f"{classification_result.directories} directories.",
            selected=len(classification_result.selected),
            skipped=len(classification_result.skipped),
            failed=len(classification_result.failed),
            directories=classification_result.directories,
            accounts_for_every_entry=classification_result.accounts_for_every_entry(),
        )
        if classification_result.skipped:
            events.partial(
                Stage.CLASSIFICATION,
                f"{len(classification_result.skipped)} entries were skipped without "
                "reading. Every one is listed with its reason in the file view.",
                **{
                    f"skipped_{reason}": count
                    for reason, count in classification_result.counts_by_reason().items()
                },
            )

        if tree_truncated:
            # Truncation must never be discoverable only by noticing a boolean.
            tree_error = (
                "GitHub truncated the tree response for this repository, so the file "
                f"listing is incomplete. {tree_entry_count} entries were returned; the "
                "repository contains more. Classification below covers only those."
            )
            events.partial(
                Stage.TREE,
                "GitHub truncated the tree, so files exist in this repository that "
                "RepoBridge never saw and cannot account for.",
                entries_returned=tree_entry_count,
                truncated=True,
            )

    # Step 5: read and extract the selected files, capped. Runs only when a tree
    # arrived; a degraded run has nothing selected to read.
    extraction: ExtractionResult | None = None
    if classification_result is not None and classification_result.selected:
        extraction_cfg = get_extraction_config()

        # One client for the whole run: a client per file means a TCP+TLS handshake per
        # file, which dominated the read time before pooling.
        async with open_client(
            extraction_cfg.content_timeout,
            max_connections=extraction_cfg.max_concurrent_reads,
        ) as client:

            async def _fetch(path: str) -> str:
                return await fetch_file_content(
                    normalized, path, resolved_ref, client=client
                )

            extraction = await fetch_and_extract(
                [f.path for f in classification_result.selected],
                _fetch,
                extraction_cfg,
            )

    if extraction is not None:
        events.info(
            Stage.CONTENT,
            f"Read {len(extraction.read)} of {extraction.selected_total} selected files.",
            files_read=len(extraction.read),
            selected=extraction.selected_total,
            read_cap=extraction.cap,
            concurrency=extraction_cfg.max_concurrent_reads,
            accounts_for_every_selected_file=extraction.accounts_for_every_selected_file(),
        )
        if extraction.not_fetched:
            events.partial(
                Stage.CONTENT,
                f"{len(extraction.not_fetched)} selected file(s) were not read: this run "
                f"reads at most {extraction.cap}. The files read are a rank-ordered "
                "sample, not the first N in tree order.",
                not_fetched=len(extraction.not_fetched),
                read_cap=extraction.cap,
            )
        # One event per FAILED file, capped. Never one per file that worked.
        #
        # Split by which stage actually failed: a file that never arrived is a content
        # failure, a file that arrived and would not parse is an extraction failure.
        # Reporting a malformed notebook as `read_failed` names the wrong stage and sends
        # a reader looking at the network when the network was fine.
        for failure in extraction.read_failures:
            events.file_failure(
                Stage.CONTENT, failure.path, failure.error or "Could not read file.",
                reason="read_failed",
            )
        if extraction.read_failures:
            events.partial(
                Stage.CONTENT,
                f"{len(extraction.read_failures)} selected file(s) could not be "
                "retrieved. The run continued; per-file failures do not end it.",
                failed=len(extraction.read_failures),
            )
        events.info(
            Stage.EXTRACTION,
            f"Extracted {len(extraction.chunks)} chunks from {len(extraction.read)} files.",
            chunks=len(extraction.chunks),
            files=len(extraction.read),
        )
        for failure in extraction.extraction_failures:
            events.file_failure(
                Stage.EXTRACTION,
                failure.path,
                failure.error or "Could not extract text from file.",
                reason="extraction_failed",
            )
        if extraction.extraction_failures:
            events.partial(
                Stage.EXTRACTION,
                f"{len(extraction.extraction_failures)} file(s) were retrieved but could "
                "not be turned into text, so their content is absent from the summary. "
                "The run continued; per-file failures do not end it.",
                failed=len(extraction.extraction_failures),
                retrieved_but_unparsed=len(extraction.extraction_failures),
            )
    elif classification_result is not None:
        events.info(
            Stage.CONTENT,
            "No file was read: classification selected nothing readable.",
            selected=0,
        )

    # Step 6: persist. A degraded run is stored too, with its error and whatever
    # metadata succeeded -- a run that vanished because it failed would be the worst
    # outcome for a tool whose pitch is that it tells you what went wrong.
    run_id = await storage.create_run(
        session,
        repo_url=str(request.repo_url),
        owner=normalized.owner,
        name=normalized.name,
        branch_or_ref=request.branch_or_ref,
        resolved_ref=resolved_ref,
        metadata=metadata,
        tree_entry_count=tree_entry_count,
        tree_truncated=tree_truncated,
        tree_error=tree_error,
        classification=classification_result,
    )

    if extraction is not None:
        await storage.persist_extraction(session, run_id, extraction)

    events.info(
        Stage.PERSISTENCE,
        f"Run stored with {tree_entry_count} classified entries and "
        f"{len(extraction.chunks) if extraction else 0} chunks.",
        run_id=run_id,
        entries=tree_entry_count,
        chunks=len(extraction.chunks) if extraction else 0,
    )

    # Step 7: summarise, grounded in what was actually read.
    # A run with no chunks never reaches the provider -- see core/summarization.py.
    summary = await summarise(
        repo=f"{normalized.owner}/{normalized.name}",
        metadata={**metadata, "resolved_ref": resolved_ref},
        run_summary={
            "tree_entry_count": tree_entry_count,
            "tree_truncated": tree_truncated,
            "selected_count": len(classification_result.selected) if classification_result else 0,
            "skipped_count": len(classification_result.skipped) if classification_result else 0,
            "files_read": len(extraction.read) if extraction else 0,
            "files_read_failed": len(extraction.failed) if extraction else 0,
            "files_not_fetched": len(extraction.not_fetched) if extraction else 0,
            "read_cap": extraction.cap if extraction else None,
        },
        skipped_by_reason=(
            classification_result.counts_by_reason() if classification_result else {}
        ),
        chunks=[
            ChunkRef(
                source_path=c.source_path,
                chunk_index=c.chunk_index,
                chunk_type=c.chunk_type.value,
                text=c.text,
                token_estimate=c.token_estimate(),
                cell_index=c.cell_index,
            )
            for c in (extraction.chunks if extraction else [])
        ],
        cfg=get_summarization_config(),
        call_provider=provider,
    )
    await storage.persist_summary(session, run_id, summary)
    _record_summary_events(events, summary)

    events.flush_suppressed()
    await storage.persist_events(session, run_id, events)

    # Step 8: build response
    return {
        "run_id": run_id,
        "repo_url": str(request.repo_url),
        "owner": normalized.owner,
        "name": normalized.name,
        "branch_or_ref": request.branch_or_ref,
        "resolved_ref": resolved_ref,
        "tree_preview": tree_preview,
        "tree_entry_count": tree_entry_count,
        "tree_truncated": tree_truncated,
        "tree_error": tree_error,
        "classification": classification,
        "extraction": _extraction_payload(extraction),
        "summary": _summary_payload(summary),
        "metadata": {
            "full_name": metadata.get("full_name"),
            "private": metadata.get("private"),
            "default_branch": metadata.get("default_branch"),
            "description": metadata.get("description"),
            "archived": metadata.get("archived"),
            "fork": metadata.get("fork"),
            "stargazers_count": metadata.get("stargazers_count"),
            "language": metadata.get("language"),
        },
    }

def _record_summary_events(events: Recorder, summary: SummaryResult) -> None:
    """
    Put the summarisation outcome in the timeline, including *why* it stopped.

    The case worth the code: a daily-quota 429 is detected and deliberately not retried,
    because the provider advertises a ~58 s `retryDelay` while the allowance does not
    return until the quota-day boundary. Until now that decision surfaced only inside a
    prose `provider_error` string. Here it is a stage event carrying `retry_decision`,
    `quota_id` and how many attempts were made -- which is the difference between a reader
    concluding "the provider is broken" and "come back tomorrow, or switch model".
    """
    status = summary.status.value
    detail = dict(summary.error_detail or {})

    if status == "ok":
        provenance = summary.provenance or {}
        events.info(
            Stage.SUMMARIZATION,
            f"Summary generated by {summary.model}.",
            model=summary.model,
            prompt_tokens_estimated=summary.prompt_tokens_estimated,
            chunks_included=provenance.get("chunks_included"),
            chunks_total=provenance.get("chunks_total"),
        )
        if provenance.get("chunks_excluded"):
            events.partial(
                Stage.SUMMARIZATION,
                f"{provenance['chunks_excluded']} of {provenance['chunks_total']} chunks "
                "did not fit the token budget and were not sent to the model.",
                chunks_excluded=provenance["chunks_excluded"],
                token_budget=provenance.get("token_budget"),
            )
        if provenance.get("is_partial"):
            events.partial(
                Stage.SUMMARIZATION,
                "This summary is based on partial coverage. "
                + " ".join(provenance.get("limitations", [])),
                is_partial=True,
            )
        return

    if status == "no_content":
        events.degraded(
            Stage.SUMMARIZATION,
            summary.error or "No content was extracted, so there is nothing to summarise.",
            reason="no_content",
        )
        return

    if status == "not_configured":
        events.degraded(
            Stage.SUMMARIZATION,
            summary.error or "No summarisation API key configured.",
            reason="not_configured",
        )
        return

    events.degraded(
        Stage.SUMMARIZATION,
        summary.error or "Summary generation failed.",
        reason=detail.get("kind", "provider_error"),
        **{k: v for k, v in detail.items() if k != "kind"},
    )


def _run_summary(run) -> dict:
    """One run as JSON. Counts come from the stored run row."""
    return {
        "run_id": run.id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "repo_url": run.repo_url,
        "owner": run.owner,
        "name": run.name,
        "branch_or_ref": run.branch_or_ref,
        "resolved_ref": run.resolved_ref,
        "status": run.status,
        # the failure that ended the run, if one did; null on completed and degraded runs
        "error": run.error,
        "metadata": {
            "default_branch": run.default_branch,
            "description": run.description,
            "language": run.language,
            "private": run.private,
            "archived": run.archived,
            "fork": run.fork,
            "stargazers_count": run.stargazers_count,
        },
        "tree_entry_count": run.tree_entry_count,
        "tree_truncated": run.tree_truncated,
        "tree_error": run.tree_error,
        "classification": {
            "total_entries": run.tree_entry_count,
            "directories": run.directories,
            "selected_count": run.selected_count,
            "skipped_count": run.skipped_count,
            "failed_count": run.failed_count,
        },
        "summary": {
            "status": run.summary_status,
            "text": run.summary_text,
            "model": run.summary_model,
            "error": run.summary_error,
            "prompt_tokens_estimated": run.summary_prompt_tokens,
            "provenance": json.loads(run.summary_provenance) if run.summary_provenance else None,
        },
        "extraction": {
            "selected_total": run.selected_count,
            "files_read": run.files_read,
            "files_failed": run.files_read_failed,
            "files_not_fetched": run.files_not_fetched,
            "read_cap": run.read_cap,
            "cap_applied": bool(run.files_not_fetched),
            "chunk_count": run.chunk_count,
            # the honesty line, stored so it reads the same long after the config changed
            "read_of_selected": (
                f"read {run.files_read} of {run.selected_count} selected files"
            ),
        },
    }


RUNS_PAGE_DEFAULT = 20
RUNS_PAGE_MAX = 100


def _parse_when(value: str | None, field: str):
    """
    An ISO 8601 date or datetime, or a 400 naming the field.

    A bare date is read as midnight UTC, so `since=2026-08-18` means "from the start of
    that day" rather than "from whenever this process thinks midnight is". Naive input is
    stamped UTC for the same reason: stored timestamps are UTC, and silently comparing a
    local-clock value against them would filter by an offset the caller never gave.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise api_error(
            400,
            "invalid_value",
            f"'{field}' must be an ISO 8601 date or timestamp, e.g. 2026-08-18 or "
            f"2026-08-18T14:30:00Z. Received '{value}'.",
            field=field,
            value=value,
        )
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.get("/runs", response_class=JSONResponse)
async def list_runs(
    status: str | None = Query(None, description="completed | degraded | failed"),
    owner: str | None = Query(None, description="repository owner, case-insensitive"),
    since: str | None = Query(None, description="ISO 8601 date or timestamp, inclusive"),
    until: str | None = Query(None, description="ISO 8601 date or timestamp, inclusive"),
    limit: int = Query(RUNS_PAGE_DEFAULT, ge=1, le=RUNS_PAGE_MAX),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """
    Recent runs, newest first, filterable.

    The filters are the three a diagnostics or UI consumer actually asks for: *what state
    is it in*, *whose repository was it*, and *when*. Anything narrower is answerable from
    a run's own endpoints once you have its id.

    **`total` counts what matched; `unfiltered_total` counts every stored run.** Both are
    always present, whether or not a filter was given, so a caller can never read a
    filtered count as a whole one — the same rule `/files` and `/chunks` follow with
    `run_entry_count` and `run_chunk_count`.
    """
    valid_statuses = sorted(st.value for st in RunStatus)
    if status is not None and status not in valid_statuses:
        raise invalid_value("status", status, valid_statuses)

    runs, total, unfiltered = await storage.list_runs(
        session,
        status=status,
        owner=owner,
        since=_parse_when(since, "since"),
        until=_parse_when(until, "until"),
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "unfiltered_total": unfiltered,
        "limit": limit,
        "offset": offset,
        "filters": {"status": status, "owner": owner, "since": since, "until": until},
        "items": [_run_summary(r) for r in runs],
    }


def _extraction_identity_holds(
    run, by_status: dict[str, int], by_content_status: dict[str, int]
) -> bool | None:
    """
    `selected == read + failed + not_fetched`, recomputed from stored rows (CONTRACT I-1).

    None, not False, for a run that never classified anything: a degraded run stored no
    entry rows, so the identity is vacuous rather than violated. Same treatment as
    `stored_identity_holds`, for the same reason — reporting False there would make a
    correctly-handled failure look like a data defect.

    **Every** content status is summed, not the three known ones. A status this function
    does not recognise must break the identity loudly; filtering to a known set is how a
    new value that falls through every branch gets certified as consistent.

    A completed run with selected files and no content rows is False, and should be: the
    extraction stage runs whenever anything is selected, so zero rows means it did not
    persist what it read.
    """
    if run.status != RunStatus.COMPLETED.value:
        return None
    return by_status.get("selected", 0) == sum(by_content_status.values())


@router.get("/runs/{run_id}", response_class=JSONResponse)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)):
    """
    One stored run.

    Both halves of the accounting identity (CONTRACT I-1) are recomputed from the rows
    rather than read off the run's denormalised counts, so a drifted count cannot report
    itself as consistent:

    - `stored_identity_holds` — `total_entries == directories + selected + skipped + failed`
    - `stored_extraction_identity_holds` — `selected == read + failed + not_fetched`

    The second one existed only in memory (`ExtractionResult.accounts_for_every_selected_file`)
    until it was wired up here. An in-memory check certifies the object that was just
    built; it says nothing about what reached the database, which is what a later reader
    actually gets.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise run_not_found(run_id)

    summary = _run_summary(run)
    by_status = await storage.reconstruct_counts(session, run_id)
    by_content_status = await storage.content_status_counts(session, run_id)
    stored_total = sum(by_status.values())
    summary["stored_rows"] = {
        "by_status": by_status,
        "by_content_status": by_content_status,
        "total": stored_total,
        "skipped_count_by_reason": await storage.counts_by_reason(session, run_id),
        # a degraded run stored no entries, so the identity is vacuous there
        "stored_identity_holds": (
            stored_total == run.tree_entry_count if run.status == "completed" else None
        ),
        "stored_extraction_identity_holds": _extraction_identity_holds(
            run, by_status, by_content_status
        ),
    }
    return summary


@router.get("/runs/{run_id}/summary", response_class=JSONResponse)
async def get_run_summary(run_id: str, session: AsyncSession = Depends(get_session)):
    """
    The stored summary and the provenance recorded with it.

    Returned together deliberately: the prose is only trustworthy to the extent a reader
    can check it against what was actually read.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise run_not_found(run_id)

    return {
        "run_id": run.id,
        "repo": f"{run.owner}/{run.name}",
        "run_status": run.status,
        "status": run.summary_status,
        "text": run.summary_text,
        "model": run.summary_model,
        "error": run.summary_error,
        "prompt_tokens_estimated": run.summary_prompt_tokens,
        "provenance": json.loads(run.summary_provenance) if run.summary_provenance else None,
    }


async def _summarise_from_storage(
    session: AsyncSession, run, provider: SummaryProvider | None
) -> SummaryResult:
    """
    Summarise a stored run from its stored inventory alone.

    Nothing here touches GitHub or re-reads a file. The chunks are the ones extraction
    already stored, and every provenance input is read back from the run row and the
    entry rows:

    - the counts come from the `analysis_runs` row written when the run was analysed,
    - `skipped_by_reason` is recomputed from `analysis_files`, the same query the
      diagnostics view uses,
    - the chunks come from `analysis_chunks` in their stored order.

    So the grounding contract is identical to the one `/api/analyze` produces: the same
    `build_provenance` inputs go in, and a summary generated an hour later still
    describes the reading that actually happened, not a fresh one.
    """
    chunks = await storage.chunks_for_summary(session, run.id)
    return await summarise(
        repo=f"{run.owner}/{run.name}",
        metadata={
            "description": run.description,
            "language": run.language,
            "resolved_ref": run.resolved_ref,
        },
        run_summary={
            "tree_entry_count": run.tree_entry_count,
            "tree_truncated": run.tree_truncated,
            "selected_count": run.selected_count,
            "skipped_count": run.skipped_count,
            "files_read": run.files_read,
            "files_read_failed": run.files_read_failed,
            "files_not_fetched": run.files_not_fetched,
            "read_cap": run.read_cap,
        },
        skipped_by_reason=await storage.counts_by_reason(session, run.id),
        chunks=chunks,
        cfg=get_summarization_config(),
        call_provider=provider,
    )


@router.post("/runs/{run_id}/summarize", response_class=JSONResponse)
async def resummarise_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    provider: SummaryProvider | None = Depends(get_summary_provider),
):
    """
    Re-generate the summary for a stored run, without re-fetching anything.

    **Why this exists.** Summarisation is the one stage that fails independently of the
    work that fed it. A transient provider 503, or a daily quota that ran out between
    extraction and generation, would otherwise leave a run permanently without a summary
    -- and the only recovery would be re-analysing the repository, spending GitHub calls
    to re-read files RepoBridge already has, on a provider quota measured in hundreds of
    requests per day.

    **What it does not do.** No GitHub call, no file read, no re-classification. The
    stored chunks are the input, and the stored inventory is the provenance. A summary
    produced here describes the reading that happened at analysis time, which is the only
    reading it can honestly describe.

    The result replaces the stored summary. That is the point: the old one was an error
    or an absence. The previous provenance is replaced along with it, so the pair stays
    consistent -- prose and provenance are only meaningful together.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise run_not_found(run_id)

    events = Recorder()
    events.info(
        Stage.SUMMARIZATION,
        "Re-summarising from stored content: no GitHub call, no file re-read.",
        run_id=run_id,
        source="stored chunks",
    )
    summary = await _summarise_from_storage(session, run, provider)
    await storage.persist_summary(session, run_id, summary)
    _record_summary_events(events, summary)
    await storage.persist_events(session, run_id, events)

    return {
        "run_id": run.id,
        "repo": f"{run.owner}/{run.name}",
        "run_status": run.status,
        **_summary_payload(summary),
    }
