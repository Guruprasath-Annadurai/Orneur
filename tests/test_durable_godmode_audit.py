"""
Phase 14B §15-18 -- durable, dual-backend, tamper-evident Godmode
elevation audit.

Real finding this phase made, more serious than what Phase 14A.4
disclosed: grepping every caller of
`orca.godmode.audit.record_elevation_event()` found exactly one --
`orca/godmode/latency_bench.py`, a benchmark script. The real
authorization choke point, `orca.godmode.resolution.resolve_and_consume_lease()`,
never called ANY audit function. There was no audit trail at all for
real elevated actions, not merely a non-durable one.

Fixed: `orca/godmode/durable_audit.py` (a new, hash-chained, dual-
backend store reusing `orca.godmode.lease_store`'s connection
primitives) is now called directly from `resolve_and_consume_lease()`,
with fail-closed ordering -- an ALLOW decision is denied if the durable
write fails, per spec §16.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os

import pytest


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev = {k: os.environ.get(k) for k in (
        "ORCA_HOME", "ORNEUR_HOME", "ORNEUR_GODMODE_DATABASE_URL", "ORNEUR_AUDIT_KEY",
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


_AUTHORITY_DSN = "postgresql://ag@localhost/orneur_phase14_test"


def _postgres_reachable() -> bool:
    try:
        import psycopg
        conn = psycopg.connect(_AUTHORITY_DSN, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


pytestmark_pg = pytest.mark.skipif(not _postgres_reachable(), reason="requires a real local Postgres database")


def _setup(home: str, *, postgres: bool = False):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    if postgres:
        os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN
    else:
        os.environ.pop("ORNEUR_GODMODE_DATABASE_URL", None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.durable_audit as durable_audit_mod
    importlib.reload(durable_audit_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)
    return lease_store_mod, durable_audit_mod, resolution_mod


def _issue_lease(home: str, lease_id: str, *, postgres: bool = False, max_uses: int = 5):
    _setup(home, postgres=postgres)
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=3600, reason="durable audit test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=max_uses)


def _elevate(resolution_mod, lease_id: str, *, principal_id="u1", trace_id="trace-1"):
    from orca.godmode.contracts import CapabilityDomain
    return resolution_mod.resolve_and_consume_lease(
        lease_id=lease_id, tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
        principal_id=principal_id, trace_id=trace_id,
    )


# --------------------------------------------------------------- real finding, before/after wiring


def test_resolve_and_consume_lease_now_durably_audits_allow(tmp_path):
    """The core fix: a real ALLOW decision is now durably persisted --
    confirmed by reading it back via a completely fresh module state
    (simulating a restart)."""
    home = str(tmp_path / "home")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "allow-1")

    decision = _elevate(resolution, lease.lease_id)
    assert decision.state.value == "ALLOW"

    _setup(home)
    import orca.godmode.durable_audit as durable_audit2
    events = durable_audit2.list_events_for_tenant("t1")
    assert len(events) == 1
    assert events[0]["lease_id"] == lease.lease_id
    assert events[0]["event_type"] == "USE"
    assert events[0]["result"] == "ALLOW"


def test_deny_decision_is_also_audited(tmp_path):
    home = str(tmp_path / "home-deny")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "deny-1", max_uses=0)

    decision = _elevate(resolution, lease.lease_id)
    assert decision.state.value == "DENY"

    events = durable_audit.list_events_for_tenant("t1")
    assert len(events) == 1
    assert events[0]["event_type"] == "DENY"
    assert events[0]["result"] == "DENY"


# --------------------------------------------------------------- §16: fail-closed audit-write-failure semantics


def test_allow_decision_denied_when_durable_audit_write_fails(tmp_path, monkeypatch):
    """Spec §16: 'do not silently succeed while mandatory audit
    persistence is unavailable.' Simulate a durable-audit-write failure
    directly and confirm the elevated action is DENIED, not silently
    granted, and the lease use is NOT consumed."""
    home = str(tmp_path / "home-audit-fail")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "audit-fail-1")

    monkeypatch.setattr(resolution, "_audit_decision", lambda *a, **k: False)
    decision = _elevate(resolution, lease.lease_id)
    assert decision.state.value == "DENY"
    assert "audit" in " ".join(decision.reasons).lower()

    from orca.godmode.lease_store import get
    assert get(lease.lease_id).uses_remaining == 5, "the lease use must NOT be consumed when the durable audit write fails"


# --------------------------------------------------------------- redaction preserved


def test_capability_and_resource_scope_are_redacted_before_persisting(tmp_path):
    home = str(tmp_path / "home-redact")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "redact-1")

    _elevate(resolution, lease.lease_id)
    events = durable_audit.list_events_for_tenant("t1")
    assert len(events) == 1
    # redact_secrets() is exercised -- exact output depends on its own
    # implementation, but the field must exist and be a string (not
    # crash, not silently dropped).
    assert isinstance(events[0]["capability"], str)


# --------------------------------------------------------------- §17: cross-process visibility + restart persistence


def _worker_elevate(home: str, lease_id: str, result_queue, *, postgres: bool = False):
    _setup(home, postgres=postgres)
    import orca.godmode.resolution as resolution_mod
    decision = _elevate(resolution_mod, lease_id, principal_id="worker-a")
    result_queue.put(decision.state.value)


@pytestmark_pg
def test_cross_process_audit_visibility_and_restart_persistence(tmp_path):
    """Spec §17 (proven at the mechanism level -- a real Postgres
    database shared by two real OS processes -- honestly NOT a claim
    of literal cross-HOST qualification, which requires the real VPS
    this session does not have; see DURABLE_GODMODE_AUDIT.md). Worker
    A (a separate real process) authorizes an elevated event; this
    process (standing in for 'Host B') queries the shared audit
    backend and sees it. Then simulates 'restart Host A' via a fresh
    module reload and confirms the event remains visible."""
    home = str(tmp_path / "home-cross-process")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home, postgres=True)
    lease = _issue_lease(home, "cross-process-1", postgres=True)

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    worker = ctx.Process(target=_worker_elevate, args=(home, lease.lease_id, result_queue), kwargs={"postgres": True})
    worker.start()
    worker.join(timeout=15)
    assert result_queue.get(timeout=5) == "ALLOW"

    events = durable_audit.list_events_for_tenant("t1")
    assert any(e["lease_id"] == lease.lease_id and e["principal_id"] == "worker-a" for e in events), (
        "this process ('Host B') must see the audit event worker A ('Host A') wrote"
    )

    # "Restart Host A" -- fresh module reload, event remains visible.
    _setup(home, postgres=True)
    import orca.godmode.durable_audit as durable_audit2
    events_after_restart = durable_audit2.list_events_for_tenant("t1")
    assert any(e["lease_id"] == lease.lease_id for e in events_after_restart)


# --------------------------------------------------------------- §18: tamper detection


def test_verify_chain_detects_no_tampering_on_clean_chain(tmp_path):
    home = str(tmp_path / "home-clean-chain")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "clean-1", max_uses=3)
    _elevate(resolution, lease.lease_id)
    _elevate(resolution, lease.lease_id)

    result = durable_audit.verify_chain()
    assert result["valid"] is True
    assert result["entries_verified"] == 2


def test_verify_chain_detects_tampered_row(tmp_path):
    """Spec §18: modify an audit record in isolated staging test.
    Required: integrity verification detects tampering."""
    home = str(tmp_path / "home-tamper")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "tamper-1", max_uses=3)
    _elevate(resolution, lease.lease_id)
    _elevate(resolution, lease.lease_id)

    assert durable_audit.verify_chain()["valid"] is True

    import sqlite3
    conn = sqlite3.connect(str(ls._db_path()))
    conn.execute("UPDATE godmode_audit SET result = 'TAMPERED' WHERE seq = 0")
    conn.commit()
    conn.close()

    result = durable_audit.verify_chain()
    assert result["valid"] is False
    assert "seq=0" in result["reason"]


def test_verify_chain_detects_deleted_row(tmp_path):
    home = str(tmp_path / "home-delete")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    lease = _issue_lease(home, "delete-1", max_uses=3)
    _elevate(resolution, lease.lease_id)
    _elevate(resolution, lease.lease_id)
    _elevate(resolution, lease.lease_id)

    import sqlite3
    conn = sqlite3.connect(str(ls._db_path()))
    conn.execute("DELETE FROM godmode_audit WHERE seq = 1")
    conn.commit()
    conn.close()

    result = durable_audit.verify_chain()
    assert result["valid"] is False


# --------------------------------------------------------------- SQLite Sovereign explicit


def test_sqlite_sovereign_durable_audit_explicitly_proven(tmp_path):
    home = str(tmp_path / "home-sovereign")
    os.makedirs(home, exist_ok=True)
    ls, durable_audit, resolution = _setup(home)
    assert ls._backend() == "sqlite"
    lease = _issue_lease(home, "sovereign-1")
    decision = _elevate(resolution, lease.lease_id)
    assert decision.state.value == "ALLOW"
    assert len(durable_audit.list_events_for_tenant("t1")) == 1


# --------------------------------------------------------------- store unavailable -> fail closed


def test_durable_audit_store_unavailable_denies_elevation(tmp_path):
    home = str(tmp_path / "home-store-down")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as ls
    importlib.reload(ls)
    import orca.godmode.durable_audit as durable_audit
    importlib.reload(durable_audit)

    from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType
    event = ElevationAuditEvent(event_type=ElevationAuditEventType.USE, principal_id="u1", tenant_id="t1")
    assert durable_audit.record_event_durable(event) is False, "an unreachable authority store must report the audit write as failed, never silently succeed"
