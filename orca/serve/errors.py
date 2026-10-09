"""
Client-safe error reporting for the serve layer.

Real gap this closes: several routes returned ``str(exc)`` straight to the
caller (``/api/chat``, ``/api/stream``, ``/api/ultra``, ``/api/vision``,
document extraction, checkout). Upstream provider errors routinely echo
account details, request ids and masked API keys ("Incorrect API key
provided: sk-...abcd"), and library errors can carry file paths. None of
that belongs in a response to an end user.

``public_error`` keeps the full exception server-side (logged with a
correlation id) and gives the client only a stable ``code``, a generic
message and the ``error_id`` an operator can search for.

This module classifies; it does not decide authorization and it does not
retry. It never returns the exception text.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

_logger = logging.getLogger("orca.serve.errors")

_TIMEOUT_NAMES = {"TimeoutError", "TimeoutException", "ReadTimeout", "ConnectTimeout", "APITimeoutError"}


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
    """Log ``exc`` in full and return what is safe to show the caller.

    ``code``/``message`` override the classification for call sites that know
    better (for example a checkout failure) but are still never given the
    exception text.
    """
    error_id = uuid.uuid4().hex[:12]
    auto_code, auto_message = _classify(exc)
    _logger.error(
        "request failed route=%s error_id=%s user=%s type=%s",
        route, error_id, user_id or "anonymous", type(exc).__name__, exc_info=exc,
    )
    return PublicError(code=code or auto_code, message=message or auto_message, error_id=error_id)
