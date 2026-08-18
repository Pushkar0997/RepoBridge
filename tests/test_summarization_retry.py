"""
Provider retry policy, and the model the provider is asked for.

**Nothing here touches the network.** Every response is served by httpx.MockTransport and
every wait is a stub, so the schedule is asserted rather than endured. That is not only a
speed choice: the free tier allows a few hundred generate requests per day and diagnostic
probing has already cost this project a whole day's allowance once. Failures are
reproduced here, never against the live API.
"""

from __future__ import annotations

import httpx
import pytest

from repobridge.config import SummarizationConfig, get_summarization_config
from repobridge.core.summarization import (
    RETRYABLE_STATUSES,
    SummarizationError,
    _backoff_delay,
    _daily_quota_id,
    _suggested_delay,
)

# `_call_gemini` is deliberately NOT imported here. The autouse guard in conftest.py
# replaces it with a refuser, and importing the name at module load would capture the
# real function *before* the guard is installed -- so these tests would keep working by
# accident rather than by permission. They ask for it through `real_provider_call`, which
# the `transport` fixture below requests on their behalf.

#: Fast config: the delays are asserted, not waited on, but keeping them small also
#: keeps a stray real sleep from being invisible.
CFG = SummarizationConfig(
    max_attempts=3, retry_initial_delay=1.0, retry_max_delay=16.0, retry_budget_seconds=45.0
)

OK_BODY = {"candidates": [{"content": {"parts": [{"text": "a grounded summary"}]}}]}


def _daily_quota_body(quota_id: str = "GenerateRequestsPerDayPerProjectPerModel-FreeTier") -> dict:
    """
    A real-shaped daily-quota 429.

    The `retryDelay` is the misleading part and is reproduced deliberately: the provider
    advertises ~58 seconds while the allowance does not return until the quota day rolls
    over. Anything that trusts it will retry into the same wall.
    """
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "You exceeded your current quota.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                            "quotaId": quota_id,
                        }
                    ],
                },
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "58s",
                },
            ],
        }
    }


def _per_minute_quota_body() -> dict:
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                        }
                    ],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3s"},
            ],
        }
    }


@pytest.fixture
def transport(monkeypatch, real_provider_call):
    """
    Install a scripted sequence of responses and record what was sent.

    Returns a dict with `requests` (one entry per attempt), `sleeps` (the waits the retry
    loop asked for) and `call` (the real `_call_gemini`, handed over by the opt-in
    fixture), so a test can assert both the number of attempts and the schedule between
    them without ever holding a reference the guard cannot see.
    """
    state: dict = {"requests": [], "sleeps": [], "call": real_provider_call}

    def install(responses):
        queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            state["requests"].append(str(request.url))
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(item, Exception):
                raise item
            return item

        class _Mocked(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr("repobridge.core.summarization.httpx.AsyncClient", _Mocked)
        return state

    return install


async def _call(state: dict, cfg: SummarizationConfig = CFG, api_key: str = "key") -> str:
    async def sleep(seconds: float) -> None:
        state["sleeps"].append(seconds)

    return await state["call"]("a prompt", cfg, api_key, sleep=sleep)


# --------------------------------------------------------------------------
# retrying the transient failures
# --------------------------------------------------------------------------


async def test_a_503_is_retried_and_the_summary_survives(transport):
    """The failure mode this exists for: 503 alternating with 200 on the free tier."""
    state = transport(
        [
            httpx.Response(503, json={"error": {"message": "model overloaded"}}),
            httpx.Response(200, json=OK_BODY),
        ]
    )

    assert await _call(state) == "a grounded summary"
    assert len(state["requests"]) == 2
    assert len(state["sleeps"]) == 1


async def test_a_500_is_retried(transport):
    state = transport([httpx.Response(500, text="upstream fault"), httpx.Response(200, json=OK_BODY)])

    assert await _call(state) == "a grounded summary"
    assert len(state["requests"]) == 2


async def test_a_per_minute_429_is_retried(transport):
    state = transport(
        [
            httpx.Response(429, json=_per_minute_quota_body()),
            httpx.Response(200, json=OK_BODY),
        ]
    )

    assert await _call(state) == "a grounded summary"
    assert len(state["requests"]) == 2


async def test_attempts_are_bounded(transport):
    """A permanently sick upstream costs `max_attempts` requests, not more."""
    state = transport([httpx.Response(503, json={})])

    with pytest.raises(SummarizationError) as excinfo:
        await _call(state)

    assert len(state["requests"]) == CFG.max_attempts
    assert "503" in str(excinfo.value)


async def test_the_last_failure_is_what_the_caller_is_told(transport):
    state = transport([httpx.Response(503, json={}), httpx.Response(500, text="x")])

    with pytest.raises(SummarizationError) as excinfo:
        await _call(state)

    # first attempt 503, then 500 twice: the 500 is the one reported
    assert "500" in str(excinfo.value)


# --------------------------------------------------------------------------
# what must NOT be retried
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
async def test_client_errors_are_not_retried(transport, status):
    """A request the provider has already rejected as invalid will not become valid."""
    state = transport([httpx.Response(status, json={"error": {"message": "no"}})])

    with pytest.raises(SummarizationError) as excinfo:
        await _call(state)

    assert len(state["requests"]) == 1
    assert str(status) in str(excinfo.value)


async def test_the_retryable_set_is_exactly_the_three_transient_statuses():
    assert RETRYABLE_STATUSES == {429, 500, 503}


async def test_a_404_on_a_wrong_model_id_fails_immediately(transport):
    """
    A retired model 404s. `gemini-2.5-flash` is still listed by the models endpoint and
    404s when called, so this is a live shape, not a hypothetical -- and repeating it
    three times would just cost three requests.
    """
    state = transport([httpx.Response(404, json={"error": {"message": "not found"}})])

    with pytest.raises(SummarizationError):
        await _call(state)
    assert len(state["requests"]) == 1


# --------------------------------------------------------------------------
# the daily quota: a wall a retry budget cannot clear
# --------------------------------------------------------------------------


async def test_a_daily_quota_429_is_not_retried(transport):
    state = transport([httpx.Response(429, json=_daily_quota_body())])

    with pytest.raises(SummarizationError):
        await _call(state)

    assert len(state["requests"]) == 1, "a daily quota must cost exactly one request"
    assert state["sleeps"] == [], "no budget may be spent waiting for a daily reset"


async def test_the_daily_quota_message_says_why_it_did_not_retry(transport):
    state = transport([httpx.Response(429, json=_daily_quota_body())])

    with pytest.raises(SummarizationError) as excinfo:
        await _call(state)

    message = str(excinfo.value)
    assert "daily request quota is exhausted" in message
    assert "quota-day boundary" in message
    # the two recoveries a reader needs: switch model, or re-summarise later
    assert "REPOBRIDGE_GEMINI_MODEL" in message
    assert "generated later" in message


async def test_the_advertised_retry_delay_is_not_trusted_for_a_daily_quota(transport):
    """The body says `retryDelay: 58s`. Honouring it would retry into the same wall."""
    state = transport([httpx.Response(429, json=_daily_quota_body())])

    with pytest.raises(SummarizationError):
        await _call(state)
    assert 58.0 not in state["sleeps"]


async def test_the_quota_id_is_named_so_a_reader_can_check_it(transport):
    state = transport([httpx.Response(429, json=_daily_quota_body())])

    with pytest.raises(SummarizationError) as excinfo:
        await _call(state)
    assert "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in str(excinfo.value)


async def test_a_quota_id_that_is_not_a_google_constant_is_not_echoed(transport):
    """
    An error body can carry the prompt back, and the prompt is repository content. Only
    identifier-shaped quota ids reach the message; anything else is described generically.
    """
    leaky = "prompt=SECRET REPOSITORY CONTENT"
    body = _daily_quota_body()
    body["error"]["details"][0]["violations"][0]["quotaId"] = leaky
    body["error"]["details"][0]["violations"][0]["quotaMetric"] = "quota/PerDay"
    state = transport([httpx.Response(429, json=body)])

    with pytest.raises(SummarizationError) as excinfo:
        await _call(state)

    message = str(excinfo.value)
    assert "SECRET REPOSITORY CONTENT" not in message
    assert "a per-day quota" in message


def test_a_per_minute_quota_is_not_mistaken_for_a_daily_one():
    assert _daily_quota_id(_per_minute_quota_body()) is None


def test_a_daily_quota_is_recognised_from_the_metric_alone():
    body = {
        "error": {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaMetric": "something/PerDay/requests"}],
                }
            ]
        }
    }
    assert _daily_quota_id(body) is not None


@pytest.mark.parametrize("body", [None, {}, {"error": {}}, {"error": {"details": "nope"}}, "text"])
def test_malformed_error_bodies_are_not_read_as_a_daily_quota(body):
    """An unparseable body must degrade to "retry it", not to "give up for the day"."""
    assert _daily_quota_id(body) is None


# --------------------------------------------------------------------------
# the schedule: backoff, jitter, provider hints, and the total budget
# --------------------------------------------------------------------------


async def test_retry_after_header_is_honoured(transport):
    state = transport(
        [
            httpx.Response(503, headers={"Retry-After": "7"}, json={}),
            httpx.Response(200, json=OK_BODY),
        ]
    )

    await _call(state)
    assert state["sleeps"] == [7.0]


async def test_retry_info_is_honoured_when_there_is_no_header(transport):
    state = transport(
        [httpx.Response(429, json=_per_minute_quota_body()), httpx.Response(200, json=OK_BODY)]
    )

    await _call(state)
    assert state["sleeps"] == [3.0]  # retryDelay: 3s


async def test_a_provider_hint_is_still_capped_by_retry_max_delay(transport):
    cfg = SummarizationConfig(max_attempts=2, retry_max_delay=5.0, retry_budget_seconds=45.0)
    state = transport(
        [
            httpx.Response(503, headers={"Retry-After": "600"}, json={}),
            httpx.Response(200, json=OK_BODY),
        ]
    )

    await _call(state, cfg)
    assert state["sleeps"] == [5.0]


async def test_backoff_grows_between_attempts(transport):
    state = transport([httpx.Response(503, json={})])

    with pytest.raises(SummarizationError):
        await _call(state)

    first, second = state["sleeps"]
    # equal jitter: attempt n waits in [c/2, c] for a ceiling c that doubles
    assert 0.5 <= first <= 1.0
    assert 1.0 <= second <= 2.0


def test_backoff_is_jittered():
    """Identical inputs must not produce identical waits, or clients synchronise."""
    delays = {_backoff_delay(3, CFG) for _ in range(50)}
    assert len(delays) > 1


def test_backoff_never_exceeds_the_configured_ceiling():
    assert all(_backoff_delay(attempt, CFG) <= CFG.retry_max_delay for attempt in range(1, 12))


async def test_a_wait_that_does_not_fit_the_budget_is_not_attempted(transport):
    """
    The rule the daily-quota case generalises: never spend the budget on a wait that
    cannot clear the wall. Here the provider asks for 30s and 10s of budget remain.
    """
    cfg = SummarizationConfig(max_attempts=3, retry_max_delay=60.0, retry_budget_seconds=10.0)
    state = transport(
        [httpx.Response(503, headers={"Retry-After": "30"}, json={}), httpx.Response(200, json=OK_BODY)]
    )

    with pytest.raises(SummarizationError):
        await _call(state, cfg)

    assert state["sleeps"] == []
    assert len(state["requests"]) == 1


async def test_the_total_wait_never_exceeds_the_budget(transport):
    cfg = SummarizationConfig(
        max_attempts=6, retry_initial_delay=2.0, retry_max_delay=8.0, retry_budget_seconds=10.0
    )
    state = transport([httpx.Response(503, json={})])

    with pytest.raises(SummarizationError):
        await _call(state, cfg)

    assert sum(state["sleeps"]) <= cfg.retry_budget_seconds


def test_an_http_date_retry_after_falls_back_to_backoff():
    """Only the numeric form is parsed; the date form must not become a bogus delay."""
    resp = httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert _suggested_delay(resp, None) is None


# --------------------------------------------------------------------------
# the model: configurable, and read at call time
# --------------------------------------------------------------------------


def test_the_default_model_is_a_high_daily_quota_one():
    """
    Guards the decision, not the string: a quality-tier Flash model at 20 requests/day
    cannot be developed against. See the 2026-08-18 amendment in spec.md section 7.6.
    """
    assert SummarizationConfig().model == "gemini-3.5-flash-lite"


def test_the_model_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_MODEL", "gemini-3.1-flash-lite")
    assert get_summarization_config().model == "gemini-3.1-flash-lite"


def test_the_model_is_read_at_call_time_not_bound_at_import(monkeypatch):
    """
    The bug this guards against actually happened once, to the M5 extraction cap: a value
    bound in a default argument is evaluated at definition time and cannot be changed on a
    live process. The daily quota is *per model*, so switching models is the only recovery
    from an exhausted day -- it has to work without a restart.
    """
    before = get_summarization_config().model
    monkeypatch.setenv("REPOBRIDGE_GEMINI_MODEL", "gemini-3.1-flash-lite")
    during = get_summarization_config().model
    monkeypatch.delenv("REPOBRIDGE_GEMINI_MODEL")
    after = get_summarization_config().model

    assert during == "gemini-3.1-flash-lite"
    assert after == before == SummarizationConfig().model


def test_a_blank_model_override_is_ignored(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_MODEL", "   ")
    assert get_summarization_config().model == SummarizationConfig().model


def test_the_model_override_does_not_disturb_the_token_budget(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("REPOBRIDGE_SUMMARY_TOKEN_BUDGET", "999")
    cfg = get_summarization_config()
    assert (cfg.model, cfg.max_prompt_tokens) == ("gemini-3.1-flash-lite", 999)


async def test_the_configured_model_is_the_one_requested(transport):
    cfg = SummarizationConfig(model="gemini-3.1-flash-lite")
    state = transport([httpx.Response(200, json=OK_BODY)])

    await _call(state, cfg)
    assert "/models/gemini-3.1-flash-lite:generateContent" in state["requests"][0]


async def test_a_retry_does_not_silently_change_model(transport):
    cfg = SummarizationConfig(model="gemini-3.1-flash-lite", max_attempts=2)
    state = transport([httpx.Response(503, json={}), httpx.Response(200, json=OK_BODY)])

    await _call(state, cfg)
    assert all("gemini-3.1-flash-lite" in url for url in state["requests"])


async def test_the_api_key_is_never_in_a_retried_url(transport):
    secret = "AIzaSyRETRYKEYMUSTNEVERAPPEARINAURL0000"
    state = transport([httpx.Response(503, json={}), httpx.Response(200, json=OK_BODY)])

    await _call(state, api_key=secret)
    assert all(secret not in url for url in state["requests"])
