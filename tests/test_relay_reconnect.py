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
    CachedRelayView,
    CheckpointCurrency,
    OperationReconciliationSummary,
    RelayMutationOutcome,
    RelayReconnectError,
    RelayConnectionState,
    RelayFreshness,
    RelayOperationTruth,
    RelayReconnectResult,
    RevisionCurrency,
    _classify_checkpoint_currency,
    _classify_revision_currency,
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


# ── Revision-currency pure classification (Phase 15.13.1) ────────────

def test_matching_expected_and_actual_revision_is_current():
    assert _classify_revision_currency("rev1", "rev1") is RevisionCurrency.CURRENT


def test_mismatched_revision_is_stale_conflict():
    assert _classify_revision_currency("rev1", "rev2") is RevisionCurrency.STALE_CONFLICT


def test_absent_actual_revision_is_never_silently_current():
    # None == None would otherwise coincidentally "match" -- must not
    # be treated as an honest currentness claim.
    assert _classify_revision_currency(None, None) is RevisionCurrency.STALE_CONFLICT
    assert _classify_revision_currency("rev1", None) is RevisionCurrency.STALE_CONFLICT


# ── Checkpoint-currency pure classification (Phase 15.13.1) ──────────

def test_matching_checkpoint_and_mission_revision_is_current():
    assert _classify_checkpoint_currency("rev1", "rev1") is CheckpointCurrency.CURRENT


def test_mismatched_checkpoint_revision_is_stale():
    assert _classify_checkpoint_currency("rev1", "rev2") is CheckpointCurrency.STALE


def test_absent_revision_on_either_side_fails_closed_to_stale():
    assert _classify_checkpoint_currency(None, "rev1") is CheckpointCurrency.STALE
    assert _classify_checkpoint_currency("rev1", None) is CheckpointCurrency.STALE
    assert _classify_checkpoint_currency(None, None) is CheckpointCurrency.STALE


# ── CachedRelayView client-side lifecycle (Phase 15.13.1) ────────────

def test_initial_view_is_offline_and_stale():
    view = CachedRelayView.initial()
    assert view.connection_state is RelayConnectionState.OFFLINE
    assert view.freshness is RelayFreshness.STALE


def test_connection_lost_marks_stale_even_if_previously_current():
    view = CachedRelayView(connection_state=RelayConnectionState.CONNECTED, freshness=RelayFreshness.CURRENT)
    view.mark_connection_lost()
    assert view.connection_state is RelayConnectionState.OFFLINE
    assert view.freshness is RelayFreshness.STALE


def test_begin_reconnecting_does_not_become_current_by_itself():
    view = CachedRelayView.initial()
    view.begin_reconnecting()
    assert view.connection_state is RelayConnectionState.RECONNECTING
    assert view.freshness is RelayFreshness.STALE  # attempting != succeeding


def test_successful_reconnect_applies_the_real_results_state():
    view = CachedRelayView.initial()
    view.begin_reconnecting()
    fake_result = RelayReconnectResult(
        relay_session_id="rlysess_x", mission_id="mis_x",
        connection_state=RelayConnectionState.CONNECTED, freshness=RelayFreshness.CURRENT,
        server_observed_at="2026-01-01T00:00:00+00:00", snapshot=None,  # type: ignore[arg-type]
        operations=(), warnings=(), requires_reauthentication=False,
    )
    view.apply_successful_reconnect(fake_result)
    assert view.connection_state is RelayConnectionState.CONNECTED
    assert view.freshness is RelayFreshness.CURRENT
    assert view.last_good_result is fake_result


def test_failed_reconnect_never_relabels_cached_data_current():
    view = CachedRelayView.initial()
    view.begin_reconnecting()
    view.record_failed_reconnect()
    assert view.connection_state is RelayConnectionState.OFFLINE
    assert view.freshness is RelayFreshness.STALE
