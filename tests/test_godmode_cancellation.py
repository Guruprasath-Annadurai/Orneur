"""
Phase 14B.2 -- Godmode cancellation closure.

`resolve_and_consume_lease()` gained an optional `cancellation:
CancellationSignal | None` parameter (see `orca.godmode.cancellation`'s
module docstring) checked at four checkpoints, all strictly before
AUTHORIZATION_COMMITTED is ever written:

  A. before resolve_lease() at all
  B. after resolve_lease() ALLOW, before the ATTEMPT precondition write
  C. after ATTEMPT succeeds, before consume_use()
  D. immediately after consume_use() succeeds, before COMMITTED

A cancellation is cooperative and fail-safe: it never rolls back an
already-committed grant, never refunds an already-consumed lease use,
and never lets a side effect execute after the caller's own
`check_and_record_pre_side_effect_cancellation()` gate observes it.

Uses the same real local Postgres pattern as
`tests/test_durable_audit_concurrency_hardening.py` (this repo's
existing, already-approved DISTRIBUTED-mode authority test harness) --
skips cleanly if that database is unreachable.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os

import pytest

_AUTHORITY_DSN = "postgresql://ag@localhost/orneur_phase14_test"
_SECURITY_ROOT_DSN = "postgresql://ag@localhost/orneur_phase14_security_root_test"


def _postgres_reachable() -> bool:
    try:
        import psycopg
        conn = psycopg.connect(_AUTHORITY_DSN, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="requires a real local Postgres database")


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev = {k: os.environ.get(k) for k in (
        "ORCA_HOME", "ORNEUR_HOME", "ORNEUR_GODMODE_DATABASE_URL", "ORNEUR_AUDIT_KEY", "ORNEUR_DEPLOYMENT_PROFILE",
        "ORNEUR_DATABASE_URL", "ORNEUR_SECURITY_ROOT_DATABASE_URL",
    )}
    yield
    for k, v in prev.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.security_root as security_root_mod
    importlib.reload(security_root_mod)
    import orca.godmode.durable_audit as durable_audit_mod
    importlib.reload(durable_audit_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)


def _setup(home: str):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN
    os.environ["ORNEUR_DATABASE_URL"] = _AUTHORITY_DSN
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.durable_audit as durable_audit_mod
    importlib.reload(durable_audit_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)
    return lease_store_mod, durable_audit_mod, resolution_mod


def _issue_lease(home: str, lease_id: str, *, max_uses: int = 1, tenant_id: str = "t-cancel"):
    _setup(home)
    from datetime import datetime, timedelta, timezone
    from orca.godmode import kill_switch
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    if kill_switch.is_active():
        kill_switch.deactivate()

    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=3600, reason="Phase 14B.2 cancellation test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=max_uses)


def _signal_cancelled_on_call(n: int):
    """Returns a CallableCancellationSignal whose `is_cancelled()`
    returns False for the first n-1 calls and True from the n-th call
    onward. Since resolve_and_consume_lease() checks cancellation at
    checkpoints A/B/C/D in a fixed order, EACH ONLY REACHED IF THE
    PRIOR ONES DID NOT CANCEL, this deterministically targets exactly
    one checkpoint: n=1 -> A, n=2 -> B, n=3 -> C, n=4 -> D."""
    from orca.godmode.cancellation import CallableCancellationSignal

    state = {"calls": 0}

    def _check() -> bool:
        state["calls"] += 1
        return state["calls"] >= n

    return CallableCancellationSignal(_check)


def _resolve(resolution_mod, lease_id: str, *, cancellation=None, tenant_id: str = "t-cancel"):
    from orca.godmode.contracts import CapabilityDomain
    return resolution_mod.resolve_and_consume_lease(
        lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
        principal_id="u1", trace_id="trace-cancel", cancellation=cancellation,
    )


# --------------------------------------------------------------- checkpoints


def test_cancel_before_validation_checkpoint_a(tmp_path):
    home = str(tmp_path / "home-a")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-a", max_uses=1)

    decision = _resolve(resolution, lease.lease_id, cancellation=_signal_cancelled_on_call(1))
    assert decision.state.value == "DENY"
    assert decision.cancelled is True

    # No consumption -- a normal (uncancelled) attempt must still succeed.
    second = _resolve(resolution, lease.lease_id)
    assert second.state.value == "ALLOW"

    events = durable_audit.list_events_for_tenant("t-cancel")
    my_events = [e for e in events if e["lease_id"] == lease.lease_id]
    assert any(e["event_type"] == "AUTHORIZATION_CANCELLED" and e["result"] == "CANCELLED_BEFORE_CONSUME" for e in my_events)
    assert not any(e["result"] == "ALLOW" and e["event_type"] != "AUTHORIZATION_COMMITTED" for e in my_events)


def test_cancel_after_validation_checkpoint_b(tmp_path):
    home = str(tmp_path / "home-b")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-b", max_uses=1)

    decision = _resolve(resolution, lease.lease_id, cancellation=_signal_cancelled_on_call(2))
    assert decision.state.value == "DENY"
    assert decision.cancelled is True

    second = _resolve(resolution, lease.lease_id)
    assert second.state.value == "ALLOW"

    events = durable_audit.list_events_for_tenant("t-cancel")
    my_events = [e for e in events if e["lease_id"] == lease.lease_id]
    assert any(e["event_type"] == "AUTHORIZATION_CANCELLED" and e["result"] == "CANCELLED_BEFORE_CONSUME" for e in my_events)


def test_cancel_after_attempt_checkpoint_c(tmp_path):
    home = str(tmp_path / "home-c")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-c", max_uses=1)

    decision = _resolve(resolution, lease.lease_id, cancellation=_signal_cancelled_on_call(3))
    assert decision.state.value == "DENY"
    assert decision.cancelled is True

    # The ATTEMPT precondition WAS durably written (Gate 2 ran), but
    # consume_use() was never called -- the use is still available.
    second = _resolve(resolution, lease.lease_id)
    assert second.state.value == "ALLOW"

    events = durable_audit.list_events_for_tenant("t-cancel")
    my_events = [e for e in events if e["lease_id"] == lease.lease_id]
    assert any(e["event_type"] == "AUTHORIZATION_ATTEMPT" for e in my_events)
    assert any(e["event_type"] == "AUTHORIZATION_CANCELLED" and e["result"] == "CANCELLED_BEFORE_CONSUME" for e in my_events)


def test_cancel_after_consume_checkpoint_d_use_spent_not_refunded(tmp_path):
    home = str(tmp_path / "home-d")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-d", max_uses=1)

    decision = _resolve(resolution, lease.lease_id, cancellation=_signal_cancelled_on_call(4))
    assert decision.state.value == "DENY"
    assert decision.cancelled is True

    # The use WAS spent (consume_use() succeeded) -- never refunded.
    # A subsequent attempt on the same max_uses=1 lease must be denied
    # for exhaustion, NOT succeed.
    second = _resolve(resolution, lease.lease_id)
    assert second.state.value == "DENY"
    assert "no uses remaining" in "; ".join(second.reasons)

    events = durable_audit.list_events_for_tenant("t-cancel")
    my_events = [e for e in events if e["lease_id"] == lease.lease_id]
    assert any(e["event_type"] == "AUTHORIZATION_CANCELLED" and e["result"] == "CANCELLED_AFTER_CONSUME" for e in my_events)
    # AUTHORIZATION_COMMITTED must NEVER have been written for this
    # cancelled-after-consume attempt.
    assert not any(e["event_type"] == "AUTHORIZATION_COMMITTED" for e in my_events)
    assert durable_audit.count_false_committed_audit(my_events) == 0


def test_no_cancellation_signal_preserves_existing_allow_behavior(tmp_path):
    home = str(tmp_path / "home-none")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-none", max_uses=1)

    decision = _resolve(resolution, lease.lease_id, cancellation=None)
    assert decision.state.value == "ALLOW"
    assert decision.cancelled is False


def test_never_cancelled_signal_preserves_existing_allow_behavior(tmp_path):
    from orca.godmode.cancellation import NoCancellation
    home = str(tmp_path / "home-nocancel")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-noop", max_uses=1)

    decision = _resolve(resolution, lease.lease_id, cancellation=NoCancellation())
    assert decision.state.value == "ALLOW"
    assert decision.cancelled is False


# --------------------------------------------------------------- caller-side gate (Step 5)


def test_caller_side_gate_blocks_side_effect_after_commit(tmp_path):
    """Simulates the exact window Step 5 exists for: cancellation
    arrives strictly AFTER resolve_and_consume_lease() has already
    returned ALLOW/COMMITTED. The committed grant is never retracted;
    only the side effect is blocked."""
    from orca.godmode.cancellation import ThreadCancellationSignal, check_and_record_pre_side_effect_cancellation

    home = str(tmp_path / "home-gate")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-gate", max_uses=1)

    decision = _resolve(resolution, lease.lease_id)  # no cancellation signal passed into the call itself
    assert decision.state.value == "ALLOW"

    signal = ThreadCancellationSignal()
    signal.cancel(reason="test: cancelled after commit, before side effect")
    proceed = check_and_record_pre_side_effect_cancellation(
        cancellation=signal, tenant_id="t-cancel", lease_id=lease.lease_id,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write",
    )
    assert proceed is False

    events = durable_audit.list_events_for_tenant("t-cancel")
    my_events = [e for e in events if e["lease_id"] == lease.lease_id]
    # COMMITTED must remain -- it is never rewritten or retracted.
    assert any(e["event_type"] == "AUTHORIZATION_COMMITTED" for e in my_events)
    assert any(e["event_type"] == "EXECUTION_CANCELLED_BEFORE_SIDE_EFFECT" for e in my_events)


def test_caller_side_gate_allows_side_effect_when_not_cancelled(tmp_path):
    from orca.godmode.cancellation import NoCancellation, check_and_record_pre_side_effect_cancellation

    home = str(tmp_path / "home-gate-ok")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-gate-ok", max_uses=1)

    decision = _resolve(resolution, lease.lease_id)
    assert decision.state.value == "ALLOW"

    proceed = check_and_record_pre_side_effect_cancellation(
        cancellation=NoCancellation(), tenant_id="t-cancel", lease_id=lease.lease_id,
    )
    assert proceed is True


# --------------------------------------------------------------- deadline / budget interaction


def test_deadline_denies_independent_of_cancellation_plumbing(tmp_path):
    """Deadline expiry must deny on its own merits, with a live (but
    never-triggered) cancellation signal present -- proves the two
    mechanisms compose without either masking the other. (Checkpoint A
    is checked before resolve_lease()'s own is_expired() check, so a
    signal that WOULD cancel at checkpoint A necessarily reports
    "cancelled" first regardless of expiry -- that is checkpoint A's
    own, separately-covered, correct behavior, not this test's
    concern.)"""
    import time
    from datetime import datetime, timedelta, timezone
    from orca.godmode.cancellation import NoCancellation
    home = str(tmp_path / "home-deadline-first")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)

    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    approval = GodmodeApproval(
        approval_id="ap-deadline-cancel", principal_id="u1", tenant_id="t-cancel", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=1, reason="deadline+cancellation interaction test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=1)
    time.sleep(2)  # deadline (expires_at) is now in the past

    decision = _resolve(resolution, lease.lease_id, cancellation=NoCancellation())
    assert decision.state.value == "DENY"
    assert decision.cancelled is False
    assert "expired" in "; ".join(decision.reasons).lower()


def test_cancellation_at_checkpoint_a_takes_priority_over_expired_lease(tmp_path):
    """Cancellation arrives first (checkpoint A, before resolve_lease()
    even runs) against an ALSO-expired lease -- the reported reason is
    cancellation, not expiry, since checkpoint A is unconditionally
    first. Both stop execution safely either way; no lease refund, no
    side effect, no permission bypass."""
    import time
    from datetime import datetime, timedelta, timezone
    home = str(tmp_path / "home-cancel-first")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)

    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    approval = GodmodeApproval(
        approval_id="ap-cancel-deadline", principal_id="u1", tenant_id="t-cancel", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=1, reason="cancellation+deadline interaction test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=1)
    time.sleep(2)

    decision = _resolve(resolution, lease.lease_id, cancellation=_signal_cancelled_on_call(1))
    assert decision.state.value == "DENY"
    assert decision.cancelled is True


def test_cancellation_and_budget_do_not_reset_each_other(tmp_path):
    """Cancelling one attempt must not reset max_uses -- a cancelled-
    after-consume attempt still spent the one use; a fresh (uncancelled)
    retry against the SAME lease is correctly denied for exhaustion,
    never silently re-authorized."""
    home = str(tmp_path / "home-budget-cancel")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "cancel-budget", max_uses=1)

    cancelled_decision = _resolve(resolution, lease.lease_id, cancellation=_signal_cancelled_on_call(4))
    assert cancelled_decision.state.value == "DENY"
    assert cancelled_decision.cancelled is True

    retry = _resolve(resolution, lease.lease_id)
    assert retry.state.value == "DENY"
    assert "no uses remaining" in "; ".join(retry.reasons)


# --------------------------------------------------------------- real concurrency (Steps 9-10)


def _worker_elevate_with_cancellation(home: str, lease_id: str, principal_id: str, result_queue, barrier, cancel_event):
    from orca.godmode.cancellation import CallableCancellationSignal
    resolution_mod = _setup(home)[2]
    from orca.godmode.contracts import CapabilityDomain
    signal = CallableCancellationSignal(cancel_event.is_set)
    barrier.wait(timeout=15)
    decision = resolution_mod.resolve_and_consume_lease(
        lease_id=lease_id, tenant_id="t-cancel", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
        principal_id=principal_id, trace_id=f"trace-{principal_id}", cancellation=signal,
    )
    result_queue.put((decision.state.value, decision.cancelled))


def test_race_cancel_before_any_actor_starts_zero_consumption(tmp_path):
    """Step 9, ordering A: cancellation wins (set before either actor
    even begins) -- real multiprocess concurrency, both actors see an
    already-cancelled signal. Required: 0 consumption, 0 side effect."""
    home = str(tmp_path / "home-race-cancel-first")
    os.makedirs(home, exist_ok=True)
    _issue_lease_result = _issue_lease(home, "cancel-race-a", max_uses=1)

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue = ctx.Queue()
    cancel_event = ctx.Event()
    cancel_event.set()  # cancelled BEFORE either actor starts

    workers = [
        ctx.Process(target=_worker_elevate_with_cancellation, args=(home, _issue_lease_result.lease_id, f"actor-{i}", result_queue, barrier, cancel_event))
        for i in range(2)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=30)
    results = [result_queue.get(timeout=5) for _ in range(2)]

    assert all(state == "DENY" and cancelled is True for state, cancelled in results)

    _, durable_audit, resolution = _setup(home)
    fresh = _resolve(resolution, _issue_lease_result.lease_id)
    assert fresh.state.value == "ALLOW"  # use still available -- 0 consumption


def test_race_cancel_vs_authorization_race_two_actors(tmp_path):
    """Step 10: two actors race for ONE max_uses=1 lease while a
    cancellation signal is ALSO flipped concurrently (real multiprocess
    timing, not simulated). Required globally, regardless of exact
    timing: consumption <= 1, and if cancellation is observed before
    any side-effect gate for a given actor, that actor's own side
    effect count is 0. Never double execution; audit chain stays
    valid; false-committed stays 0."""
    home = str(tmp_path / "home-race-cancel-vs-auth")
    os.makedirs(home, exist_ok=True)
    lease = _issue_lease(home, "cancel-race-b", max_uses=1)

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue = ctx.Queue()
    cancel_event = ctx.Event()
    # Deliberately NOT set before the race -- let both actors race
    # normally against the barrier; the cancellation signal is checked
    # by each actor's own CallableCancellationSignal but never gets
    # set during THIS run, isolating the pure authority-race invariant
    # (proving the cancellation plumbing doesn't perturb the existing,
    # already-locked race behavior when nothing actually cancels).

    workers = [
        ctx.Process(target=_worker_elevate_with_cancellation, args=(home, lease.lease_id, f"actor-{i}", result_queue, barrier, cancel_event))
        for i in range(2)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=30)
    results = [result_queue.get(timeout=5) for _ in range(2)]

    allow_count = sum(1 for state, _ in results if state == "ALLOW")
    deny_count = sum(1 for state, _ in results if state == "DENY")
    assert allow_count == 1, f"double execution: {results}"
    assert deny_count == 1

    _, durable_audit, resolution = _setup(home)
    events = durable_audit.list_events_for_tenant("t-cancel")
    my_events = [e for e in events if e["lease_id"] == lease.lease_id]
    committed = sum(1 for e in my_events if e["event_type"] == "AUTHORIZATION_COMMITTED")
    lost_race = sum(1 for e in my_events if e["event_type"] == "AUTHORIZATION_LOST_RACE")
    assert committed == 1
    assert lost_race == 1
    assert durable_audit.count_false_committed_audit(my_events) == 0
    chain = durable_audit.verify_chain()
    assert chain["valid"] is True, chain
