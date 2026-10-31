"""Deterministic TOTP timestamps for L02-B3 step-up tests.

Wall-clock ``time.time() + 31`` is flaky: when the current second-of-step is
29, ``t+31`` lands on step N+2, which is outside the real accepted drift
window (±1 step). These helpers pin or compute timestamps that stay inside
the product window without loosening verify_totp / claim_totp_step.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

TOTP_STEP_S = 30
# Mid-step epoch so enable (current step) and next-step codes are stable.
FIXED_TOTP_EPOCH = 1_700_000_015.0


def mid_of_step(step: int) -> float:
    return float(step) * TOTP_STEP_S + (TOTP_STEP_S / 2)


def current_step(at_time: float | None = None) -> int:
    t = time.time() if at_time is None else at_time
    return int(t // TOTP_STEP_S)


def next_step_mid(at_time: float | None = None) -> float:
    """Timestamp firmly inside the next TOTP step (always within window=1 of now)."""
    return mid_of_step(current_step(at_time) + 1)


@contextmanager
def freeze_totp_wall_clock(epoch: float = FIXED_TOTP_EPOCH) -> Iterator[float]:
    """Freeze ``time.time`` for in-process TOTP generate + verify paths.

    Patches both the stdlib ``time`` module and ``orca.auth.totp.time`` so
    TestClient request handlers see the same controlled clock as the test.
    """
    import orca.auth.totp as totp_mod

    real_time = time.time
    real_totp_time = totp_mod.time.time

    def _frozen() -> float:
        return epoch

    time.time = _frozen  # type: ignore[assignment]
    totp_mod.time.time = _frozen  # type: ignore[method-assign]
    try:
        yield epoch
    finally:
        time.time = real_time  # type: ignore[assignment]
        totp_mod.time.time = real_totp_time  # type: ignore[method-assign]
