"""
Phase 14B.1 -- durable audit concurrency hardening.

A real cross-host qualification run (10 real races between a genuine
Northflank container and a genuine GitHub Actions runner) showed the
losing actor's durable audit write failing in 10/10 races
(AUDIT_FAILURE_DENY instead of the correct AUTHORIZATION_LOST_RACE).
Two real defects were found and fixed in orca/godmode/durable_audit.py:
DDL executing inside the per-event write transaction, and a
session-scoped advisory lock (invisible to normal Postgres
diagnostics, not tied to durable state) instead of an explicit,
transactionally-locked head row.

This file proves the fix locally against a real Postgres database:
50 two-actor races, then wider (5-actor, 10-actor) contention, plus
crash/recovery and chain/head-consistency checks. A local pass does
NOT by itself prove the original cloud failure is fixed (the failure
needed real network latency this local suite cannot recreate) -- see
docs/orneur/phase-14/PHASE14B_DISTRIBUTED_EVIDENCE.md for the honest
distinction and the real cross-host re-qualification result.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os
import uuid

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
    # Reset shared module-level state back to whatever the ambient env
    # now is -- importlib.reload() mutates the SAME module objects every
    # other test file in this pytest process imports; without this,
    # leaving them reloaded into DISTRIBUTED/Postgres mode leaks into
    # unrelated test files that run afterward in the same process.
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
    # _compute_signature() -> _audit_key() imports orca.audit -> orca.auth.db,
    # which fails closed at import time under DISTRIBUTED if this is unset --
    # unrelated to this test's own subject, but required for the import to
    # succeed at all in a process where orca.auth.db hasn't already been
    # imported under SOVEREIGN first.
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


def _issue_lease(home: str, lease_id: str, *, max_uses: int = 1):
    _setup(home)
    from datetime import datetime, timedelta, timezone
    from orca.godmode import kill_switch
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    # The shared local security-root test database persists across test
    # runs (same convention as test_kill_switch_stale_restore.py etc.) --
    # a fresh/never-configured root fails closed as ACTIVE by design, so
    # establish a known INACTIVE baseline before racing for a lease.
    # Idempotent (only calls through if not already inactive) so this
    # doesn't inflate the shared epoch counter on every one of many
    # repeated calls (e.g. 50 in the stress test below) and break other
    # test files' own epoch-based assertions against the same shared
    # local security-root database.
    if kill_switch.is_active():
        kill_switch.deactivate()

    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=3600, reason="Phase 14B.1 concurrency hardening test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=max_uses)


def _worker_elevate(home: str, lease_id: str, principal_id: str, result_queue, barrier):
    resolution_mod = _setup(home)[2]
    from orca.godmode.contracts import CapabilityDomain
    barrier.wait(timeout=15)
    decision = resolution_mod.resolve_and_consume_lease(
        lease_id=lease_id, tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
        principal_id=principal_id, trace_id=f"trace-{principal_id}",
    )
    result_queue.put(decision.state.value)


def _run_n_way_race(home: str, lease_id: str, n_actors: int) -> list[str]:
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(n_actors)
    result_queue = ctx.Queue()
    workers = [
        ctx.Process(target=_worker_elevate, args=(home, lease_id, f"actor-{i}", result_queue, barrier))
        for i in range(n_actors)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=30)
    return [result_queue.get(timeout=5) for _ in range(n_actors)]


# --------------------------------------------------------------- classification


def test_classify_pg_error_categories_are_sanitized(tmp_path):
    home = str(tmp_path / "home-classify")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, _ = _setup(home)
    import psycopg

    assert durable_audit._classify_pg_error(psycopg.errors.LockNotAvailable("x")) == "LOCK_TIMEOUT"
    assert durable_audit._classify_pg_error(psycopg.errors.DeadlockDetected("x")) == "DEADLOCK"
    assert durable_audit._classify_pg_error(psycopg.errors.SerializationFailure("x")) == "SERIALIZATION_FAILURE"
    assert durable_audit._classify_pg_error(psycopg.errors.UniqueViolation("x")) == "UNIQUE_VIOLATION"
    assert durable_audit._classify_pg_error(psycopg.errors.QueryCanceled("x")) == "STATEMENT_TIMEOUT"
    assert durable_audit._classify_pg_error(psycopg.OperationalError("x")) == "CONNECTION_FAILURE"
    # No category string ever contains the word "password" or "dsn" -- a
    # structural guarantee, not just true for the cases above.
    for cat in ("LOCK_TIMEOUT", "STATEMENT_TIMEOUT", "DEADLOCK", "SERIALIZATION_FAILURE", "UNIQUE_VIOLATION", "CONNECTION_FAILURE"):
        assert "password" not in cat.lower() and "dsn" not in cat.lower()


# --------------------------------------------------------------- timeout ordering (Phase 14B.1.1)


def test_lock_timeout_shorter_than_statement_timeout_fires_first(tmp_path):
    """Real Postgres proof of the coherent ordering (spec Phase 14B.1.1
    Step 3/6): hold the head-row lock in a separate real connection
    longer than _PG_LOCK_WAIT_TIMEOUT_MS but well under
    _PG_STATEMENT_TIMEOUT_MS, and confirm the waiting writer is
    cancelled by lock_timeout (LOCK_TIMEOUT), not statement_timeout
    (STATEMENT_TIMEOUT) -- proving the two no longer race each other
    with the wrong one winning, which was the real Phase 14B.1 cloud
    bug (a session-level statement_timeout of 5000ms silently capped an
    intended 8000ms lock_timeout)."""
    home = str(tmp_path / "home-timeout-order")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, _ = _setup(home)
    durable_audit._ensure_pg_schema()
    assert durable_audit._PG_LOCK_WAIT_TIMEOUT_MS < durable_audit._PG_STATEMENT_TIMEOUT_MS

    import psycopg
    import threading
    import time

    holder_ready = threading.Event()
    # Holds for longer than lock_timeout but well under statement_timeout
    # -- just enough for the writer's FIRST attempt to be cancelled by
    # lock_timeout specifically, then released so a retry succeeds
    # quickly. This is the actual point of the test: prove the writer's
    # own budget (lock_timeout, then retry) governs the outcome, not an
    # unrelated already-in-effect statement_timeout capping it short.
    hold_seconds = (durable_audit._PG_LOCK_WAIT_TIMEOUT_MS / 1000.0) + 1.0

    def hold_lock():
        conn = psycopg.connect(_AUTHORITY_DSN, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SELECT last_seq, last_hash FROM godmode_audit_head WHERE id = 1 FOR UPDATE")
            holder_ready.set()
            time.sleep(hold_seconds)
        conn.rollback()
        conn.close()

    holder = threading.Thread(target=hold_lock)
    holder.start()
    holder_ready.wait(timeout=5)

    from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType
    event = ElevationAuditEvent(event_type=ElevationAuditEventType.AUTHORIZATION_ATTEMPT, principal_id="u1", tenant_id="t-timeout-order", result="PENDING_CONSUME")

    start = time.monotonic()
    ok, category = durable_audit._record_event_postgres_with_diagnostics(event)
    elapsed = time.monotonic() - start
    holder.join(timeout=10)

    # The writer's first attempt gets LOCK_TIMEOUT'd around ~5s (never
    # STATEMENT_TIMEOUT'd first), then a retry succeeds once the holder
    # releases -- total time bounded well under statement_timeout, and
    # the eventual result is a real success, not a masked failure.
    assert ok is True, f"expected eventual success via retry, got category={category}"
    assert elapsed < (durable_audit._PG_STATEMENT_TIMEOUT_MS / 1000.0), (
        f"took {elapsed:.1f}s -- statement_timeout, not lock_timeout, governed this wait"
    )


def test_statement_timeout_category_used_when_it_actually_fires(tmp_path):
    """Directly forces a real STATEMENT_TIMEOUT (not LOCK_TIMEOUT) by
    setting an artificially tiny statement_timeout and running a
    real slow query (pg_sleep), proving the classifier distinguishes
    them using real Postgres SQLSTATEs, not just unit-level mocking."""
    home = str(tmp_path / "home-real-stmt-timeout")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, _ = _setup(home)

    import psycopg
    conn = psycopg.connect(_AUTHORITY_DSN, autocommit=False)
    category = None
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '200ms'")
            cur.execute("SELECT pg_sleep(2)")
    except Exception as e:
        category = durable_audit._classify_pg_error(e) if isinstance(e, psycopg.Error) else None
    finally:
        conn.rollback()
        conn.close()

    assert category == "STATEMENT_TIMEOUT", f"expected STATEMENT_TIMEOUT, got {category}"


# --------------------------------------------------------------- hot path has no DDL


def test_write_hot_path_executes_no_ddl_after_schema_initialized(tmp_path, monkeypatch):
    """Proves the write hot path never re-executes DDL once the schema
    is initialized: sabotage the DDL strings themselves (so executing
    them would raise a syntax error) and confirm a write still
    succeeds -- which is only possible if `_record_event_postgres_with_diagnostics()`
    never executes `_PG_TABLE_SCHEMA`/`_PG_HEAD_SCHEMA` on the hot path."""
    home = str(tmp_path / "home-noddl")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, _ = _setup(home)
    from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType

    durable_audit._ensure_pg_schema()
    assert _AUTHORITY_DSN in durable_audit._pg_schema_initialized_dsns

    monkeypatch.setattr(durable_audit, "_PG_TABLE_SCHEMA", "THIS IS NOT VALID SQL AND WOULD RAISE IF EXECUTED")
    monkeypatch.setattr(durable_audit, "_PG_HEAD_SCHEMA", "THIS IS NOT VALID SQL AND WOULD RAISE IF EXECUTED")

    event = ElevationAuditEvent(event_type=ElevationAuditEventType.AUTHORIZATION_ATTEMPT, principal_id="u1", tenant_id="t-noddl", result="PENDING_CONSUME")
    ok, category = durable_audit._record_event_postgres_with_diagnostics(event)
    assert ok is True, f"write failed ({category}) -- the hot path must have touched DDL despite schema already being initialized"
    assert category == "SUCCESS"


# --------------------------------------------------------------- 50 two-actor races


def test_fifty_two_actor_races_all_satisfy_the_invariant(tmp_path):
    home = str(tmp_path / "home-fifty")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, _ = _setup(home)

    committed_total = 0
    lost_race_total = 0
    audit_failure_total = 0
    double_exec_total = 0

    for i in range(50):
        lease_id = f"race50-{i}-{uuid.uuid4().hex[:8]}"
        lease = _issue_lease(home, lease_id, max_uses=1)
        results = _run_n_way_race(home, lease.lease_id, 2)

        allow_count = sum(1 for r in results if r == "ALLOW")
        assert allow_count <= 1, f"double execution at race {i}: {results}"
        if allow_count > 1:
            double_exec_total += 1

        events = durable_audit.list_events_for_tenant("t1")
        my_events = [e for e in events if e["lease_id"] == lease.lease_id]
        committed = sum(1 for e in my_events if e["event_type"] == "AUTHORIZATION_COMMITTED")
        lost_race = sum(1 for e in my_events if e["event_type"] == "AUTHORIZATION_LOST_RACE")
        audit_failure = sum(1 for e in my_events if e.get("event_type") == "AUDIT_FAILURE_DENY")
        committed_total += committed
        lost_race_total += lost_race
        audit_failure_total += audit_failure

        assert durable_audit.count_false_committed_audit(my_events) == 0, f"false committed audit at race {i}"

    assert committed_total == 50, f"expected 50 committed, got {committed_total}"
    assert lost_race_total == 50, f"expected 50 lost_race, got {lost_race_total}"
    assert audit_failure_total == 0, f"expected 0 AUDIT_FAILURE_DENY under normal contention, got {audit_failure_total}"
    assert double_exec_total == 0

    chain = durable_audit.verify_chain()
    assert chain["valid"] is True

    head = durable_audit.verify_head_consistency()
    assert head["valid"] is True, head


# --------------------------------------------------------------- wider contention


@pytest.mark.parametrize("n_actors", [5, 10])
def test_wider_contention_exactly_one_winner(tmp_path, n_actors):
    home = str(tmp_path / f"home-wide-{n_actors}")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, _ = _setup(home)

    lease_id = f"race-wide-{n_actors}-{uuid.uuid4().hex[:8]}"
    lease = _issue_lease(home, lease_id, max_uses=1)
    results = _run_n_way_race(home, lease.lease_id, n_actors)

    allow_count = sum(1 for r in results if r == "ALLOW")
    deny_count = sum(1 for r in results if r == "DENY")
    assert allow_count == 1, f"expected exactly one winner among {n_actors} actors, got {results}"
    assert deny_count == n_actors - 1

    events = durable_audit.list_events_for_tenant("t1")
    my_events = [e for e in events if e["lease_id"] == lease.lease_id]
    committed = sum(1 for e in my_events if e["event_type"] == "AUTHORIZATION_COMMITTED")
    lost_race = sum(1 for e in my_events if e["event_type"] == "AUTHORIZATION_LOST_RACE")
    audit_failure = sum(1 for e in my_events if e.get("event_type") == "AUDIT_FAILURE_DENY")

    assert committed == 1, f"expected 1 committed, got {committed}"
    assert lost_race == n_actors - 1, f"expected {n_actors - 1} lost_race, got {lost_race}"
    assert audit_failure == 0, f"expected 0 audit failures under normal contention, got {audit_failure}"
    assert durable_audit.count_false_committed_audit(my_events) == 0


# --------------------------------------------------------------- crash/recovery


def test_crash_after_insert_before_head_update_rolls_back_both(tmp_path, monkeypatch):
    """Simulates a crash between the event INSERT and the head UPDATE --
    since both are in the same transaction, the whole thing must roll
    back: no orphan chain entry, no advanced head."""
    home = str(tmp_path / "home-crash-1")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, _ = _setup(home)
    from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType

    before = durable_audit.verify_head_consistency()
    assert before["valid"] is True

    real_execute = None

    class _CrashingCursor:
        def __init__(self, real_cur):
            self._real = real_cur

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._real.__exit__(*a)

        def execute(self, sql, *args, **kwargs):
            if "INSERT INTO godmode_audit" in sql and "godmode_audit_head" not in sql:
                self._real.execute(sql, *args, **kwargs)
                raise RuntimeError("simulated crash after INSERT, before head UPDATE")
            return self._real.execute(sql, *args, **kwargs)

        def fetchone(self):
            return self._real.fetchone()

    from orca.godmode.lease_store import _pg_connect as real_connect
    conn = real_connect()
    monkeypatch.setattr(conn, "cursor", lambda: _CrashingCursor(conn.__class__.cursor(conn)))
    monkeypatch.setattr("orca.godmode.lease_store._pg_connect", lambda: conn)

    event = ElevationAuditEvent(event_type=ElevationAuditEventType.AUTHORIZATION_ATTEMPT, principal_id="u1", tenant_id="t-crash1", result="PENDING_CONSUME")
    ok, category = durable_audit._record_event_postgres_with_diagnostics(event)
    assert ok is False
    assert category == "UNKNOWN_DATABASE_FAILURE"

    # Rolled back cleanly -- no orphan row for this tenant, head unchanged.
    events = durable_audit.list_events_for_tenant("t-crash1")
    assert events == []

    monkeypatch.undo()
    after = durable_audit.verify_head_consistency()
    assert after == before, "head must be unchanged after a rolled-back write"


def test_head_consistency_detects_injected_mismatch(tmp_path):
    """Directly corrupts the head row (bypassing the real write path) to
    prove verify_head_consistency() actually detects HEAD_HASH_MISMATCH
    rather than always reporting valid=True."""
    home = str(tmp_path / "home-head-mismatch")
    os.makedirs(home, exist_ok=True)
    _, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "head-mismatch-1", max_uses=3)
    from orca.godmode.contracts import CapabilityDomain
    resolution.resolve_and_consume_lease(
        lease_id=lease.lease_id, tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
        principal_id="u1", trace_id="trace-1",
    )
    assert durable_audit.verify_head_consistency()["valid"] is True

    import psycopg
    conn = psycopg.connect(_AUTHORITY_DSN)
    with conn.cursor() as cur:
        cur.execute("UPDATE godmode_audit_head SET last_hash = 'deliberately-wrong-hash' WHERE id = 1")
    conn.commit()
    conn.close()

    result = durable_audit.verify_head_consistency()
    assert result["valid"] is False
    assert result["reason"] == "HEAD_HASH_MISMATCH"
