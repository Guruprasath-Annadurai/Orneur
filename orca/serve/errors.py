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


@dataclass(frozen=True)
class PublicError:
    code: str
    message: str
    error_id: str

    def as_json(self) -> dict:
        return {"error": self.message, "code": self.code, "error_id": self.error_id}

    def as_sse(self) -> dict:
        return {"type": "error", "text": self.message, "code": self.code, "error_id": self.error_id}


def _classify(exc: BaseException) -> tuple[str, str]:
    names = {cls.__name__ for cls in type(exc).__mro__}
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or names & _TIMEOUT_NAMES:
        return "upstream_timeout", "The model backend timed out. Please try again."
    if isinstance(exc, (ConnectionError, OSError)) or "ConnectError" in names:
        return "backend_unreachable", "The model backend could not be reached. Please try again shortly."
    return "backend_error", "The model backend could not complete this request. Please try again."


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
    return PublicError(code=code or auto_code, message=message or auto_message, error_id=error_id)
