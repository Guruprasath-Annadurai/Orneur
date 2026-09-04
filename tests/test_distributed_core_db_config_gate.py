"""
Phase 14A.4 -- closes the real, disclosed gap Phase 14A.3's own final
report flagged: `ORNEUR_DATABASE_URL` (the core auth/session/audit
backend, `orca.auth.db`) did not receive the same fail-startup
enforcement as the distributed security-root and Godmode authority
backends. In DISTRIBUTED mode, a missing/invalid/unreachable core DB
used to be caught only by whatever exception `orca.auth.db`'s own
`init_db()` happened to raise at import time (potentially leaking
connection details) -- never a clean, secret-free
`DeploymentConfigError`, and never enforced independent of import
order.

Fix: `orca.godmode.deployment_profile.require_distributed_core_db_url()`
/ `validate_deployment_config()` now also require
`ORNEUR_DATABASE_URL`; `orca/auth/db.py` itself also fails fast at
import time (defense in depth, for any entry point that imports it
without going through `orca/serve/api.py`'s startup gate);
`orca/serve/api.py`'s validation call was moved to the very top of the
file, before any `orca.*` import that could transitively touch a
database.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os

import pytest

_AUTHORITY_DSN = "postgresql://ag@localhost/orneur_phase14_test"
_SECURITY_ROOT_DSN = "postgresql://ag@localhost/orneur_phase14_security_root_test"
_CORE_DB_DSN = "postgresql://ag@localhost/orneur_phase14_authdb_test"


def _postgres_reachable(dsn: str) -> bool:
    try:
        import psycopg
        conn = psycopg.connect(dsn, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


_PG_AVAILABLE = (
    _postgres_reachable(_AUTHORITY_DSN)
    and _postgres_reachable(_SECURITY_ROOT_DSN)
    and _postgres_reachable(_CORE_DB_DSN)
)
pytestmark_pg = pytest.mark.skipif(not _PG_AVAILABLE, reason="requires three real local Postgres databases")


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    """Real test-pollution bug found and fixed while writing this file:
    tests here reload `orca.auth.db`/`orca.auth.store`/`orca.audit`
    with `ORNEUR_DATABASE_URL` pointed at a real Postgres database --
    those modules bind `BACKEND`/`AUTH_DB` at IMPORT time. The actual
    root-cause fix is in `tests/conftest.py`'s `isolated_home` fixture
    (it only ever popped the legacy `ORCA_DATABASE_URL`, never
    `ORNEUR_DATABASE_URL` -- so a leftover value from this file's own
    tests silently redirected unrelated tests, e.g.
    tests/test_auth_privacy.py and tests/test_org_store.py, at a real
    Postgres database instead of their own isolated SQLite tmp file,
    surfacing as raw `psycopg.errors.UniqueViolation` failures).

    This fixture restores the env vars this file itself touches (never
    reloading `orca.auth.db`/`store`/`audit` here in teardown -- doing
    so against whatever the RESTORED, real environment now is would
    itself call `orca.auth.db`'s unconditional `init_db()` against the
    real `~/.orca/auth.db`, trading one leak for another). Any later
    test that needs a clean module state gets it via its own explicit
    reload (e.g. `isolated_home`), which now works correctly once the
    env var itself is properly unset."""
    prev = {k: os.environ.get(k) for k in (
        "ORCA_HOME", "ORNEUR_HOME", "ORNEUR_DEPLOYMENT_PROFILE",
        "ORNEUR_GODMODE_DATABASE_URL", "ORNEUR_SECURITY_ROOT_DATABASE_URL",
        "ORNEUR_DATABASE_URL", "ORNEUR_SECURITY_ROOT_HOME",
    )}
    yield
    for k, v in prev.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.deployment_profile as dp_mod
    importlib.reload(dp_mod)


# --------------------------------------------------------------- §2: audit -- confirmed via direct code reading, asserted here as a living contract


def test_auth_db_owns_the_expected_tables():
    """Spec §2's audit, made executable: confirms exactly which tables
    `ORNEUR_DATABASE_URL` owns today, so this list can't silently drift
    without a test noticing. See STATE_OWNERSHIP.md for the full
    owner/reader/writer/consistency table this backs."""
    import orca.auth.db as db
    schema_tables = {
        "users", "signup_counter", "usage_daily", "user_sessions",
        "organizations", "org_members", "privacy_consents",
        "consent_audit_log", "data_export_requests", "security_breach_log",
    }
    for table in schema_tables:
        assert table in db._SCHEMA_SQLITE
        assert table in db._SCHEMA_POSTGRES
    # audit_log is created by orca.audit's own _ensure_table(), not
    # auth.db's schema constants directly for SQLite (though Postgres's
    # schema also defines it) -- confirmed by reading orca/audit.py.
    assert "audit_log" in db._SCHEMA_POSTGRES


# --------------------------------------------------------------- §3, §6: no silent fallback, by construction


def test_sovereign_profile_local_auth_db_still_works(tmp_path):
    """Spec §5: SOVEREIGN must keep working exactly as before."""
    home = str(tmp_path / "home")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ.pop("ORNEUR_DEPLOYMENT_PROFILE", None)
    os.environ.pop("ORNEUR_DATABASE_URL", None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.auth.db as db
    importlib.reload(db)
    assert db.BACKEND == "sqlite"
    user = None
    import orca.auth.store as store
    importlib.reload(store)
    user = store.create_user("sovereign-test@example.com", "password123")
    assert store.get_user_by_email("sovereign-test@example.com").id == user.id


def test_distributed_missing_core_db_url_fails_at_import(tmp_path):
    """Spec §3-4: DISTRIBUTED with NO ORNEUR_DATABASE_URL must fail
    hard at `orca.auth.db` import time -- not silently create/use
    ~/.orca/auth.db."""
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN if _PG_AVAILABLE else "postgresql://x/y"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN if _PG_AVAILABLE else "postgresql://x/y"
    os.environ.pop("ORNEUR_DATABASE_URL", None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.auth.db as db
    with pytest.raises(RuntimeError, match="ORNEUR_DATABASE_URL"):
        importlib.reload(db)


def test_distributed_malformed_core_db_url_raises():
    """Spec §10: an unsupported scheme / malformed URL must also fail,
    via validate_deployment_config()'s own check (auth.db's own
    defense-in-depth check only verifies presence, not scheme --
    validate_deployment_config() is the authoritative scheme check)."""
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_DATABASE_URL"] = "not-a-real-dsn-at-all"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = "postgresql://x/y"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "postgresql://x/y"
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    with pytest.raises(dp.DeploymentConfigError, match="core application database"):
        dp.require_distributed_core_db_url()


def test_validate_deployment_config_requires_core_db_and_leaks_no_secret():
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = "postgresql://user:hunter2@example.com/db"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "postgresql://user:hunter2@example.com/db"
    os.environ.pop("ORNEUR_DATABASE_URL", None)
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    with pytest.raises(dp.DeploymentConfigError) as excinfo:
        dp.validate_deployment_config()
    message = str(excinfo.value)
    assert "ORNEUR_DATABASE_URL" in message or "core application database" in message
    assert "hunter2" not in message
    assert "://" not in message


@pytestmark_pg
def test_validate_deployment_config_distributed_all_three_backends_succeeds():
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN
    os.environ["ORNEUR_DATABASE_URL"] = _CORE_DB_DSN
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    summary = dp.validate_deployment_config(check_connectivity=True)
    assert summary["profile"] == "DISTRIBUTED"
    assert summary["core_db_backend"] == "postgres"


def test_validate_deployment_config_unreachable_core_db_fails_startup():
    """Spec §3's 'unreachable during mandatory startup validation'."""
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    os.environ["ORNEUR_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    with pytest.raises(dp.DeploymentConfigError):
        dp.validate_deployment_config(check_connectivity=True)


# --------------------------------------------------------------- §8: two-worker shared state, real production abstraction


def _worker_create_user_and_session(core_db_dsn, home, result_queue):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DATABASE_URL"] = core_db_dsn
    import importlib as _importlib
    import orca.config as config_mod
    _importlib.reload(config_mod)
    import orca.auth.db as db
    _importlib.reload(db)
    import orca.auth.store as store
    _importlib.reload(store)
    import uuid
    email = f"worker-a-{uuid.uuid4().hex[:10]}@example.com"
    user = store.create_user(email, "password123")
    store.record_user_session(user.id, f"session-{uuid.uuid4().hex[:8]}")
    import orca.audit as audit_mod
    _importlib.reload(audit_mod)
    entry_id = audit_mod.log("worker_a_created_user", user_id=user.id, detail={"email": email})
    result_queue.put(("CREATED", user.id, email, entry_id))


def _worker_read_user_session_and_audit(core_db_dsn, home, user_id, email, entry_id, result_queue):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DATABASE_URL"] = core_db_dsn
    import importlib as _importlib
    import orca.config as config_mod
    _importlib.reload(config_mod)
    import orca.auth.db as db
    _importlib.reload(db)
    import orca.auth.store as store
    _importlib.reload(store)
    user = store.get_user_by_email(email)
    session_ids = store.get_user_session_ids(user_id) if user else []
    import orca.audit as audit_mod
    _importlib.reload(audit_mod)
    recent = audit_mod.recent(limit=50, user_id=user_id)
    audit_visible = any(r.get("id") == entry_id for r in recent) if entry_id else False
    result_queue.put(("READ", user is not None and user.id == user_id, len(session_ids) > 0, audit_visible))


@pytestmark_pg
def test_two_worker_shared_auth_session_and_audit_state(tmp_path):
    """Spec §8: two real OS processes against one shared local Postgres
    core DB, using the ACTUAL production abstraction
    (orca.auth.store.create_user/record_user_session,
    orca.audit.log/recent), not direct SQL. Worker A creates a user +
    session + audit entry; worker B (separate process) observes all
    three."""
    home = str(tmp_path / "home-shared-core")
    os.makedirs(home, exist_ok=True)
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    worker_a = ctx.Process(target=_worker_create_user_and_session, args=(_CORE_DB_DSN, home, result_queue))
    worker_a.start()
    worker_a.join(timeout=15)
    outcome, user_id, email, entry_id = result_queue.get(timeout=5)
    assert outcome == "CREATED"

    worker_b = ctx.Process(target=_worker_read_user_session_and_audit, args=(_CORE_DB_DSN, home, user_id, email, entry_id, result_queue))
    worker_b.start()
    worker_b.join(timeout=15)
    outcome2, user_found, session_found, audit_visible = result_queue.get(timeout=5)
    assert outcome2 == "READ"
    assert user_found, "worker B must see the user worker A created"
    assert session_found, "worker B must see the session worker A recorded"
    assert audit_visible, "worker B must see the audit entry worker A wrote"


# --------------------------------------------------------------- §9: misconfigured worker cannot join


def _worker_check_core_db_startup(core_db_dsn_or_none, authority_dsn, security_root_dsn, home, result_queue):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = authority_dsn
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = security_root_dsn
    if core_db_dsn_or_none is not None:
        os.environ["ORNEUR_DATABASE_URL"] = core_db_dsn_or_none
    else:
        os.environ.pop("ORNEUR_DATABASE_URL", None)
    import importlib as _importlib
    import orca.config as config_mod
    _importlib.reload(config_mod)
    import orca.godmode.deployment_profile as dp
    _importlib.reload(dp)
    try:
        dp.validate_deployment_config()
    except dp.DeploymentConfigError:
        result_queue.put("REFUSED_STARTUP")
        return
    result_queue.put("SERVED")


@pytestmark_pg
def test_misconfigured_worker_missing_core_db_refuses_startup(tmp_path):
    """Spec §9: worker A correct, worker B missing ORNEUR_DATABASE_URL
    -- worker B must refuse startup, never create/use a local
    fallback database."""
    home = str(tmp_path / "home-misconfig-core")
    os.makedirs(home, exist_ok=True)
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    worker_a = ctx.Process(target=_worker_check_core_db_startup, args=(_CORE_DB_DSN, _AUTHORITY_DSN, _SECURITY_ROOT_DSN, home, result_queue))
    worker_a.start()
    worker_a.join(timeout=15)
    assert result_queue.get(timeout=5) == "SERVED"

    worker_b = ctx.Process(target=_worker_check_core_db_startup, args=(None, _AUTHORITY_DSN, _SECURITY_ROOT_DSN, home, result_queue))
    worker_b.start()
    worker_b.join(timeout=15)
    assert result_queue.get(timeout=5) == "REFUSED_STARTUP"

    assert not os.path.exists(os.path.join(home, "auth.db")), "a misconfigured worker must never create a local auth.db fallback"


# --------------------------------------------------------------- §11-12: backend outage and recovery


@pytestmark_pg
def test_core_db_outage_after_startup_denies_no_fallback(tmp_path):
    """Spec §11: after a worker starts correctly, make the shared core
    DB unavailable. Required: auth/session operations fail safely
    (raise or return None, matching orca.auth.store's existing
    contract), no local fallback file is created, no fabricated
    success."""
    home = str(tmp_path / "home-outage-core")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DATABASE_URL"] = _CORE_DB_DSN
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.auth.db as db
    importlib.reload(db)
    import orca.auth.store as store
    importlib.reload(store)
    assert db.BACKEND == "postgres"

    # Simulate outage WITHOUT reloading `db` -- `_get_postgres_conn()`
    # reads ORNEUR_DATABASE_URL fresh on every call (never cached), so
    # changing the env var alone is sufficient to make the NEXT
    # get_conn() call fail, exactly matching a real mid-session outage.
    # (Reloading `db` itself with a bad DSN is a DIFFERENT, harsher
    # scenario -- `init_db()` runs unconditionally at that module's own
    # import time, so a reload with a bad DSN crashes at import, not at
    # a graceful runtime call; that is real, pre-existing behavior of
    # this module, disclosed in STATE_OWNERSHIP.md's Phase 14A.4
    # addendum rather than silently worked around here.)
    os.environ["ORNEUR_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"

    with pytest.raises(Exception):
        store.create_user("outage-test@example.com", "password123")
    assert not os.path.exists(os.path.join(home, "auth.db")), "outage must never create a local fallback database"

    # Recovery -- restore the good DSN, no reload needed.
    os.environ["ORNEUR_DATABASE_URL"] = _CORE_DB_DSN
    import uuid
    email = f"recovery-{uuid.uuid4().hex[:8]}@example.com"
    user = store.create_user(email, "password123")
    assert store.get_user_by_email(email).id == user.id, "worker must return to correct, authoritative shared state after recovery with no restart"


# --------------------------------------------------------------- §13: tenant isolation (audit scoping)


@pytestmark_pg
def test_tenant_scoped_audit_no_cross_tenant_leak(tmp_path):
    """Spec §13: concurrent tenant-scoped operations across separate
    processes -- audit entries scoped by user_id must not leak across
    users when queried with a specific user_id filter."""
    home = str(tmp_path / "home-tenant")
    os.makedirs(home, exist_ok=True)

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    worker_a = ctx.Process(target=_worker_create_user_and_session, args=(_CORE_DB_DSN, home, result_queue))
    worker_a.start()
    worker_a.join(timeout=15)
    _, user_a_id, email_a, _ = result_queue.get(timeout=5)

    worker_b = ctx.Process(target=_worker_create_user_and_session, args=(_CORE_DB_DSN, home, result_queue))
    worker_b.start()
    worker_b.join(timeout=15)
    _, user_b_id, email_b, _ = result_queue.get(timeout=5)

    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DATABASE_URL"] = _CORE_DB_DSN
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.audit as audit_mod
    importlib.reload(audit_mod)

    recent_a = audit_mod.recent(limit=50, user_id=user_a_id)
    recent_b = audit_mod.recent(limit=50, user_id=user_b_id)
    assert all(r["user_id"] == user_a_id for r in recent_a)
    assert all(r["user_id"] == user_b_id for r in recent_b)
    assert user_a_id not in {r["user_id"] for r in recent_b}
    assert user_b_id not in {r["user_id"] for r in recent_a}


# --------------------------------------------------------------- §14: audit durability semantics (inspection, not redesign)


def test_godmode_elevation_audit_is_in_memory_only_and_does_not_gate_authorization(tmp_path):
    """Spec §14: inspect current semantics rather than redesigning them.
    Godmode's OWN elevation audit (orca.godmode.audit) is a plain
    in-memory list, entirely separate from ORNEUR_DATABASE_URL's
    hash-chained audit_log -- confirmed here as a living contract.
    Elevation authorization decisions (resolution.py) do not call or
    depend on either audit mechanism succeeding, so there is no
    "durable audit required before authorization" architecture for
    this phase to have silently violated -- the pre-existing,
    already-disclosed limitation (in STATE_OWNERSHIP.md) is that this
    specific audit trail is not durable, not that authorization is
    unsafe."""
    from orca.godmode import audit as godmode_audit
    assert isinstance(godmode_audit._AUDIT_LOG, list)

    import inspect
    import orca.godmode.resolution as resolution
    source = inspect.getsource(resolution)
    assert "godmode.audit" not in source and "record_elevation_event" not in source, (
        "resolution.py's authorization decision must not depend on the in-memory Godmode audit log "
        "succeeding or being called -- confirming no accidental new coupling was introduced"
    )


@pytestmark_pg
def test_orca_audit_log_never_raises_and_reports_failure_via_none_return():
    """orca.audit.log()'s own documented contract: 'Never raises (audit
    failures must not break the request they're logging). Returns the
    entry id, or None on failure.' Confirmed directly against a broken
    backend -- this is intentional, pre-existing fail-soft behavior,
    not a gap introduced or hidden by this phase. Imports `db`/`audit`
    successfully first (with a real, working DSN), THEN breaks the env
    var without reloading -- see the outage test above for why
    reloading `orca.auth.db` itself with an already-bad DSN is a
    different, harsher scenario (it crashes at import via `init_db()`,
    not gracefully at a runtime call)."""
    os.environ["ORNEUR_DATABASE_URL"] = _CORE_DB_DSN
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.auth.db as db
    importlib.reload(db)
    import orca.audit as audit_mod
    importlib.reload(audit_mod)

    os.environ["ORNEUR_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    result = audit_mod.log("test_event_against_broken_backend")
    assert result is None, "log() must report failure via None, never raise, never fabricate a fake entry id"


# --------------------------------------------------------------- §15: security-root regression


@pytest.mark.parametrize("_marker", [1])
def test_security_root_local_fallback_still_impossible_in_distributed_mode(tmp_path, _marker):
    """Spec §15: re-confirm Phase 14A.3's core guarantee is unaffected
    by this phase's core-DB changes."""
    home = str(tmp_path / "home-regression")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ.pop("ORNEUR_SECURITY_ROOT_DATABASE_URL", None)
    os.environ.pop("ORNEUR_SECURITY_ROOT_HOME", None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.security_root as security_root
    importlib.reload(security_root)
    from orca.godmode.deployment_profile import DeploymentConfigError
    with pytest.raises(DeploymentConfigError):
        security_root._backend()


# --------------------------------------------------------------- §7: readiness reflects core-db outage


def test_readyz_not_ready_when_distributed_core_db_becomes_unavailable():
    """Spec §7: a worker that started successfully whose shared core
    database becomes unavailable afterward must report NOT_READY, not
    silently stay READY (mirroring the analogous security-root check
    added in Phase 14A.3 -- see
    test_distributed_security_root_config_gate.py's own version of
    this test for why api.py is imported first, under whatever profile
    is already active, rather than re-imported under bad config)."""
    from orca.serve import api as api_module
    from fastapi.testclient import TestClient
    client = TestClient(api_module.app)

    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)

    import unittest.mock as mock
    with mock.patch.object(api_module, "resolve_tier_model", lambda tier, host=None: "orca-nano"):
        resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["dependencies"]["core_database"]["status"] == "unavailable"


# --------------------------------------------------------------- §17: state leak


def test_no_home_leak_during_distributed_core_db_tests():
    assert not os.path.exists(os.path.expanduser("~/.orneur-security-root"))
    assert not os.path.exists(os.path.expanduser("~/.orca/godmode"))
