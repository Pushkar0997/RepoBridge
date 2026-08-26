"""
Spend control for a shared instance.

**The problem.** On one shared demo instance every visitor spends the *operator's* GitHub
token and Gemini quota. A single `github/docs` analysis is 11,217 selected files; even
under the 200-file read cap that is 202 GitHub calls, and five idle-curious visitors can
exhaust a day's Gemini allowance between them. Nothing in the project stopped that,
because until now the only user was the person paying.

**What this is not.** Not auth, not per-visitor keys, not session isolation. Those are a
later milestone and building them here would be building the wrong thing. This is the
minimum that makes one shared instance survivable: a ceiling on how fast the operator's
quota can be spent, and by whom.

---

## Why a fixed window and not a token bucket

A sliding-log limiter with `deque` and `time.monotonic()` is about thirty lines, has no
dependency, and -- the property that decides it -- **can say exactly when the limit
resets**, because it knows when the oldest request in the window happened. Every other
limit in this project tells the reader what was exceeded and when it lifts: GitHub rate
limits carry a reset time, the read cap carries "20 of 107", the token budget carries what
did not fit. A limiter that could only say "too many requests" would be the one dishonest
limit in the codebase.

A token bucket would smooth bursts better and could not answer that question as precisely.
Burst smoothing is not the problem here; a clear refusal is.

## What this deliberately does not do

**It is per-process, in memory.** Two workers means two independent counters and an
effective limit of double what is configured. That is stated in the README rather than
solved, because solving it means Redis or a database table -- a dependency and a schema --
for a throwaway demo that will run one worker. **If the deployment is ever scaled beyond
one worker, these limits silently double.** Set `--workers 1`.

**It forgets on restart.** A restart resets every window. For a demo that is acceptable
and for anything real it is not, which is the same boundary as the sentence above.

**Identity is best-effort.** A "client" is an IP address, taken from `X-Forwarded-For`
when present because the app runs behind a proxy. A visitor who can change IP can have
another allowance. This is a fairness measure between honest testers, not a security
control, and it is written down as such so nobody later mistakes it for one.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LimitVerdict:
    """
    Whether an action is allowed, and -- when it is not -- everything needed to say so.

    `retry_after_seconds` and `limit` are what make the refusal actionable. A limiter that
    returns only a boolean forces the caller to invent a message, and invented messages
    are how "something went wrong" gets shipped.
    """

    allowed: bool
    scope: str = ""
    limit: int = 0
    used: int = 0
    retry_after_seconds: int = 0

    @property
    def retry_after_human(self) -> str:
        """"in 4 minutes" / "in 35 seconds" -- for a sentence a person reads."""
        seconds = max(1, self.retry_after_seconds)
        if seconds < 90:
            return f"in {seconds} second{'' if seconds == 1 else 's'}"
        minutes = (seconds + 59) // 60
        return f"in {minutes} minute{'' if minutes == 1 else 's'}"


ALLOWED = LimitVerdict(allowed=True)


class RateLimiter:
    """
    A sliding-window counter per key, in memory, thread-safe.

    `window_seconds` is an hour everywhere it is used, but is a parameter so tests do not
    have to wait one.
    """

    def __init__(self, window_seconds: int = 3600, clock=time.monotonic):
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._events[key]
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def check(self, key: str, limit: int, *, scope: str = "") -> LimitVerdict:
        """
        Would one more action be allowed? **Does not consume the allowance.**

        Separate from `record` on purpose: an analysis should only count against the
        limit if it actually runs, and the caller cannot know that until validation has
        passed. Checking and consuming in one call would charge a visitor for a typo.
        """
        if limit <= 0:
            return ALLOWED  # 0 means no limit, the default everywhere off a shared host

        with self._lock:
            now = self._clock()
            events = self._prune(key, now)
            if len(events) < limit:
                return ALLOWED

            oldest = events[0]
            # Ceiling, not floor-plus-one: floor would promise the allowance back a
            # moment early, and floor+1 overstates by up to a second, which rounds a
            # 50-minute wait up to "in 51 minutes".
            retry_after = math.ceil(oldest + self.window_seconds - now)
            return LimitVerdict(
                allowed=False,
                scope=scope or key,
                limit=limit,
                used=len(events),
                retry_after_seconds=max(1, retry_after),
            )

    def record(self, key: str) -> None:
        """Consume one unit of the allowance. Call once the action has gone ahead."""
        with self._lock:
            now = self._clock()
            self._prune(key, now)
            self._events[key].append(now)

    def used(self, key: str) -> int:
        with self._lock:
            return len(self._prune(key, self._clock()))

    def reset(self) -> None:
        """Forget everything. For tests and for an operator wanting a clean slate."""
        with self._lock:
            self._events.clear()


#: The process-wide limiter. One instance, one set of counters -- see the module docstring
#: on why that is per-process and what it costs.
_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter


def client_key(forwarded_for: str | None, direct_host: str | None) -> str:
    """
    Which visitor this is, best-effort.

    `X-Forwarded-For` is a list appended to by each proxy, so the *first* entry is the
    original client. It is also trivially spoofable by the client, which is exactly why
    the module docstring calls this a fairness measure and not a security control -- but
    behind a platform's proxy the direct peer is the proxy itself, so using it alone would
    put every visitor in one bucket and make the per-client limit meaningless.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return direct_host or "unknown"
