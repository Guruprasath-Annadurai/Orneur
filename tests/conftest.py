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
    yield


@pytest.fixture
def isolated_home():
    """
    Points ORCA_HOME at a fresh temp dir and reloads config/db/store so
    they pick up the new path. Yields the store module for direct use.
    """
    tmpdir = tempfile.mkdtemp(prefix="orca_test_")
    prev_home = os.environ.get("ORCA_HOME")
    prev_db_url = os.environ.get("ORCA_DATABASE_URL")
    os.environ["ORCA_HOME"] = tmpdir
    os.environ.pop("ORCA_DATABASE_URL", None)  # force SQLite backend for tests

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

    shutil.rmtree(tmpdir, ignore_errors=True)
