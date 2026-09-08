"""
Phase 15.5 -- orca.mission.authority_bridge tests.

These are REAL integration tests against orca.godmode's actual
authority engine (SQLite-backed locally, via the LEASE_DIR isolation
already provided by tests/conftest.py's autouse fixture) -- not
mocked. The same code path (issue_operation_lease ->
consume_operation_lease -> resolve_and_consume_lease) is exercised
against real Neon-backed Postgres in
tests/test_operation_store_live_neon.py; this file proves the bridge
itself is correct without needing live Neon.
"""
from __future__ import annotations

import uuid

import pytest

from orca.godmode.contracts import ElevatedPolicyDecisionState
from orca.mission.authority_bridge import consume_operation_lease, issue_operation_lease


def _op_id() -> str:
    return f"op_{uuid.uuid4().hex[:10]}"


def test_valid_lease_is_consumed_with_allow():
    op_id = _op_id()
    lease = issue_operation_lease(
        operation_id=op_id, operation_kind="deploy", tenant_id="tenant_1",
        requested_by="user_alice", approved_by="user_bob", reason="test",
    )
    decision = consume_operation_lease(
        lease_id=lease.lease_id, operation_id=op_id, operation_kind="deploy",
        tenant_id="tenant_1", requested_by="user_alice",
    )
    assert decision.state == ElevatedPolicyDecisionState.ALLOW


def test_lease_is_single_use():
    op_id = _op_id()
    lease = issue_operation_lease(
        operation_id=op_id, operation_kind="deploy", tenant_id="tenant_1",
        requested_by="user_alice", approved_by="user_bob", reason="test",
    )
    first = consume_operation_lease(
        lease_id=lease.lease_id, operation_id=op_id, operation_kind="deploy",
        tenant_id="tenant_1", requested_by="user_alice",
    )
    assert first.state == ElevatedPolicyDecisionState.ALLOW

    second = consume_operation_lease(
        lease_id=lease.lease_id, operation_id=op_id, operation_kind="deploy",
        tenant_id="tenant_1", requested_by="user_alice",
    )
    assert second.state != ElevatedPolicyDecisionState.ALLOW


def test_lease_for_operation_a_does_not_authorize_operation_b():
    """The real mechanism behind spec section 6.I: a lease is scoped
    to exactly one operation id -- attempting to consume it against a
    DIFFERENT operation id fails scope matching."""
    op_a = _op_id()
    op_b = _op_id()
    lease = issue_operation_lease(
        operation_id=op_a, operation_kind="deploy", tenant_id="tenant_1",
        requested_by="user_alice", approved_by="user_bob", reason="test",
    )
    decision = consume_operation_lease(
        lease_id=lease.lease_id, operation_id=op_b, operation_kind="deploy",
        tenant_id="tenant_1", requested_by="user_alice",
    )
    assert decision.state != ElevatedPolicyDecisionState.ALLOW
    assert any("scope mismatch" in r for r in decision.reasons)


def test_wrong_tenant_denied():
    op_id = _op_id()
    lease = issue_operation_lease(
        operation_id=op_id, operation_kind="deploy", tenant_id="tenant_1",
        requested_by="user_alice", approved_by="user_bob", reason="test",
    )
    decision = consume_operation_lease(
        lease_id=lease.lease_id, operation_id=op_id, operation_kind="deploy",
        tenant_id="tenant_OTHER", requested_by="user_alice",
    )
    assert decision.state != ElevatedPolicyDecisionState.ALLOW


def test_nonexistent_lease_denied():
    op_id = _op_id()
    decision = consume_operation_lease(
        lease_id="lease-does-not-exist", operation_id=op_id, operation_kind="deploy",
        tenant_id="tenant_1", requested_by="user_alice",
    )
    assert decision.state != ElevatedPolicyDecisionState.ALLOW


def test_wildcard_kind_rejected_at_issuance():
    """orca.godmode.issuance.issue_lease() itself rejects wildcard
    scopes -- confirms the bridge doesn't accidentally construct one."""
    from orca.godmode.contracts import LeaseIssuanceError

    op_id = _op_id()
    with pytest.raises(LeaseIssuanceError):
        issue_operation_lease(
            operation_id=op_id, operation_kind="*", tenant_id="tenant_1",
            requested_by="user_alice", approved_by="user_bob", reason="test",
        )
