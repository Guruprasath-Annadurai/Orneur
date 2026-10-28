"""Stateful output DLP for streamed tokens.

Per-chunk ``scan_output`` misses secrets split across deltas. This redactor
holds any suffix that could still become a supported secret pattern, emits
only bytes that cannot complete a secret, and fail-closes when a candidate
exceeds the explicit inspection budget derived from those patterns.
"""

from __future__ import annotations

import re

from orca.serve.dlp import redact_secrets, scan_output

# Pattern-derived budgets (must exceed the *minimum* match of every secret
# regex in orca.serve.dlp, and cap unbounded `{n,}` classes).
MAX_TOKEN_CHARS = 256
MAX_BEGIN_HEADER = 64
MAX_HOLD_CHARS = MAX_TOKEN_CHARS + MAX_BEGIN_HEADER
MAX_DELTA_CHARS = 8_192
MAX_TOTAL_CHARS = 1_048_576

_REDACT_OVERFLOW = "[REDACTED-OVERFLOW]"

# Suffixes that are not yet a complete secret but could become one.
_INCOMPLETE = (
    re.compile(r"(?:^|[^A-Za-z0-9])(s|sk|sk-|sk-[A-Za-z0-9]{1,19})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(sk-ant-?[A-Za-z0-9-]{0,19})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(A|AK|AKI|AKIA[0-9A-Z]{0,15})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(B|Be|Bea|Bear|Beare|Bearer)$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(Bearer[\t ]+[A-Za-z0-9._-]{0,19})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(g|gh|gh[pousr]|gh[pousr]_[A-Za-z0-9]{0,19})$"),
    re.compile(r"(-----(?:BEGIN(?: [A-Z ]{0,40})?)?)$"),
)


def _is_incomplete_suffix(suffix: str) -> bool:
    if not suffix:
        return False
    padded = suffix if not suffix[0].isalnum() else " " + suffix
    return any(pattern.search(padded) or pattern.search(suffix) for pattern in _INCOMPLETE)


def _hold_suffix_len(text: str) -> int:
    if not text:
        return 0
    maxn = min(len(text), MAX_HOLD_CHARS)
    for n in range(maxn, 0, -1):
        if _is_incomplete_suffix(text[-n:]):
            return n
    return 0


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
    def __init__(self) -> None:
        self._hold = ""
        self._emitted: list[str] = []
        self._total = 0
        self._failed = False
        self._cancelled = False

    def push(self, delta: str | None) -> str:
        if self._cancelled or self._failed:
            return ""
        if not delta:
            return ""
        if not isinstance(delta, str) or len(delta) > MAX_DELTA_CHARS:
            return self._fail()
        self._total += len(delta)
        if self._total > MAX_TOTAL_CHARS:
            return self._fail()
        self._hold += delta
        scanned = scan_output(self._hold)
        self._hold = scanned["safe_text"]
        if len(self._hold) > MAX_HOLD_CHARS:
            # Unbounded token exceeded the inspection budget.
            if re.search(r"sk-[A-Za-z0-9]{20,}$", self._hold) or re.search(r"gh[pousr]_[A-Za-z0-9]{20,}$", self._hold):
                return self._fail()
            # Keep only the budgeted tail; emit the scanned prefix.
        n_hold = _hold_suffix_len(self._hold)
        if n_hold > MAX_HOLD_CHARS:
            return self._fail()
        emit = self._hold[:-n_hold] if n_hold else self._hold
        self._hold = self._hold[-n_hold:] if n_hold else ""
        if emit:
            self._emitted.append(emit)
        return emit

    def finish(self) -> str:
        if self._cancelled:
            return ""
        if self._failed:
            tail = _REDACT_OVERFLOW if self._hold else ""
            self._hold = ""
            if tail:
                self._emitted.append(tail)
            return tail
        tail = scan_output(self._hold)["safe_text"]
        self._hold = ""
        if tail:
            self._emitted.append(tail)
        return tail

    def cancel(self) -> None:
        self._cancelled = True
        self._hold = ""

    def _fail(self) -> str:
        self._failed = True
        self._hold = ""
        self._emitted.append(_REDACT_OVERFLOW)
        return _REDACT_OVERFLOW

    def safe_text(self) -> str:
        if self._cancelled:
            return "".join(self._emitted)
        if self._failed:
            return "".join(self._emitted)
        return "".join(self._emitted) + scan_output(self._hold)["safe_text"]
