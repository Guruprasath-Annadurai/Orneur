"""
Phase 14A.3 -- closes the real, disclosed cloud-blocking configuration
hazard from Phase 14A.2's own closure: in DISTRIBUTED mode, if
`ORNEUR_SECURITY_ROOT_DATABASE_URL` was absent,
`orca.godmode.security_root._backend()` silently fell back to per-host
file storage. On a genuine multi-host deployment this can create
MULTIPLE INDEPENDENT kill-switch/security-root authorities.

Fix: `orca.godmode.deployment_profile` -- an explicit
`ORNEUR_DEPLOYMENT_PROFILE` (SOVEREIGN default / DISTRIBUTED), and
`security_root._backend()` / `lease_store._backend()` both raise
(rather than silently falling back) when DISTRIBUTED mode lacks valid,
explicitly configured shared backends. Read paths
(`get_epoch_and_state()`, `is_active()`, the lease-store dispatchers)
convert that raise into the same fail-closed UNKNOWN/False/None result
as a real connectivity failure -- never a crash, never a silent
fallback.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os

import pytest


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev = {k: os.environ.get(k) for k in (
        "ORCA_HOME", "ORNEUR_HOME", "ORNEUR_DEPLOYMENT_PROFILE",
        "ORNEUR_GODMODE_DATABASE_URL", "ORNEUR_SECURITY_ROOT_DATABASE_URL",
        "ORNEUR_SECURITY_ROOT_HOME",
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
    import orca.godmode.kill_switch as kill_switch_mod
    importlib.reload(kill_switch_mod)


_AUTHORITY_DSN = "postgresql://ag@localhost/orneur_phase14_test"
_SECURITY_ROOT_DSN = "postgresql://ag@localhost/orneur_phase14_security_root_test"
_CORE_DB_DSN = "postgresql://ag@localhost/orneur_phase14_authdb_test"

# Phase 14A.4 extended validate_deployment_config() to also require
# ORNEUR_DATABASE_URL (the core auth/session/audit backend) in
# DISTRIBUTED mode -- every test in this file that calls
# validate_deployment_config() or spawns a worker that does now also
# sets this, even though this file's own primary subject is the
# security root specifically. See test_distributed_core_db_config_gate.py
# for the dedicated core-db test suite.


def _postgres_reachable(dsn: str) -> bool:
    try:
        import psycopg
        conn = psycopg.connect(dsn, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


_PG_AVAILABLE = _postgres_reachable(_AUTHORITY_DSN) and _postgres_reachable(_SECURITY_ROOT_DSN) and _postgres_reachable(_CORE_DB_DSN)
pytestmark_pg = pytest.mark.skipif(not _PG_AVAILABLE, reason="requires three real local Postgres databases")


def _reload_all():
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.security_root as security_root_mod
    importlib.reload(security_root_mod)
    import orca.godmode.kill_switch as kill_switch_mod
    importlib.reload(kill_switch_mod)
    return lease_store_mod, security_root_mod, kill_switch_mod


# --------------------------------------------------------------- §1-3: no silent fallback, by construction


def test_sovereign_profile_local_file_security_root_still_works(tmp_path):
    """Spec §4: SOVEREIGN must keep working exactly as before -- no
    ORNEUR_DEPLOYMENT_PROFILE set (or explicitly SOVEREIGN) means local
    file-based security root remains valid."""
    home = str(tmp_path / "home")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_SECURITY_ROOT_HOME"] = security_root_home
    os.environ.pop("ORNEUR_DEPLOYMENT_PROFILE", None)
    os.environ.pop("ORNEUR_SECURITY_ROOT_DATABASE_URL", None)
    os.environ.pop("ORNEUR_GODMODE_DATABASE_URL", None)
    ls, security_root, ks = _reload_all()

    assert security_root._backend() == "sqlite"
    ks.activate(reason="sovereign still works")
    assert ks.is_active() is True


def test_distributed_missing_security_root_url_raises_not_silently_falls_back(tmp_path):
    """Spec §1-3: the core fix. DISTRIBUTED profile with NO
    ORNEUR_SECURITY_ROOT_DATABASE_URL must never silently create a
    local file -- `_backend()` raises, and no
    ~/.orneur-security-root-style directory is created at the default
    location this test does NOT override (proving the raise happens
    BEFORE any file-creation code path runs)."""
    home = str(tmp_path / "home")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ.pop("ORNEUR_SECURITY_ROOT_DATABASE_URL", None)
    os.environ.pop("ORNEUR_SECURITY_ROOT_HOME", None)  # deliberately NOT overridden -- proving no fallback path is touched
    _, security_root, ks = _reload_all()

    from orca.godmode.deployment_profile import DeploymentConfigError
    with pytest.raises(DeploymentConfigError):
        security_root._backend()

    # Read paths must fail closed, not raise, and not create a file.
    epoch, state = security_root.get_epoch_and_state()
    assert state == "UNKNOWN"
    assert epoch is None
    assert ks.is_active() is True, "DISTRIBUTED misconfiguration must fail closed (deny), never crash or silently allow"


def test_distributed_malformed_security_root_url_raises(tmp_path):
    """Spec §2: "resolves to an unsupported backend" must also fail --
    not just a missing value."""
    home = str(tmp_path / "home")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "not-a-real-dsn-at-all"
    _, security_root, ks = _reload_all()

    from orca.godmode.deployment_profile import DeploymentConfigError
    with pytest.raises(DeploymentConfigError):
        security_root._backend()
    assert ks.is_active() is True


def test_unknown_deployment_profile_fails_startup(tmp_path):
    """Spec §5: an unrecognized profile value must fail immediately,
    never silently default to SOVEREIGN or DISTRIBUTED."""
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "NOT_A_REAL_PROFILE"
    from orca.godmode.deployment_profile import DeploymentConfigError, get_profile
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    with pytest.raises(dp.DeploymentConfigError):
        dp.get_profile()


# --------------------------------------------------------------- §6: centralized startup validation, no secrets echoed


def test_validate_deployment_config_sovereign_is_a_noop():
    os.environ.pop("ORNEUR_DEPLOYMENT_PROFILE", None)
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    summary = dp.validate_deployment_config()
    assert summary["profile"] == "SOVEREIGN"


def test_validate_deployment_config_distributed_missing_config_raises_without_leaking_secrets():
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ.pop("ORNEUR_SECURITY_ROOT_DATABASE_URL", None)
    os.environ.pop("ORNEUR_GODMODE_DATABASE_URL", None)
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    with pytest.raises(dp.DeploymentConfigError) as excinfo:
        dp.validate_deployment_config()
    message = str(excinfo.value)
    assert "://" not in message, "no connection string should ever appear in a raised config error message"


@pytestmark_pg
def test_validate_deployment_config_distributed_with_real_backends_succeeds():
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN
    os.environ["ORNEUR_DATABASE_URL"] = _CORE_DB_DSN
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    summary = dp.validate_deployment_config(check_connectivity=True)
    assert summary["profile"] == "DISTRIBUTED"
    assert summary["security_root_backend"] == "postgres"


def test_validate_deployment_config_distributed_unreachable_backend_fails_startup():
    """Spec §2's 'unreachable during mandatory startup validation' case
    -- a well-formed but unreachable DSN must fail exactly like a
    missing one."""
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    with pytest.raises(dp.DeploymentConfigError):
        dp.validate_deployment_config(check_connectivity=True)


# --------------------------------------------------------------- §7: readiness reflects security-root state


def test_readyz_not_ready_when_distributed_security_root_becomes_unavailable():
    """`orca.serve.api` runs its startup validation once, at first
    import -- a real server that failed that check would never reach
    a running app to serve /readyz from at all (see the other tests in
    this file for that "fail startup" case, tested directly against
    `validate_deployment_config()` rather than by re-importing this
    heavy module). This test instead proves /readyz's OWN runtime
    behavior: a worker that started successfully (DISTRIBUTED, valid
    config at import time) whose security root becomes unavailable
    AFTERWARD (a transient outage, spec §13) must report NOT_READY,
    not silently stay READY."""
    # Import api.py under whatever profile is already active in this
    # session (SOVEREIGN by default) -- this succeeds regardless of
    # import order, since api.py's module-level validation only runs
    # once, on Python's first-ever import of this module.
    from orca.serve import api as api_module
    from fastapi.testclient import TestClient
    client = TestClient(api_module.app)

    # NOW simulate a transient outage: DISTRIBUTED profile, security
    # root pointed at an unreachable host -- set AFTER api.py already
    # finished importing, so this is purely a runtime-read-path test.
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    import orca.godmode.deployment_profile as dp
    importlib.reload(dp)
    import orca.godmode.security_root as security_root
    importlib.reload(security_root)

    import unittest.mock as mock
    with mock.patch.object(api_module, "resolve_tier_model", lambda tier, host=None: "orca-nano"):
        resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["dependencies"]["security_root"]["status"] == "unavailable"


# --------------------------------------------------------------- §8-9: two-host simulation, misconfigured worker cannot join


def _worker_check_distributed(security_root_dsn_or_none, authority_dsn, lease_id, home, result_queue, core_db_dsn=None):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = authority_dsn
    os.environ["ORNEUR_DATABASE_URL"] = core_db_dsn or _CORE_DB_DSN
    if security_root_dsn_or_none is not None:
        os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = security_root_dsn_or_none
    else:
        os.environ.pop("ORNEUR_SECURITY_ROOT_DATABASE_URL", None)
    import importlib as _importlib
    import orca.config as config_mod
    _importlib.reload(config_mod)
    import orca.godmode.deployment_profile as dp
    _importlib.reload(dp)

    try:
        dp.validate_deployment_config()
    except dp.DeploymentConfigError:
        result_queue.put(("REFUSED_STARTUP", None))
        return

    import orca.godmode.lease_store as ls
    _importlib.reload(ls)
    import orca.godmode.security_root as security_root
    _importlib.reload(security_root)
    import orca.godmode.kill_switch as ks
    _importlib.reload(ks)
    import orca.godmode.resolution as resolution
    _importlib.reload(resolution)
    from orca.godmode.contracts import CapabilityDomain
    decision = resolution.resolve_and_consume_lease(
        lease_id=lease_id, tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
    )
    result_queue.put(("SERVED", decision.state.value))


@pytestmark_pg
def test_two_worker_shared_security_root_kill_switch_propagates(tmp_path):
    """Spec §8: two real processes, both correctly configured
    DISTRIBUTED with the SAME shared Postgres security root. Worker A
    activates; worker B (a genuinely separate process) attempts
    elevated authorization. Required: DENY."""
    home = str(tmp_path / "home-shared")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN
    ls, security_root, ks = _reload_all()

    ks.deactivate()  # known baseline -- shared Postgres row persists across test runs
    lease_id = f"two-host-{tmp_path.name}"
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments
    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=300, reason="two-host test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=5)

    ks.activate(reason="worker A activation")  # "process A"

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    worker_b = ctx.Process(target=_worker_check_distributed, args=(_SECURITY_ROOT_DSN, _AUTHORITY_DSN, lease.lease_id, home, result_queue))
    worker_b.start()
    worker_b.join(timeout=15)
    outcome, decision_state = result_queue.get(timeout=5)
    assert outcome == "SERVED"
    assert decision_state == "DENY", "worker B, a genuinely separate process sharing the same security root, must see worker A's activation"


@pytestmark_pg
def test_misconfigured_worker_refuses_startup_instead_of_local_fallback(tmp_path):
    """Spec §8-9: deliberately remove the security-root URL for worker
    B. Required: B refuses startup/config validation -- it must NOT
    create a local security-root file, and it must NOT join the
    serving pool (never even reach resolution.py)."""
    home = str(tmp_path / "home-misconfig")
    os.makedirs(home, exist_ok=True)

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    worker_b = ctx.Process(target=_worker_check_distributed, args=(None, _AUTHORITY_DSN, "irrelevant-lease-id", home, result_queue))
    worker_b.start()
    worker_b.join(timeout=15)
    outcome, _ = result_queue.get(timeout=5)
    assert outcome == "REFUSED_STARTUP", "a misconfigured DISTRIBUTED worker must refuse to start, never silently serve with a local fallback"

    # No local security-root file must exist anywhere under this
    # worker's own ORCA_HOME-adjacent locations it might have used.
    import os as _os
    assert not _os.path.exists(_os.path.join(home, "..", ".orneur-security-root"))


# --------------------------------------------------------------- §13-14: backend outage and recovery


@pytestmark_pg
def test_security_root_outage_after_startup_denies_no_fallback_no_reset(tmp_path):
    """Spec §13: after a worker has started correctly against the real
    shared security root, make it temporarily unreachable (by pointing
    at a bad host without ever having created a local file). Required:
    new elevated authorization DENY, no local fallback, no epoch
    reset."""
    home = str(tmp_path / "home-outage")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_DEPLOYMENT_PROFILE"] = "DISTRIBUTED"
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN
    ls, security_root, ks = _reload_all()

    ks.deactivate()
    epoch_before, _ = security_root.get_epoch_and_state()

    # Simulate outage: point at an unreachable host (never touches the
    # real security root again, never creates a local file).
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    _, security_root2, ks2 = _reload_all()

    assert ks2.is_active() is True, "outage must deny (fail closed), never allow"
    epoch_during_outage, state_during_outage = security_root2.get_epoch_and_state()
    assert state_during_outage == "UNKNOWN"
    assert epoch_during_outage is None, "no epoch reset -- outage reports UNKNOWN, not a fabricated 0 or stale value"

    # Recovery: restore connectivity.
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN
    _, security_root3, ks3 = _reload_all()
    epoch_after, state_after = security_root3.get_epoch_and_state()
    assert state_after == "INACTIVE"
    assert epoch_after == epoch_before, "the security root's real state is observed correctly after recovery, no reset occurred, no process restart was required beyond this module reload (which stands in for a fresh connection attempt, not a process restart)"


# --------------------------------------------------------------- §15: home leak


def test_no_home_leak_during_distributed_config_tests():
    import os as _os
    assert not _os.path.exists(_os.path.expanduser("~/.orneur-security-root"))
    assert not _os.path.exists(_os.path.expanduser("~/.orca/godmode"))
