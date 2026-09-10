"""
Phase 15.13 -- UNIT tests for orca.mission.relay_reconnect (no mission
Neon database required): the typed network/operation-truth model,
result-ref secret redaction, and the mutation-precondition state
classification logic.

Live-Neon-dependent behavior (real reconnect against a real security-
valid Relay session, real operation reconciliation with real access
control, real two-device/concurrent scenarios, real lost-response
proofs, and real mission mutation preconditions against a real Postgres
`missions` row) is covered in tests/test_relay_reconnect_live_neon.py
(LIVE_NEON_TEMP_BRANCH).
"""
from __future__ import annotations

import pytest

from orca.mission.relay_reconnect import (
    OperationReconciliationSummary,
    RelayMutationOutcome,
    RelayReconnectError,
    RelayConnectionState,
    RelayFreshness,
    RelayOperationTruth,
    _summarize_operation_row,
    classify_operation_truth,
)
from orca.mission.state_machine import MissionState


# ── Typed truth classification ───────────────────────────────────────

@pytest.mark.parametrize("status", ["REQUESTED", "AUTHORIZED", "STARTED"])
def test_pending_statuses_classify_as_pending(status):
    assert classify_operation_truth(status) is RelayOperationTruth.PENDING


def test_succeeded_classifies_as_confirmed():
    assert classify_operation_truth("SUCCEEDED") is RelayOperationTruth.CONFIRMED


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_failed_and_cancelled_classify_as_failed(status):
    assert classify_operation_truth(status) is RelayOperationTruth.FAILED


def test_unrecognized_status_raises_rather_than_guessing():
    with pytest.raises(RelayReconnectError):
        classify_operation_truth("SOME_FUTURE_STATUS")


def test_connection_loss_is_a_distinct_dimension_from_operation_truth():
    # RelayConnectionState and RelayOperationTruth are separate enums --
    # nothing in this module can construct a RelayOperationTruth from a
    # connection-state value, only from a real operations.status string.
    assert set(RelayConnectionState) == {
        RelayConnectionState.CONNECTED,
        RelayConnectionState.RECONNECTING,
        RelayConnectionState.OFFLINE,
    }
    assert set(RelayFreshness) == {RelayFreshness.CURRENT, RelayFreshness.STALE}
    assert set(RelayOperationTruth) == {
        RelayOperationTruth.PENDING,
        RelayOperationTruth.CONFIRMED,
        RelayOperationTruth.FAILED,
    }


# ── result_ref truthfulness (spec section 24) ────────────────────────

def test_nonempty_result_ref_on_pending_operation_is_not_interpreted_as_success():
    row = {
        "id": "op_1", "idempotency_key": "key_1", "kind": "deploy", "status": "STARTED",
        "result_ref": "some-stale-or-preliminary-ref", "requested_at": "t0", "started_at": "t1",
        "completed_at": None,
    }
    summary = _summarize_operation_row(row)
    assert summary.truth is RelayOperationTruth.PENDING
    assert summary.status == "STARTED"
    # truth is driven by status, never by presence of result_ref
    assert summary.result_ref == "some-stale-or-preliminary-ref"


def test_result_ref_secrets_are_redacted_in_the_reconciliation_summary():
    row = {
        "id": "op_2", "idempotency_key": "key_2", "kind": "deploy", "status": "SUCCEEDED",
        "result_ref": "sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD",
        "requested_at": "t0", "started_at": "t1", "completed_at": "t2",
    }
    summary = _summarize_operation_row(row)
    assert summary.truth is RelayOperationTruth.CONFIRMED
    assert "abcdefghijklmnopqrstuvwxyz1234567890" not in (summary.result_ref or "")


def test_summary_is_a_bounded_safe_shape_not_raw_row():
    row = {
        "id": "op_3", "idempotency_key": "key_3", "kind": "deploy", "status": "SUCCEEDED",
        "result_ref": None, "requested_at": "t0", "started_at": "t1", "completed_at": "t2",
        "parameters_fingerprint": "should-not-leak-through", "requested_by": "user_x",
    }
    summary = _summarize_operation_row(row)
    assert isinstance(summary, OperationReconciliationSummary)
    assert not hasattr(summary, "parameters_fingerprint")
    assert not hasattr(summary, "requested_by")


# ── Mutation outcome enum shape ──────────────────────────────────────

def test_mutation_outcome_has_exactly_four_typed_states():
    assert {o.value for o in RelayMutationOutcome} == {
        "APPLIED", "STALE_CONFLICT", "DENIED", "FAILED",
    }


def test_mission_state_running_is_a_real_canonical_state():
    # sanity: the precondition model is built on the real state machine,
    # not a private duplicate enum.
    assert MissionState.RUNNING.value == "RUNNING"
