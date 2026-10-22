"""External anchor contract. The synthetic double is labeled as a test double."""
from __future__ import annotations

import pytest

from orca.genesis.training.external_anchor import (
    SYNTHETIC_TEST_DOUBLE,
    AnchorReceiptError,
    AnchorUnavailable,
    FailClosedExternalAnchor,
    RollbackRejected,
    SyntheticAnchorDouble,
)


def test_fail_closed_anchor_never_commits():
    anchor = FailClosedExternalAnchor()
    with pytest.raises(AnchorUnavailable):
        anchor.commit("run", 1, "abc")
    with pytest.raises(AnchorUnavailable):
        anchor.verify({"kind": SYNTHETIC_TEST_DOUBLE})


def test_synthetic_double_rejects_rollback_and_is_labeled():
    anchor = SyntheticAnchorDouble()
    first = anchor.commit("run", 2, "digest-a")
    assert first["kind"] == SYNTHETIC_TEST_DOUBLE
    anchor.verify(first)
    with pytest.raises(RollbackRejected, match="rollback"):
        anchor.commit("run", 1, "digest-b")
    with pytest.raises(RollbackRejected, match="conflicting"):
        anchor.commit("run", 2, "digest-b")
    later = anchor.commit("run", 3, "digest-c")
    anchor.verify(later)
    with pytest.raises(RollbackRejected):
        anchor.verify(first)
    with pytest.raises(AnchorReceiptError):
        anchor.verify({"kind": "EXTERNAL_WITNESS", "run_id": "run", "step": 3, "digest": "digest-c"})
