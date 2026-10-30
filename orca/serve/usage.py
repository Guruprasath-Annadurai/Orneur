"""Local usage accounting. Does not place paid provider calls."""

from __future__ import annotations

import threading
from collections import defaultdict

from orca.rse.imp1.locks import spending_authorized

NATIVE_FAMILIES = frozenset({"genesis", "novus", "aeternum"})
PAID_BACKENDS = frozenset({"openai", "anthropic", "google", "openrouter"})


class UsageError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_lock = threading.Lock()
_rows: list[dict] = []
_tokens_in: dict[str, int] = defaultdict(int)
_tokens_out: dict[str, int] = defaultdict(int)


def record_usage(
    *,
    user_id: str,
    model: str,
    backend: str,
    tokens_in: int,
    tokens_out: int,
    native_family: str | None = None,
) -> dict:
    if not user_id:
        raise UsageError("unauthenticated")
    if tokens_in < 0 or tokens_out < 0:
        raise UsageError("tokens_refused")
    family = (native_family or "").lower() or None
    if family in NATIVE_FAMILIES and backend not in {"local", "none", "unavailable"}:
        raise UsageError("native_identity_refused")
    if backend in PAID_BACKENDS and not spending_authorized():
        raise UsageError("paid_backend_refused")
    row = {
        "user_id": user_id,
        "model": model,
        "backend": backend,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "native_family": family,
    }
    with _lock:
        _rows.append(row)
        _tokens_in[user_id] += int(tokens_in)
        _tokens_out[user_id] += int(tokens_out)
    return row


def snapshot(user_id: str) -> dict:
    if not user_id:
        raise UsageError("unauthenticated")
    with _lock:
        mine = [dict(row) for row in _rows if row["user_id"] == user_id]
        return {
            "user_id": user_id,
            "calls": len(mine),
            "tokens_in": _tokens_in.get(user_id, 0),
            "tokens_out": _tokens_out.get(user_id, 0),
            "paid_calls": 0,
        }


def reset_for_tests() -> None:
    with _lock:
        _rows.clear()
        _tokens_in.clear()
        _tokens_out.clear()
