"""Stateful output DLP for streamed tokens.

Per-chunk ``scan_output`` misses secrets split across deltas. This redactor
is an incremental scanner with explicit state for incomplete secret prefixes,
incomplete PEM headers, PEM bodies, and PEM closing boundaries. Bytes that
remain part of a potentially sensitive sequence are never released. Incomplete
or oversized sensitive constructs fail closed. Cancellation, disconnect,
timeout, and error paths discard the hold without flushing unsafe content.
"""

from __future__ import annotations

import re
from enum import Enum

from orca.serve.dlp import redact_secrets, scan_output

# Pattern-derived budgets (must exceed the *minimum* match of every secret
# regex in orca.serve.dlp, and cap unbounded `{n,}` classes).
MAX_TOKEN_CHARS = 256
MAX_BEGIN_HEADER = 64
MAX_HOLD_CHARS = MAX_TOKEN_CHARS + MAX_BEGIN_HEADER
MAX_PEM_CHARS = 8_192
MAX_DELTA_CHARS = 8_192
MAX_TOTAL_CHARS = 1_048_576

_REDACT_OVERFLOW = "[REDACTED-OVERFLOW]"
_REDACT_PEM = "[REDACTED-PRIVATE_KEY_BLOCK]"

_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_PEM_MARKER = "PRIVATE KEY-----"
_PEM_LEAD = "-----BEGIN "

# Suffixes that are not yet a complete token/bearer/github secret but could become one.
_INCOMPLETE_TOKEN = (
    re.compile(r"(?:^|[^A-Za-z0-9])(s|sk|sk-|sk-[A-Za-z0-9]{1,19})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(sk-ant-?[A-Za-z0-9-]{0,19})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(A|AK|AKI|AKIA[0-9A-Z]{0,15})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(B|Be|Bea|Bear|Beare|Bearer)$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(Bearer[\t ]+[A-Za-z0-9._-]{0,19})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(g|gh|gh[pousr]|gh[pousr]_[A-Za-z0-9]{0,19})$"),
)


class _Phase(str, Enum):
    NORMAL = "normal"
    PEM_HEADER = "pem_header"  # holding an incomplete -----BEGIN ... header
    PEM_BODY = "pem_body"  # saw complete BEGIN; holding until END (or overflow)
    FAILED = "failed"
    CANCELLED = "cancelled"


def _is_incomplete_token_suffix(suffix: str) -> bool:
    if not suffix:
        return False
    padded = suffix if not suffix[0].isalnum() else " " + suffix
    return any(pattern.search(padded) or pattern.search(suffix) for pattern in _INCOMPLETE_TOKEN)


def _token_hold_suffix_len(text: str) -> int:
    if not text:
        return 0
    maxn = min(len(text), MAX_HOLD_CHARS)
    for n in range(maxn, 0, -1):
        if _is_incomplete_token_suffix(text[-n:]):
            return n
    return 0


def _is_pem_begin_prefix(s: str) -> bool:
    """True iff ``s`` is a prefix of some ``-----BEGIN [A-Z ]*PRIVATE KEY-----``."""
    if not s or not s.startswith("-"):
        return False
    if len(s) <= len(_PEM_LEAD):
        return _PEM_LEAD.startswith(s)
    if s == "-----BEGIN":
        return True
    if not s.startswith(_PEM_LEAD):
        return False
    rest = s[len(_PEM_LEAD) :]
    if _PEM_MARKER in rest:
        idx = rest.index(_PEM_MARKER)
        type_part = rest[:idx]
        after = rest[idx + len(_PEM_MARKER) :]
        if after:
            return False
        return all(c.isupper() or c == " " for c in type_part)
    for i in range(len(rest) + 1):
        type_part = rest[:i]
        rem = rest[i:]
        if not all(c.isupper() or c == " " for c in type_part):
            continue
        if _PEM_MARKER.startswith(rem):
            return True
    return False


def _pem_header_hold_from(text: str) -> int | None:
    """Index from which an incomplete PEM BEGIN header must be held, else None.

    Short dash runs (1-2 chars) are only held at a boundary (start of buffer
    or after whitespace) so streamed prose like ``pong-`` is not split, while
    character-by-character ``-----BEGIN`` still accumulates from the first dash.
    """
    if not text:
        return None
    maxn = min(len(text), MAX_BEGIN_HEADER + 8)
    for n in range(maxn, 0, -1):
        start = len(text) - n
        suf = text[start:]
        if not _is_pem_begin_prefix(suf):
            continue
        if len(suf) < 3:
            prev = text[start - 1] if start > 0 else None
            if prev is not None and not prev.isspace():
                continue
        return start
    return None


def redact_structure(value):
    """Fail-closed redaction of nested SSE/error payloads."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {k: redact_structure(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_structure(v) for v in value]
    return value


class StreamRedactor:
    """Incremental secret scanner with explicit PEM / token hold state."""

    def __init__(self) -> None:
        self._hold = ""
        self._emitted: list[str] = []
        self._total = 0
        self._phase = _Phase.NORMAL
        self._pem_from = 0  # index into _hold where PEM body/header starts

    @property
    def phase(self) -> str:
        return self._phase.value

    def push(self, delta: str | None) -> str:
        if self._phase in (_Phase.CANCELLED, _Phase.FAILED):
            return ""
        if not delta:
            return ""
        if not isinstance(delta, str) or len(delta) > MAX_DELTA_CHARS:
            return self._fail()
        self._total += len(delta)
        if self._total > MAX_TOTAL_CHARS:
            return self._fail()
        self._hold += delta
        return self._drain()

    def finish(self) -> str:
        """End of stream. Never flushes incomplete/oversized sensitive holds."""
        if self._phase == _Phase.CANCELLED:
            return ""
        if self._phase == _Phase.FAILED:
            self._hold = ""
            return ""
        if self._phase in (_Phase.PEM_HEADER, _Phase.PEM_BODY):
            # Incomplete PEM construct at end-of-stream: fail closed.
            return self._fail()
        if not self._hold:
            return ""
        # Final token pass — still withhold anything that looks incomplete/oversized.
        if _token_hold_suffix_len(self._hold) == len(self._hold) and len(self._hold) > MAX_HOLD_CHARS:
            return self._fail()
        if re.search(r"sk-[A-Za-z0-9]{20,}$", self._hold) or re.search(r"gh[pousr]_[A-Za-z0-9]{20,}$", self._hold):
            if len(self._hold) > MAX_HOLD_CHARS:
                return self._fail()
        scanned = scan_output(self._hold)
        # If the hold was only an incomplete secret prefix, redact_secrets leaves it
        # intact — withhold rather than emit a dangling sk-/Bearer/gh prefix.
        if _token_hold_suffix_len(scanned["safe_text"]) == len(scanned["safe_text"]) and scanned["safe_text"]:
            # Pure incomplete prefix with no complete secret: drop closed (empty),
            # not a leak. Empty is safer than emitting "sk-" / "Bearer".
            self._hold = ""
            return ""
        tail = scanned["safe_text"]
        self._hold = ""
        if tail:
            self._emitted.append(tail)
        return tail

    def cancel(self) -> None:
        self._phase = _Phase.CANCELLED
        self._hold = ""
        self._pem_from = 0

    def _fail(self) -> str:
        self._phase = _Phase.FAILED
        self._hold = ""
        self._pem_from = 0
        self._emitted.append(_REDACT_OVERFLOW)
        return _REDACT_OVERFLOW

    def safe_text(self) -> str:
        """Emitted text only. Never includes unsafe held content."""
        return "".join(self._emitted)

    def _drain(self) -> str:
        out: list[str] = []
        while self._hold and self._phase not in (_Phase.CANCELLED, _Phase.FAILED):
            if self._phase == _Phase.PEM_BODY:
                piece = self._drain_pem_body()
                if piece is None:
                    break
                if piece:
                    out.append(piece)
                continue
            if self._phase == _Phase.PEM_HEADER:
                piece = self._drain_pem_header()
                if piece is None:
                    break
                if piece:
                    out.append(piece)
                continue
            piece = self._drain_normal()
            if piece is None:
                break
            if piece:
                out.append(piece)
        emitted = "".join(out)
        if emitted:
            self._emitted.append(emitted)
        return emitted

    def _drain_pem_body(self) -> str | None:
        body = self._hold[self._pem_from :]
        end = _PEM_END.search(body)
        if end:
            before = self._hold[: self._pem_from]
            # Redact from BEGIN through END; keep any trailing bytes after END.
            after = body[end.end() :]
            self._hold = after
            self._pem_from = 0
            self._phase = _Phase.NORMAL
            # before was already scanned/safe when we entered PEM_BODY
            return before + _REDACT_PEM
        if len(body) > MAX_PEM_CHARS:
            self._fail()
            return _REDACT_OVERFLOW
        # Still incomplete — emit nothing from the PEM region; before is already out.
        if self._pem_from > 0:
            before = self._hold[: self._pem_from]
            self._hold = self._hold[self._pem_from :]
            self._pem_from = 0
            return before
        return None

    def _drain_pem_header(self) -> str | None:
        # Try to complete BEGIN from hold start (pem_from).
        region = self._hold[self._pem_from :]
        begin = _PEM_BEGIN.match(region)
        if begin:
            # Promote to body; keep holding from pem_from.
            self._phase = _Phase.PEM_BODY
            return ""
        if not _is_pem_begin_prefix(region):
            # No longer a PEM header candidate (diverged) — return to normal.
            self._phase = _Phase.NORMAL
            self._pem_from = 0
            return ""
        if len(region) > MAX_BEGIN_HEADER + 8:
            self._fail()
            return _REDACT_OVERFLOW
        # Still incomplete header — hold everything from pem_from.
        if self._pem_from > 0:
            before = self._hold[: self._pem_from]
            self._hold = region
            self._pem_from = 0
            return before
        return None

    def _drain_normal(self) -> str | None:
        # Complete PEM BEGIN anywhere in the buffer?
        begin = _PEM_BEGIN.search(self._hold)
        if begin:
            prefix = self._hold[: begin.start()]
            rest = self._hold[begin.start() :]
            safe_prefix = self._release_safe(prefix)
            self._hold = rest
            self._pem_from = 0
            self._phase = _Phase.PEM_BODY
            return safe_prefix

        # Incomplete PEM header at the end? Prefer a longer token hold when
        # both apply (e.g. ``sk-`` must not lose its trailing dash to PEM).
        pem_at = _pem_header_hold_from(self._hold)
        token_n = _token_hold_suffix_len(self._hold)
        if pem_at is not None:
            pem_n = len(self._hold) - pem_at
            if token_n >= pem_n:
                pem_at = None
        if pem_at is not None:
            prefix = self._hold[:pem_at]
            safe_prefix = self._release_safe(prefix)
            self._hold = self._hold[pem_at:]
            self._pem_from = 0
            self._phase = _Phase.PEM_HEADER
            return safe_prefix

        return self._release_with_token_hold()

    def _release_safe(self, text: str) -> str:
        if not text:
            return ""
        return scan_output(text)["safe_text"]

    def _release_with_token_hold(self) -> str | None:
        scanned = scan_output(self._hold)
        self._hold = scanned["safe_text"]
        if len(self._hold) > MAX_HOLD_CHARS:
            if re.search(r"sk-[A-Za-z0-9]{20,}$", self._hold) or re.search(
                r"gh[pousr]_[A-Za-z0-9]{20,}$", self._hold
            ):
                self._fail()
                return _REDACT_OVERFLOW
        n_hold = _token_hold_suffix_len(self._hold)
        if n_hold > MAX_HOLD_CHARS:
            self._fail()
            return _REDACT_OVERFLOW
        emit = self._hold[:-n_hold] if n_hold else self._hold
        self._hold = self._hold[-n_hold:] if n_hold else ""
        return emit if emit else None
