"""IMP-1 decisions.

A successful registry or grant check is CHECKS_PASSED. That word is not executable
authority: corpus generation, qualification, model selection, GPU, provider use,
spending and training stay denied. Unexpected errors become FAIL_CLOSED.
"""

from __future__ import annotations

CHECKS_PASSED = "CHECKS_PASSED"
FAIL_CLOSED = "FAIL_CLOSED"
QUARANTINE = "QUARANTINE"

_DECISIONS = frozenset({CHECKS_PASSED, FAIL_CLOSED, QUARANTINE})

# Frozen authorization locks. This table has no writer.
POSTURE = (
    ("corpus_generation", "NOT_AUTHORIZED"),
    ("qualification", "NOT_AUTHORIZED"),
    ("model_selection", False),
    ("gpu", False),
    ("provider", False),
    ("spending", False),
    ("training", False),
    ("provisioning", False),
    ("hardware_purchase", False),
    ("real_secret_creation", False),
    ("executable", False),
)


class FailClosed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Quarantine(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Result:
    """Immutable decision. ``executable`` is always false."""

    __slots__ = ("decision", "reason", "payload")

    def __init__(self, decision: str, reason: str, payload=None) -> None:
        if decision not in _DECISIONS:
            decision = FAIL_CLOSED
            reason = "BAD_DECISION"
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "payload", payload)

    def __setattr__(self, name, value) -> None:
        raise AttributeError("result is immutable")

    @property
    def executable(self) -> bool:
        return False

    @property
    def posture(self) -> tuple:
        return POSTURE

    @property
    def ok(self) -> bool:
        return self.decision == CHECKS_PASSED


def guard(fn):
    """Map every unexpected exception on a security path to FAIL_CLOSED."""

    def wrapped(*args, **kwargs) -> Result:
        try:
            out = fn(*args, **kwargs)
        except FailClosed as exc:
            return Result(FAIL_CLOSED, exc.reason)
        except Quarantine as exc:
            return Result(QUARANTINE, exc.reason)
        except Exception:
            return Result(FAIL_CLOSED, "UNEXPECTED")
        if not isinstance(out, Result):
            return Result(FAIL_CLOSED, "UNEXPECTED")
        return out

    wrapped.__wrapped__ = fn
    wrapped.__name__ = fn.__name__
    return wrapped
