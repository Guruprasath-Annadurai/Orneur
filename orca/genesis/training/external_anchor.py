"""Adapter contract for an external anti-rollback anchor.

No external witness is configured. `FailClosedExternalAnchor` refuses
every commit and verify. `SyntheticAnchorDouble` is an in-process test
double. Its kind string is fixed and is not an external attestation,
not a founder signature, and not a production ledger.
"""
from __future__ import annotations

from typing import Protocol

SYNTHETIC_TEST_DOUBLE = "SYNTHETIC_TEST_DOUBLE"
EXTERNAL_ANCHOR_NOT_CONFIGURED = "EXTERNAL_ANCHOR_NOT_CONFIGURED"


class AnchorUnavailable(Exception):
    """No independently controlled external anchor is configured."""


class RollbackRejected(Exception):
    """The step would move the anchor backwards or disagree at the same step."""


class AnchorReceiptError(Exception):
    """The receipt is not from the adapter that is being asked to verify it."""


class Anchor(Protocol):
    kind: str

    def commit(self, run_id: str, step: int, digest: str) -> dict:
        ...

    def verify(self, receipt: dict) -> None:
        ...


class FailClosedExternalAnchor:
    """Production adapter until a real witness exists.

    Calling it does not create an anchor. It fails closed.
    """

    kind = EXTERNAL_ANCHOR_NOT_CONFIGURED

    def commit(self, run_id: str, step: int, digest: str) -> dict:
        raise AnchorUnavailable(
            "no independently controlled external anchor is configured; "
            "a local file is not a substitute witness"
        )

    def verify(self, receipt: dict) -> None:
        raise AnchorUnavailable(
            "no independently controlled external anchor is configured; receipt cannot be verified"
        )


class SyntheticAnchorDouble:
    """In-memory monotonic anchor for tests.

    `kind` is always `SYNTHETIC_TEST_DOUBLE`. The object does not persist
    across processes and has no authority outside the test that built it.
    """

    def __init__(self) -> None:
        self.kind = SYNTHETIC_TEST_DOUBLE
        self._highest: dict[str, tuple[int, str]] = {}

    def commit(self, run_id: str, step: int, digest: str) -> dict:
        if not run_id or not digest:
            raise RollbackRejected("run_id and digest are required")
        if step < 0:
            raise RollbackRejected("step must be non-negative")
        previous = self._highest.get(run_id)
        if previous is not None:
            prev_step, prev_digest = previous
            if step < prev_step:
                raise RollbackRejected(
                    f"refusing rollback of {run_id} from step {prev_step} to {step}"
                )
            if step == prev_step and digest != prev_digest:
                raise RollbackRejected(
                    f"refusing conflicting digest for {run_id} at step {step}"
                )
        self._highest[run_id] = (step, digest)
        return {
            "kind": SYNTHETIC_TEST_DOUBLE,
            "run_id": run_id,
            "step": step,
            "digest": digest,
        }

    def verify(self, receipt: dict) -> None:
        if receipt.get("kind") != SYNTHETIC_TEST_DOUBLE:
            raise AnchorReceiptError(
                "synthetic anchor refuses a receipt whose kind is not SYNTHETIC_TEST_DOUBLE"
            )
        run_id = receipt.get("run_id")
        if run_id not in self._highest:
            raise RollbackRejected("no synthetic commitment exists for this run")
        step, digest = self._highest[run_id]
        if receipt.get("step") != step or receipt.get("digest") != digest:
            raise RollbackRejected("receipt does not match the latest synthetic commitment")
