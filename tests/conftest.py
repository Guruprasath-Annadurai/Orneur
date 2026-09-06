"""
Shared pytest fixtures.

Real risk this avoids: every auth/db test that doesn't isolate ORCA_HOME
would read/write the developer's actual ~/.orca/auth.db — corrupting real
account data or picking up stale state between test runs. isolated_home
gives every test a fresh temp directory and reloads the config/db/store
modules against it, so tests are hermetic and repeatable.
"""
from __future__ import annotations

import importlib
import os
import tempfile
import shutil

import pytest


@pytest.fixture(autouse=True)
def _isolate_gateway_registry_dirs(tmp_path, monkeypatch):
    """
    Regression protection (Phase 7.1 spec §29-30): `tests/test_gateway_chaos.py`
    was found writing a real `ModelDeployment` record into the developer's
    actual `~/.orca/registry/deployments/` (via `ModelDeployment.request_drain()`
    -> `.save()`) because that test forgot to isolate `DEPLOYMENT_DIR`.

    Widened in Phase 7.1's deployment-records work (spec §25-26) to cover
    EVERY test unconditionally, not just `test_gateway_*` modules: once
    `orca.gateway.wiring.brain_for_tier_resolution()` started persisting
    (`.save()`) the deployment record it registers for each live model
    call -- so Model Society's disk-based `list_deployments()` can
    actually see production deployment state -- ANY test that exercises a
    real Court/Kernel/Truth Fabric model call (not just `test_gateway_*`
    files) would otherwise also write into the developer's real
    `~/.orca/registry/deployments/`. Isolating `DEPLOYMENT_DIR` here does
    NOT prevent live-Ollama tests from making real model calls -- it only
    keeps the deployment-record bookkeeping local to this test run. A
    test that explicitly sets its own `DEPLOYMENT_DIR` override still
    works -- this fixture runs first and the test's own
    `monkeypatch.setattr` simply takes over.
    """
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)

    # Phase 10: same real risk for orca.godmode's file-backed lease store
    # -- lives under ORCA_HOME by default and must never touch a
    # developer's real ~/.orca/godmode/ during a test run.
    #
    # Phase 14A.1: kill-switch state moved INTO this same leases.db file
    # (orca.godmode.lease_store's kill_switch_state table) rather than
    # its own flag file -- redirecting LEASE_DIR here already isolates
    # kill-switch state too, so the old
    # `monkeypatch.setattr(kill_switch_mod, "_KILL_SWITCH_FILE", ...)`
    # line is gone (that attribute no longer exists; monkeypatch would
    # raise AttributeError on every single test in this suite, since
    # this fixture is autouse). See docs/orneur/phase-14/KILL_SWITCH_DURABILITY.md.
    import orca.godmode.lease_store as lease_store_mod
    godmode_tmp = tmp_path / "godmode"
    monkeypatch.setattr(lease_store_mod, "LEASE_DIR", godmode_tmp / "leases")

    # Phase 14A.2: orca.godmode.security_root is DELIBERATELY independent
    # of ORCA_HOME (that is its entire security property -- see its
    # module docstring) and defaults to `~/.orneur-security-root`, a
    # real directory under the developer's actual home. Every test that
    # calls kill_switch.activate()/is_active() now writes there unless
    # isolated -- `monkeypatch.setenv` works directly here (no module
    # reload needed) because `security_root._root_home()` re-reads this
    # env var on every call, never caching it at import time.
    monkeypatch.setenv("ORNEUR_SECURITY_ROOT_HOME", str(godmode_tmp / "security-root"))
    yield


@pytest.fixture
def isolated_home():
    """
    Points ORCA_HOME at a fresh temp dir and reloads config/db/store so
    they pick up the new path. Yields the store module for direct use.

    Phase 14A.4 real bug found and fixed: this fixture only ever popped
    the legacy `ORCA_DATABASE_URL` env var, never `ORNEUR_DATABASE_URL`
    -- the name `orneur_env()` actually prefers. A test elsewhere in
    the same pytest session that left `ORNEUR_DATABASE_URL` set (e.g.
    a DISTRIBUTED-profile config test) meant every test using THIS
    fixture silently kept hitting that real/leftover Postgres database
    instead of the fresh isolated SQLite tmp file this fixture exists
    to guarantee -- surfaced as raw `psycopg.errors.UniqueViolation`
    failures in tests/test_auth_privacy.py and tests/test_org_store.py
    that have nothing to do with Postgres at all. Also now reloads the
    same modules on teardown (not just restoring the env vars) so a
    LATER test relying on module import order elsewhere doesn't
    inherit this fixture's own tmp-dir state.
    """
    tmpdir = tempfile.mkdtemp(prefix="orca_test_")
    prev_home = os.environ.get("ORCA_HOME")
    prev_db_url = os.environ.get("ORCA_DATABASE_URL")
    prev_db_url_orneur = os.environ.get("ORNEUR_DATABASE_URL")
    os.environ["ORCA_HOME"] = tmpdir
    os.environ.pop("ORCA_DATABASE_URL", None)  # force SQLite backend for tests
    os.environ.pop("ORNEUR_DATABASE_URL", None)  # same -- see docstring

    import orca.config as config
    import orca.auth.db as db
    import orca.auth.store as store
    import orca.auth.privacy as privacy

    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(store)
    importlib.reload(privacy)

    yield store

    if prev_home is not None:
        os.environ["ORCA_HOME"] = prev_home
    else:
        os.environ.pop("ORCA_HOME", None)
    if prev_db_url is not None:
        os.environ["ORCA_DATABASE_URL"] = prev_db_url
    if prev_db_url_orneur is not None:
        os.environ["ORNEUR_DATABASE_URL"] = prev_db_url_orneur

    shutil.rmtree(tmpdir, ignore_errors=True)
