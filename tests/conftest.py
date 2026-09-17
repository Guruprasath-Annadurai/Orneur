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

    # Phase 14C: `orca.docs.store` (RAG doc storage, chromadb-backed) has
    # the exact same real-directory-leak shape as DEPLOYMENT_DIR/LEASE_DIR
    # above -- `DOCS_DIR` and `_REGISTRY_FILE` are module-level constants
    # captured once at import time from `ORCA_HOME`, never re-isolated
    # per test the way `isolated_home` re-isolates auth/db modules. Left
    # unpatched, every test that constructs a real `_Session` (chat,
    # docs, memory, knowledge-graph, session-load/export tests) shares
    # ONE real chromadb `PersistentClient` path across the whole pytest
    # process -- harmless when only one such test runs, but a SECOND
    # real chromadb-backed session constructed later in the same process
    # intermittently hits `chromadb.errors.InternalError: ... readonly
    # database`, an order-dependent flake with no relation to the code
    # under test. Isolating both constants here (same tmp_path already
    # used for DEPLOYMENT_DIR/LEASE_DIR above) gives every test its own
    # chroma path, matching this fixture's existing unconditional
    # per-test isolation for the other file-backed stores.
    import orca.docs.store as docs_store_mod
    docs_tmp = tmp_path / "docs"
    docs_tmp.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(docs_store_mod, "DOCS_DIR", docs_tmp)
    monkeypatch.setattr(docs_store_mod, "_REGISTRY_FILE", docs_tmp / "registry.json")

    # Phase 21A audit finding, closed in Phase 21B: the exact same
    # unisolated-module-constant leak this fixture already fixed for
    # DEPLOYMENT_DIR/LEASE_DIR/DOCS_DIR also existed for the model/
    # dataset/checkpoint/training-run registries -- confirmed live during
    # the Phase 21A forensic audit, which found real test-run pollution
    # (fake "force-test"/"v1"/"v2" evaluation records, a "test-model"
    # redteam file) sitting in the developer's actual ~/.orca/registry/
    # and ~/.orca/training/ directories. Isolating all four here, same
    # tmp_path already used above.
    import orca.registry.checkpoint as checkpoint_mod
    import orca.registry.dataset_bundle as dataset_bundle_mod
    import orca.registry.dataset_manifest as dataset_manifest_mod
    import orca.registry.evaluation_registry as evaluation_registry_mod
    import orca.registry.evaluation_suite_manifest as evaluation_suite_manifest_mod
    import orca.registry.model_registry as model_registry_mod
    import orca.registry.provenance as provenance_mod
    import orca.registry.training_run as training_run_mod
    registry_tmp = tmp_path / "registry"
    checkpoint_dir_tmp = registry_tmp / "checkpoints"
    dataset_dir_tmp = registry_tmp / "datasets"
    dataset_bundle_dir_tmp = registry_tmp / "dataset_bundles"
    evaluation_dir_tmp = registry_tmp / "evaluations"
    # Phase 21B.3: the evaluation SUITE manifest registry (genesis-eval-v1's
    # own definition -- task set/content/scoring-contract digests) is a
    # separate directory from evaluation_dir_tmp above (which holds
    # per-candidate EvaluationReport RESULTS, not suite definitions) --
    # same unisolated-module-constant risk, isolated here too.
    evaluation_suite_dir_tmp = registry_tmp / "evaluation_suites"
    training_run_dir_tmp = registry_tmp / "training_runs"
    # Phase 21B.2: run-scoped dataset snapshots (the TOCTOU-closure
    # mechanism) live under ~/.orca/training/, not ~/.orca/registry/ --
    # same unisolated-module-constant risk, isolated here too.
    run_snapshot_dir_tmp = tmp_path / "training" / "run_snapshots"
    for d in (
        checkpoint_dir_tmp, dataset_dir_tmp, dataset_bundle_dir_tmp, evaluation_dir_tmp,
        evaluation_suite_dir_tmp, training_run_dir_tmp, run_snapshot_dir_tmp, registry_tmp,
    ):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", checkpoint_dir_tmp)
    monkeypatch.setattr(dataset_bundle_mod, "DATASET_BUNDLE_DIR", dataset_bundle_dir_tmp)
    monkeypatch.setattr(dataset_manifest_mod, "DATASET_MANIFEST_DIR", dataset_dir_tmp)
    monkeypatch.setattr(evaluation_registry_mod, "EVALUATION_REGISTRY_DIR", evaluation_dir_tmp)
    monkeypatch.setattr(evaluation_suite_manifest_mod, "EVALUATION_SUITE_DIR", evaluation_suite_dir_tmp)
    monkeypatch.setattr(model_registry_mod, "REGISTRY_STATE_PATH", registry_tmp / "registry_state.json")
    monkeypatch.setattr(training_run_mod, "TRAINING_RUN_DIR", training_run_dir_tmp)
    monkeypatch.setattr(provenance_mod, "RUN_SNAPSHOT_DIR", run_snapshot_dir_tmp)

    # Same risk for the default formatted-training-data directory --
    # orca.train.config.FORMATTED_DIR is a module-level ORCA_HOME-derived
    # constant a test could otherwise silently read/resolve against the
    # developer's real ~/.orca/training/formatted/.
    import orca.train.config as train_config_mod
    formatted_dir_tmp = tmp_path / "training" / "formatted"
    formatted_dir_tmp.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(train_config_mod, "FORMATTED_DIR", formatted_dir_tmp)

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

    # Phase 16 closure: the docstring above has long claimed this fixture
    # "reloads the same modules on teardown" -- it never actually did. That
    # left `orca.config.ORCA_HOME` (and anything importing the *value*, like
    # orca/train/config.py's `from orca.config import ORCA_HOME`) pointed at
    # this fixture's now-deleted tmpdir for the rest of the pytest session,
    # for any module not yet imported at the point this fixture first ran.
    # This was undetected until a full-suite run happened to trigger the
    # FIRST-EVER lazy import of orca.train.config/orca.train.cloud after an
    # isolated_home-using test, producing a genuine
    # `FileNotFoundError: .../orca_test_.../models` in an entirely unrelated
    # test (see tests/test_phase16_training_fail_closed.py) -- the exact
    # kind of state-isolation gap this project's own anti-test-gaming
    # discipline requires root-causing rather than working around.
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(store)
    importlib.reload(privacy)

    shutil.rmtree(tmpdir, ignore_errors=True)
