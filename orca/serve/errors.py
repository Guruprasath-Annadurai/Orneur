"""
Client-safe error reporting for the serve layer.

Real gap this closes (Checkpoint 1): several routes returned ``str(exc)``
straight to the caller (``/api/chat``, ``/api/stream``, ``/api/ultra``,
``/api/vision``, document extraction, checkout). Upstream provider errors
routinely echo account details, request ids and masked API keys ("Incorrect
API key provided: sk-...abcd"), and library errors can carry file paths.
None of that belongs in a response to an end user.

``public_error`` gives the client only a stable ``code``, a generic message
and an ``error_id`` an operator can search for.

DEF-CP1-02 (Checkpoint 2 finding): Checkpoint 1 logged the raw exception
server-side via ``exc_info=exc`` on the (reasonable) assumption that "server
logs" are a safe place for what callers must not see. They are not: this
process's logs are typically shipped to a log aggregator, retained for
weeks, and readable by a much wider on-call/ops population than the
original caller. The threat is identical to the one this module exists to
address -- it is the SAME upstream exception, the SAME masked keys and
account identifiers, just moved to a destination with a wider, longer-lived
audience instead of being removed.

A first attempt at this fix ran the formatted traceback through secret/PII
redaction (the same patterns ``orca/serve/dlp.py`` already applies to model
OUTPUT) before logging it. That is not enough: those patterns match known
SHAPES (an OpenAI-style key, an SSN, a bearer token). "Customer data" and
"sensitive provider error content" in the general case -- an org id, a file
path, an account email in a sentence rather than a key=value pair, anything
a provider's SDK decided to put in an exception message -- have no fixed
shape a regex can promise to catch. Treating that denylist as sufficient
would be the exact kind of confident-but-wrong claim this project's own
``dlp.py``/``pii_redact.py`` docstrings are careful never to make about
their own, narrower job (scanning chat output, not arbitrary exception text).

So the default behavior here is an allowlist, not a denylist: ``public_error``
logs ONLY structured, inherently-safe fields -- route, an error_id, the
caller's user_id (already just an opaque id, never a secret) and the
exception's TYPE name. The exception's own text/traceback is logged ONLY
when ``ORNEUR_LOG_EXCEPTION_DETAIL=1`` is set, clearly documented below as a
local-debugging opt-in that still runs through secret/PII redaction as a
second layer, never a production default. The error_id is the intended
correlation path: an operator reproduces the failure, or cross-references
the upstream provider's own dashboard/logs for that time window, using the
id the caller was given -- without this process's own logs ever having held
the sensitive content to begin with.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import traceback
import uuid
from dataclasses import dataclass

from orca.docs.pii_redact import redact_pii
from orca.serve.dlp import redact_secrets

_logger = logging.getLogger("orca.serve.errors")

_TIMEOUT_NAMES = {"TimeoutError", "TimeoutException", "ReadTimeout", "ConnectTimeout", "APITimeoutError"}

# Opt-in only, for local debugging. Second redaction layer for when it IS
# enabled -- shapes dlp.py's model-OUTPUT patterns don't cover but exception
# text/tracebacks commonly do (chat responses don't echo request headers or
# generic key=value credentials back at the user; library exceptions do).
_LOG_EXCEPTION_DETAIL_ENV = "ORNEUR_LOG_EXCEPTION_DETAIL"
_GENERIC_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\b(authorization)\s*:\s*\S+"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|client[_-]?secret)\b\s*[:=]\s*[\"']?[^\s\"'&,)]+"),
)


def _detail_logging_enabled() -> bool:
    return os.environ.get(_LOG_EXCEPTION_DETAIL_ENV, "") == "1"


def _redact(text: str) -> str:
    text = redact_secrets(text)
    text, _pii_report = redact_pii(text)
    for pattern in _GENERIC_CREDENTIAL_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    return text


# G-023 -- the stable, machine-readable error vocabulary of the serve layer. A client may switch on `code`; the message is for people and may be
# reworded. Codes are never removed or repurposed (add new ones). The HTTP status is the default for the code; a route may still choose another.
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    "auth_required": (401, "Please sign in to continue."),
    "forbidden": (403, "You do not have access to this."),
    "model_access_denied": (402, "Your plan does not include this model."),
    "quota_exceeded": (429, "You have reached your usage limit for today."),
    "rate_limited": (429, "Too many requests. Please slow down and retry."),
    "content_refused": (400, "This request can't be processed -- it matches a category we don't generate content for."),
    "request_abstained": (422, "This request can't be completed."),
    "invalid_request": (422, "The request was not valid."),
    "not_found": (404, "Not found."),
    "conflict": (409, "The request conflicts with the current state."),
    "session_busy": (409, "This conversation is busy with another request. Wait for it to finish and try again."),
    "history_unavailable": (503, "Conversation history is temporarily unavailable, so this request was not started. Nothing was lost; please retry shortly."),
    "turn_superseded": (409, "This conversation moved on while the reply was being generated, so it was not saved."),
    "capability_disabled": (403, "This capability is not available in this environment."),
    "model_unavailable": (503, "This model is not available right now. Please choose another model or try again later."),
    "upstream_timeout": (504, "The model backend timed out. Please try again."),
    "backend_unreachable": (503, "The model backend could not be reached. Please try again shortly."),
    "backend_error": (502, "The model backend could not complete this request. Please try again."),
    "server_busy": (503, "The server is at capacity. Please retry shortly."),
    "server_draining": (503, "The server is restarting and is not accepting new requests. Nothing was started or charged. Please retry in a moment."),
    "request_timeout": (504, "This request took longer than the allowed time and was stopped. Nothing from it was saved. You can send it again."),
    "cancelled": (499, "The request was cancelled."),
    "internal_error": (500, "Something went wrong on our side. Please try again."),
}

_STATUS_DEFAULT_CODE = {401: "auth_required", 402: "model_access_denied", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_request",
                        429: "rate_limited", 503: "server_busy", 504: "upstream_timeout"}


def default_code_for_status(status: int) -> str:
    if status in _STATUS_DEFAULT_CODE:
        return _STATUS_DEFAULT_CODE[status]
    return "internal_error" if status >= 500 else "invalid_request"


@dataclass(frozen=True)
class PublicError:
    code: str
    message: str
    error_id: str
    status: int = 500
    extra: tuple = ()          # ((key, value), ...) -- safe, structured, caller-visible additions (e.g. used/limit)

    def as_json(self) -> dict:
        return {"error": self.message, "code": self.code, "error_id": self.error_id, **dict(self.extra)}

    def as_sse(self) -> dict:
        return {"type": "error", "text": self.message, "code": self.code, "error_id": self.error_id, **dict(self.extra)}


def coded_error(code: str, *, message: str | None = None, status: int | None = None, **extra) -> PublicError:
    """An error with a stable `code` that is not caused by an exception (quota, plan gate, refusal, ...)."""
    if code not in ERROR_CATALOG:
        raise KeyError(f"unknown error code: {code}")
    default_status, default_message = ERROR_CATALOG[code]
    return PublicError(code=code, message=message or default_message, error_id=uuid.uuid4().hex[:12],
                       status=status or default_status, extra=tuple(extra.items()))


def _classify_one(exc: BaseException) -> tuple[str, str] | None:
    names = {cls.__name__ for cls in type(exc).__mro__}
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled", ERROR_CATALOG["cancelled"][1]
    if "ModelNotRoutableError" in names or "CircuitOpenError" in names or "DeploymentUnavailableError" in names or "WorkerUnhealthyError" in names:
        return "model_unavailable", ERROR_CATALOG["model_unavailable"][1]
    # L02-06: the model gateway's admission limit (queue full / queue timeout) is CAPACITY, not a model failure: tell the user to retry, truthfully.
    if "QueueFullError" in names or "QueueTimeoutError" in names:
        return "server_busy", ERROR_CATALOG["server_busy"][1]
    if "GenerationTimeoutError" in names:
        return "upstream_timeout", ERROR_CATALOG["upstream_timeout"][1]
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or names & _TIMEOUT_NAMES:
        return "upstream_timeout", ERROR_CATALOG["upstream_timeout"][1]
    if isinstance(exc, (ConnectionError, OSError)) or "ConnectError" in names:
        return "backend_unreachable", ERROR_CATALOG["backend_unreachable"][1]
    return None


def _classify(exc: BaseException) -> tuple[str, str]:
    """Walk the cause chain (the Kernel wraps backend failures), most specific first; unrecognised -> generic backend_error."""
    seen, cur = 0, exc
    while cur is not None and seen < 6:
        hit = _classify_one(cur)
        if hit:
            return hit
        cur = cur.__cause__ or cur.__context__
        seen += 1
    return "backend_error", ERROR_CATALOG["backend_error"][1]


def public_error(exc: BaseException, *, route: str, user_id: str | None = None,
                 code: str | None = None, message: str | None = None) -> PublicError:
    """Log what is safe, and return what is safe to show the caller.

    ``code``/``message`` override the classification for call sites that know
    better (for example a checkout failure) but are still never given the
    exception text.

    Routine logging is metadata-only (route, error_id, user_id, exception
    type name) -- never the exception's own message or traceback, since that
    text is exactly what this function exists to keep out of a caller's
    hands, and a log line is not a different trust boundary from a response
    body. Set ``ORNEUR_LOG_EXCEPTION_DETAIL=1`` to additionally log a
    redacted traceback for LOCAL DEBUGGING ONLY; this is a second layer on
    top of the redaction already applied to model output, not a guarantee --
    do not enable it against a production log destination.
    """
    error_id = uuid.uuid4().hex[:12]
    auto_code, auto_message = _classify(exc)
    _logger.error(
        "request failed route=%s error_id=%s user=%s type=%s",
        route, error_id, user_id or "anonymous", type(exc).__name__,
    )
    if _detail_logging_enabled():
        formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        _logger.debug("error_id=%s detail (redacted, debug-only):\n%s", error_id, _redact(formatted))
    final_code = code or auto_code
    return PublicError(code=final_code, message=message or auto_message, error_id=error_id,
                       status=ERROR_CATALOG.get(final_code, (500, ""))[0])
