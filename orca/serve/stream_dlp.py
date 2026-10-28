"""Stateful output DLP for streamed tokens.

Per-chunk ``scan_output`` misses secrets split across deltas. Character-by-
character PEM streaming previously escaped incomplete-suffix holding and
emitted private-key bodies before validation. This redactor:

* never releases ambiguous secret bytes before a complete match is decided
* holds every supported PEM BEGIN delimiter until a matching END (or fail-closed)
* covers API-key / bearer / GitHub / AWS shapes via bounded incomplete suffixes
* persists only ``safe_text()`` (emitted + still-held, fully scanned)
"""

from __future__ import annotations

import re

from orca.serve.dlp import redact_secrets, scan_output

# Pattern-derived budgets (must exceed the *minimum* match of every secret
# regex in orca.serve.dlp, and cap unbounded `{n,}` classes).
MAX_TOKEN_CHARS = 256
MAX_BEGIN_HEADER = 80
MAX_HOLD_CHARS = MAX_TOKEN_CHARS + MAX_BEGIN_HEADER
MAX_PEM_CHARS = 8_192
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
MAX_DELTA_CHARS = 8_192
MAX_TOTAL_CHARS = 1_048_576

_REDACT_OVERFLOW = "[REDACTED-OVERFLOW]"
_PEM_STARTER = "-----BEGIN "
_PEM_END_LIT = "PRIVATE KEY-----"

# Suffixes that are not yet a complete secret but could become one.
# Once a token passes its minimum match length, keep holding while the
# charset continues so a 20-char prefix of a longer key cannot redact
# early and leak the remainder character-by-character.
_INCOMPLETE = (
    re.compile(rf"(?:^|[^A-Za-z0-9])(s|sk|sk-|sk-[A-Za-z0-9]{{1,{MAX_TOKEN_CHARS}}})$"),
    re.compile(rf"(?:^|[^A-Za-z0-9])(sk-ant-?[A-Za-z0-9-]{{0,{MAX_TOKEN_CHARS}}})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(A|AK|AKI|AKIA[0-9A-Z]{0,16})$"),
    re.compile(rf"(?:^|[^A-Za-z0-9])(AKIA[0-9A-Z]{{16}}[A-Za-z0-9/+=]{{0,{MAX_TOKEN_CHARS}}})$"),
    re.compile(r"(?:^|[^A-Za-z0-9])(B|Be|Bea|Bear|Beare|Bearer)$"),
    re.compile(rf"(?:^|[^A-Za-z0-9])(Bearer[\t ]+[A-Za-z0-9._-]{{0,{MAX_TOKEN_CHARS}}})$"),
    re.compile(rf"(?:^|[^A-Za-z0-9])(g|gh|gh[pousr]|gh[pousr]_[A-Za-z0-9]{{0,{MAX_TOKEN_CHARS}}})$"),
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


def _is_incomplete_pem_begin(s: str) -> bool:
    """True iff ``s`` is a proper prefix of some ``-----BEGIN … PRIVATE KEY-----``."""
    if not s or _PEM_BEGIN.fullmatch(s):
        return False
    if _PEM_STARTER.startswith(s):
        return True
    if not s.startswith(_PEM_STARTER):
        return False
    rest = s[len(_PEM_STARTER) :]
    if re.fullmatch(r"[A-Z ]*", rest):
        return True
    for i in range(len(rest) + 1):
        label, tail = rest[:i], rest[i:]
        if not re.fullmatch(r"[A-Z ]*", label):
            continue
        if tail and _PEM_END_LIT.startswith(tail) and tail != _PEM_END_LIT:
            return True
    return False


def _incomplete_pem_begin_len(text: str) -> int:
    if not text:
        return 0
    maxn = min(len(text), MAX_BEGIN_HEADER)
    for n in range(maxn, 0, -1):
        if _is_incomplete_pem_begin(text[-n:]):
            return n
    return 0


def _split_emit_hold(text: str) -> tuple[str, str]:
    """Return (safe_to_emit, still_ambiguous_suffix).

    Hold length is decided on the *raw* buffer first. Running ``scan_output``
    on an open ``sk-…`` candidate would redact at the 20-char minimum and
    leak the remainder on subsequent pushes — so only the emit prefix is
    scanned, and the held suffix is scanned later on terminator/finish.
    """
    n_hold = _hold_suffix_len(text)
    if n_hold > MAX_HOLD_CHARS:
        return _REDACT_OVERFLOW, ""
    if n_hold:
        before, held = text[:-n_hold], text[-n_hold:]
        emit = scan_output(before)["safe_text"] if before else ""
        return emit, held
    return scan_output(text)["safe_text"], ""


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
    """Bounded stateful scanner. Ambiguous bytes stay in ``_hold`` until decided."""

    def __init__(self) -> None:
        self._hold = ""
        self._emitted: list[str] = []
        self._total = 0
        self._failed = False
        self._cancelled = False
        self._in_pem = False

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
        return self._drain()

    def _record(self, piece: str) -> str:
        if not piece:
            return ""
        if piece == _REDACT_OVERFLOW and not self._failed:
            self._failed = True
            self._hold = ""
            self._in_pem = False
        self._emitted.append(piece)
        return piece

    def _drain(self) -> str:
        out: list[str] = []
        while self._hold and not self._failed and not self._cancelled:
            if self._in_pem:
                end = _PEM_END.search(self._hold)
                if end is None:
                    if len(self._hold) > MAX_PEM_CHARS:
                        return self._fail()
                    break
                block = self._hold[: end.end()]
                self._hold = self._hold[end.end() :]
                redacted = scan_output(block)["safe_text"]
                piece = self._record(redacted)
                if piece:
                    out.append(piece)
                self._in_pem = False
                continue

            found = _PEM_BEGIN.search(self._hold)
            if found is not None:
                before = self._hold[: found.start()]
                self._hold = self._hold[found.start() :]
                if before:
                    emit, held = _split_emit_hold(before)
                    # Bytes held as non-PEM secrets sit immediately before a
                    # confirmed BEGIN — they cannot be part of the PEM block,
                    # so flush them through a final scan (fail closed on overflow).
                    if held:
                        flush = scan_output(held)["safe_text"]
                        emit = emit + flush
                    piece = self._record(emit)
                    if piece == _REDACT_OVERFLOW:
                        return piece
                    if piece:
                        out.append(piece)
                self._in_pem = True
                if len(self._hold) > MAX_PEM_CHARS:
                    return self._fail()
                continue

            pem_n = _incomplete_pem_begin_len(self._hold)
            if pem_n:
                before = self._hold[:-pem_n]
                pem_suffix = self._hold[-pem_n:]
                if before:
                    emit, held = _split_emit_hold(before)
                    piece = self._record(emit)
                    if piece == _REDACT_OVERFLOW:
                        self._hold = ""
                        return piece
                    if piece:
                        out.append(piece)
                    # Keep unresolved secret suffix + PEM-prefix candidate together.
                    self._hold = held + pem_suffix
                else:
                    self._hold = pem_suffix
                break

            emit, held = _split_emit_hold(self._hold)
            self._hold = held
            piece = self._record(emit)
            if piece == _REDACT_OVERFLOW:
                self._hold = ""
                return piece
            if piece:
                out.append(piece)
            break

        return "".join(out)

    def finish(self) -> str:
        if self._cancelled:
            return ""
        if self._failed:
            tail = _REDACT_OVERFLOW if self._hold or self._in_pem else ""
            self._hold = ""
            self._in_pem = False
            if tail:
                self._emitted.append(tail)
            return tail
        if self._in_pem:
            # Unclosed PEM at end of stream: fail closed — never flush raw key material.
            self._hold = ""
            self._in_pem = False
            self._emitted.append(_REDACT_OVERFLOW)
            return _REDACT_OVERFLOW
        tail = scan_output(self._hold)["safe_text"]
        self._hold = ""
        if tail:
            self._emitted.append(tail)
        return tail

    def cancel(self) -> None:
        self._cancelled = True
        self._hold = ""
        self._in_pem = False

    def _fail(self) -> str:
        self._failed = True
        self._hold = ""
        self._in_pem = False
        self._emitted.append(_REDACT_OVERFLOW)
        return _REDACT_OVERFLOW

    def safe_text(self) -> str:
        if self._cancelled:
            return "".join(self._emitted)
        if self._failed:
            return "".join(self._emitted)
        if self._in_pem:
            return "".join(self._emitted) + _REDACT_OVERFLOW
        return "".join(self._emitted) + scan_output(self._hold)["safe_text"]
