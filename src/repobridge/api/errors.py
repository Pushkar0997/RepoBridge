"""
One error shape for the whole API.

**The problem this fixes.** Endpoints grew their conventions across seven milestones and
ended up with two incompatible error bodies. Ours were `{"detail": {"message": ...}}`;
FastAPI's own request-validation failures were `{"detail": [{...}, {...}]}` — the same key
holding an object in one case and a list in the other. A consumer could not write one
parser, which is exactly what `evals.md` means by "API can be used programmatically
without guessing response shape".

**The envelope.** Every non-2xx response from this application, without exception:

```json
{"error": {"status": 404, "code": "run_not_found",
           "message": "Run 'abc' was not found.", "details": {}}}
```

- `status` repeats the HTTP status in the body, so a logged body is self-describing.
- `code` is the stable machine-readable name. **Match on this, not on the message.**
  Messages are written for people and may be reworded; codes are the contract.
- `message` is one sentence a person can act on.
- `details` is always present, always an object, possibly empty. Extra structured facts
  live here — the `run_id` of a failed run, the list of valid values for a rejected
  filter, the per-field breakdown of a schema violation. The name and the "always an
  object" rule match `core/diagnostics.py`, which made the same choice for the same
  reason.

**Why `error` and not `detail`.** `detail` is FastAPI's name and it is meaningless to a
consumer — detail of what? Worse, keeping the name would keep the association with the
list-shaped form we are deliberately abandoning, so a client written against the old
`detail` would keep working for 404s and silently break on 422s. Renaming makes the change
visible at the one moment before v0.1 ships where an API break is free.

**Successes are not wrapped.** `tasks.md` suggests "consistent `data` and `error` fields or
similar pattern"; this is the "similar pattern". Wrapping every success in `data` would
re-path every field in every consumer, every test and every template — including every
honesty field whose exact location is cited in `smoke.md` — to convey nothing a caller
does not already know from the status code. The errors genuinely had two shapes; the
successes did not.

**Status codes name the faulting party.** The rule `_status_for` already applies to GitHub
failures, generalised:

- **4xx** — the caller's request is at fault. 422 when the request could not be *parsed*
  into the expected schema, 400 when it parsed and is not *acceptable* (a well-formed URL
  pointing at the wrong host, an unknown filter value). Both carry a `code`, so a consumer
  that cares about the distinction reads the code rather than the status.
- **404** — the resource does not exist.
- **429 / 502** — an upstream service is at fault, never the caller.
- **500** — this application is at fault, and it says so rather than reporting a caller
  error it invented.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from repobridge.core.diagnostics import redact

logger = logging.getLogger(__name__)


def api_error(
    status_code: int, code: str, message: str, **details: Any
) -> HTTPException:
    """
    Build the one error this API raises. `raise api_error(404, "run_not_found", ...)`.

    Details with a `None` value are dropped, so an optional field is absent rather than
    present-and-null — the same rule `Recorder.record` applies to event details.
    """
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": {k: v for k, v in details.items() if v is not None},
        },
    )


def run_not_found(run_id: str) -> HTTPException:
    """
    The most common error in the API, defined once.

    Six endpoints raised this with six copies of the same f-string. One copy means one
    wording and one code, and a seventh endpoint cannot invent a variation.
    """
    return api_error(404, "run_not_found", f"Run '{run_id}' was not found.", run_id=run_id)


def invalid_value(field: str, value: str, valid: list[str]) -> HTTPException:
    """
    A filter value that is not one of a known set.

    The valid set travels in `details` rather than only inside the prose, so a client can
    show the options without parsing an English sentence.
    """
    return api_error(
        400,
        "invalid_value",
        f"Unknown {field} '{value}'. Valid values: {', '.join(valid)}.",
        field=field,
        value=value,
        valid=valid,
    )


def _body(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "status": status,
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )


#: Codes for statuses raised without one — chiefly Starlette's own 404 and 405 for
#: unrouted paths, which never pass through `api_error`.
_DEFAULT_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    422: "invalid_request",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
}


def install_error_handlers(app: FastAPI) -> None:
    """
    Route every failure through the one envelope.

    Registered on the app rather than applied per-endpoint, so an endpoint cannot opt out
    and a future endpoint cannot forget to opt in. That is the whole point: consistency
    enforced by construction rather than by review.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "message" in detail:
            # raised through `api_error`
            return _body(
                exc.status_code,
                detail.get("code") or _DEFAULT_CODES.get(exc.status_code, "error"),
                detail["message"],
                detail.get("details"),
            )
        # Starlette's own (unrouted path, wrong method) or a bare string detail
        return _body(
            exc.status_code,
            _DEFAULT_CODES.get(exc.status_code, "error"),
            detail if isinstance(detail, str) else "The request could not be completed.",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        """
        Schema violations, in the same envelope as everything else.

        Pydantic's per-error list is preserved under `details.fields` rather than
        discarded — it is genuinely useful, it was simply never the shape a caller could
        rely on finding, because only this one class of error produced it.
        """
        fields = [
            {
                "location": list(err.get("loc", [])),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        first = fields[0]["message"] if fields else "The request body is not valid."
        where = ".".join(str(p) for p in fields[0]["location"][1:]) if fields else ""
        return _body(
            422,
            "invalid_request",
            f"{first}{f' (at {where})' if where else ''}.",
            {"fields": fields},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        """
        This application's own failures, reported as this application's fault.

        **The exception text is deliberately not returned.** An unhandled exception can
        carry a request URL, a header, or a connection string, and this is the one error
        path nobody wrote on purpose — so it is the one least likely to have been checked
        for secrets. The response says only that the server failed.

        **The traceback is rendered here rather than handed to `logger.exception`**, so
        that `redact` can run over it. `exception()` defers formatting to the handler,
        which is past the last point this code controls — the traceback was therefore the
        one place a secret could reach a log line unscrubbed, and CONTRACT I-6 says no
        secret is logged. Nothing is lost: the full traceback is still emitted, and a
        secret is the one thing that was never any use for debugging.
        """
        logger.error(
            "Unhandled error serving %s %s\n%s",
            request.method,
            request.url.path,
            redact("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),
        )
        return _body(
            500,
            "internal_error",
            "RepoBridge failed to handle this request. The server log has the detail.",
        )
