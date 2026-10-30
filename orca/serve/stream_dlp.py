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

# A secret that could still GROW or still be completed by the next delta. Matches only at a word boundary (a secret must start at one: the
# patterns in orca.serve.dlp are ``\b``-anchored) and only when it reaches the end of the buffer, so ``keys`` ending in "s" is plain text while
# ``... sk-a1B2`` / ``Bearer abc`` / a complete-but-unterminated ``sk-<24 chars>`` are all held until a character that ends them arrives.
# (Holding a *complete* key until it is terminated is what keeps its last few characters from being released after the redaction marker.)
_OPEN_TAIL = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"sk-[A-Za-z0-9\-]*|s|sk"
    r"|AKIA[0-9A-Z]*|A|AK|AKI"
    r"|Bearer\s+[A-Za-z0-9._\-]*|Bearer|Beare|Bear|Bea|Be|B"
    r"|gh[pousr]_[A-Za-z0-9]*|gh[pousr]|gh|g"
    r")\Z"                                                  # \Z, not $: "$" also matches before a trailing newline, which would hold a CLOSED token
)

class _Phase(str, Enum):
    NORMAL = "normal"
    PEM_HEADER = "pem_header"  # holding an incomplete -----BEGIN ... header
    PEM_BODY = "pem_body"  # saw complete BEGIN; holding until END (or overflow)
    FAILED = "failed"
    CANCELLED = "cancelled"


def _token_hold_suffix_len(text: str, prev: str = "") -> int:
    """Length of the suffix of ``text`` that may be the start (or the still-growing body) of a secret and so must not be released yet.

    ``prev`` is the character released just before ``text`` (word-boundary context for a candidate that starts at the very beginning)."""
    if not text:
        return 0
    ctx = prev[-1:] if prev else ""
    m = _OPEN_TAIL.search(ctx + text, len(ctx))        # the context character only supplies the word-boundary check; it is never part of a match
    return len(m.group(0)) if m is not None else 0


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

    A trailing run of dashes is ALWAYS held, wherever it follows (LANDMARK-01 B-01): releasing the first one or two dashes of ``-----BEGIN`` because
    they followed a non-space character (``key.-----BEGIN ...``) meant the header could never be recognised again and the whole PEM body streamed out.
    Holding costs a dash of latency until the next delta (or the end of the stream), nothing else.
    """
    if not text:
        return None
    maxn = min(len(text), MAX_BEGIN_HEADER + 8)
    for n in range(maxn, 0, -1):
        start = len(text) - n
        suf = text[start:]
        if not _is_pem_begin_prefix(suf):
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
        self._prev = ""  # last character released (word-boundary context for what is still held)

    @property
    def phase(self) -> str:
        return self._phase.value

    def push(self, delta: str | None) -> str:
        if self._phase in (_Phase.CANCELLED, _Phase.FAILED):
            return ""
        if not delta:
            return ""
        if not isinstance(delta, str) or len(delta) > MAX_DELTA_CHARS:
            return self._record(self._fail())
        self._total += len(delta)
        if self._total > MAX_TOTAL_CHARS:
            return self._record(self._fail())
        self._hold += delta
        return self._drain()

    def finish(self) -> str:
        """End of stream. Never flushes an incomplete PEM block or an oversized hold; everything else is released as the one-shot scan would."""
        if self._phase == _Phase.CANCELLED:
            return ""
        if self._phase == _Phase.FAILED:
            self._hold = ""
            return ""
        if self._phase in (_Phase.PEM_HEADER, _Phase.PEM_BODY):
            # Incomplete PEM construct at end-of-stream: fail closed.
            return self._record(self._fail())
        if not self._hold:
            return ""
        if _token_hold_suffix_len(self._hold, self._prev) > MAX_HOLD_CHARS:
            return self._record(self._fail())
        # The stream has ended, so nothing can grow any more: what is held is released exactly as the non-streaming route would redact it
        # (complete secrets become markers; a fragment shorter than the DLP's own 20-character definition of a secret is ordinary text -
        # "... a Bearer token" and "... keys" must keep their last words).
        tail = scan_output(self._hold)["safe_text"]
        self._hold = ""
        return self._record(tail)

    def cancel(self) -> None:
        self._phase = _Phase.CANCELLED
        self._hold = ""
        self._pem_from = 0

    def _record(self, text: str) -> str:
        if text:
            self._emitted.append(text)
            self._prev = text[-1]
        return text

    def _fail(self) -> str:
        """Fail closed: drop whatever is held and return the overflow marker. The caller records/returns the marker exactly once."""
        self._phase = _Phase.FAILED
        self._hold = ""
        self._pem_from = 0
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
                    self._prev = piece[-1]
                continue
            if self._phase == _Phase.PEM_HEADER:
                piece = self._drain_pem_header()
                if piece is None:
                    break
                if piece:
                    out.append(piece)
                    self._prev = piece[-1]
                continue
            piece = self._drain_normal()
            if piece is None:
                break
            if piece:
                out.append(piece)
                self._prev = piece[-1]
        return self._record("".join(out))

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
        token_n = _token_hold_suffix_len(self._hold, self._prev)
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
        n_hold = _token_hold_suffix_len(self._hold, self._prev)
        if n_hold > MAX_HOLD_CHARS:
            self._fail()
            return _REDACT_OVERFLOW
        head, self._hold = self._hold[: len(self._hold) - n_hold], self._hold[len(self._hold) - n_hold :]
        emit = scan_output(head)["safe_text"] if head else ""
        return emit if emit else None
