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
def _isolate_gateway_registry_dirs(request, tmp_path, monkeypatch):
    """
    Regression protection (Phase 7.1 spec §29-30): `tests/test_gateway_chaos.py`
    was found writing a real `ModelDeployment` record into the developer's
    actual `~/.orca/registry/deployments/` (via `ModelDeployment.request_drain()`
    -> `.save()`) because that one test forgot to isolate `DEPLOYMENT_DIR`.
    Every `tests/test_gateway_*.py` module now gets `DEPLOYMENT_DIR`
    pointed at a fresh `tmp_path` automatically, so a future test that
    forgets an explicit `monkeypatch.setattr(..., "DEPLOYMENT_DIR", ...)`
    still cannot touch real developer state. A test that explicitly sets
    its own `DEPLOYMENT_DIR` override still works -- this fixture runs
    first and the test's own `monkeypatch.setattr` simply takes over.
    """
    if request.module.__name__.startswith("tests.test_gateway") or request.module.__name__.startswith("test_gateway"):
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
