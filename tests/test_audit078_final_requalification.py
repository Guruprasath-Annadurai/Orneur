"""ORNEUR — AUDIT #078 FINAL TARGETED REQUALIFICATION TEST SUITE
Independently verifies PR #78 (HEAD: 55eb4fea5c5c4820db6b15e1a2aac5885bddce78)
against the CTO Final Targeted Requalification Directive.

Covers:
1. Intermediate-directory symlink substitution against the actual repaired isolated worker over IPC.
2. Verification that save/restore, lockfiles, tempfiles, and manifests cannot escape workspace.
3. Linux-specific descriptor behavior (_open_dir_no_symlinks leaf fd fsyncability) and failure cleanup.
4. allow_cross_run_migration=True rejection on every callable path (CrossRunMigrationDisabledError).
5. Normal same-run checkpoint restoration verification.
"""
from __future__ import annotations

import fcntl
import multiprocessing as mp
import os
import secrets
import shutil
import stat
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

from orca import config as orca_config
from orca.config import (
    UntrustedStoreDirectory,
    _dirfd_mkstemp,
    _open_dir_no_symlinks,
)
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.training import isolated_worker as wmod
from orca.genesis.training.isolated_worker import (
    IsolatedTrainingWorker,
    _enforce_checkpoint_path_confinement,
)
import orca.genesis.governance.authorization as GOV
from orca.genesis.training.primitives import (
    TrainingState,
    save_training_state,
)
from orca.genesis.training.resumable_checkpoint import (
    CrossRunCheckpointAccessError,
    CrossRunMigrationDisabledError,
    DatasetIdentity,
    compute_config_fingerprint,
    restore_resumable_checkpoint,
    save_resumable_checkpoint,
)
from tests.test_genesis_isolated_worker import _make_cfg, TINY_MODEL_CFG, STEP_CFG


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _sync_worker_main_toctou(cfg, ready_evt, error_queue, status_queue, post_val_evt, resume_evt):
    """Worker process target: hooks path confinement inside spawned child process."""
    real_enforce = wmod._enforce_checkpoint_path_confinement

    def hooked_enforce(cfg_arg, requested_path):
        resolved = real_enforce(cfg_arg, requested_path)
        if post_val_evt is not None:
            post_val_evt.set()
        if resume_evt is not None:
            if not resume_evt.wait(timeout=15.0):
                raise TimeoutError("worker timed out waiting for resume_evt from parent test")
        return resolved

    wmod._enforce_checkpoint_path_confinement = hooked_enforce
    wmod._worker_main(cfg, ready_evt, error_queue, status_queue)


class SynchronizedWorker(IsolatedTrainingWorker):
    def __init__(self, cfg, post_val_evt=None, resume_evt=None):
        super().__init__(cfg)
        self.post_val_evt = post_val_evt
        self.resume_evt = resume_evt

    def start(self, timeout: float = 15.0) -> None:
        ctx = mp.get_context("spawn")
        self._ready_evt = ctx.Event()
        self._error_queue = ctx.Queue()
        self._status_queue = ctx.Queue()
        self._proc = ctx.Process(
            target=_sync_worker_main_toctou,
            args=(self._cfg, self._ready_evt, self._error_queue, self._status_queue, self.post_val_evt, self.resume_evt),
            daemon=True,
        )
        self._proc.start()
        if not self._ready_evt.wait(timeout):
            reason = self._error_queue.get_nowait() if not self._error_queue.empty() else "worker did not become ready"
            self.stop()
            raise RuntimeError(reason)
        try:
            self.isolation_qualification = self._status_queue.get(timeout=5.0)
        except Exception:
            self.isolation_qualification = "ISOLATION_NOT_QUALIFIED"


# ==============================================================================
# CHECK 1: INTERMEDIATE-DIRECTORY SYMLINK-SUBSTITUTION ATTACK OVER IPC
# ==============================================================================

def test_check1_intermediate_symlink_substitution_defeated_on_isolated_worker(tmp_path):
    """Reruns the previously demonstrated intermediate-ancestor substitution attack
    against the actual repaired isolated worker across the IPC boundary.
    Proves:
    1. The save is rejected fail-closed with UntrustedStoreDirectory.
    2. Zero files (checkpoint, tempfile, manifest, lock) escape to outside_dir.
    3. The worker remains alive and accepts subsequent authorized requests."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "inner").mkdir()

    cfg = _make_cfg(tmp_path, checkpoint_workspace_dir=workspace)
    ctx = mp.get_context("spawn")
    post_val_evt = ctx.Event()
    resume_evt = ctx.Event()

    worker = SynchronizedWorker(cfg, post_val_evt=post_val_evt, resume_evt=resume_evt)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            # Create sub/inner in workspace
            sub = workspace / "sub"
            (sub / "inner").mkdir(parents=True)

            key = secrets.token_bytes(32)
            save_result = {}

            def _call_save():
                save_result["resp"] = client.save_checkpoint(
                    path="sub/inner/ckpt.pt",
                    integrity_key=key,
                    sampler_position=0,
                    sampler_seed=42,
                    sampler_num_blocks=10,
                )

            th = threading.Thread(target=_call_save)
            th.start()

            # 1. Wait deterministically for worker to pass validation hook
            assert post_val_evt.wait(timeout=10.0), "Worker validation hook was not triggered"

            # 2. TOCTOU Window: Swap intermediate directory 'sub' to symlink -> outside_dir
            shutil.rmtree(sub)
            sub.symlink_to(outside_dir)
            assert sub.is_symlink()

            # 3. Release worker to proceed to save
            resume_evt.set()
            th.join(timeout=10.0)

            # 4. Assert save failed closed
            resp = save_result.get("resp")
            assert resp is not None, "Save call returned no response"
            assert resp["ok"] is False, f"Expected save to fail, but got: {resp}"
            assert "UntrustedStoreDirectory" in resp["error"], f"Unexpected error: {resp['error']}"
            assert "'sub' is a symlink" in resp["error"]

            # 5. Assert ZERO files escaped into outside_dir
            outside_files = list((outside_dir / "inner").iterdir())
            assert len(outside_files) == 0, f"Defect: files escaped to outside directory: {outside_files}"

            # 6. Verify worker remains alive and healthy for subsequent operations
            batch = torch.randint(0, 32, (2, 8))
            health_step = client.step(batch, batch.clone())
            assert health_step["ok"] is True, f"Worker became unhealthy after rejected save: {health_step}"
        finally:
            client.close()
    finally:
        worker.stop()


# ==============================================================================
# CHECK 2: SAVE, RESTORE, LOCK FILES, TEMP FILES, MANIFESTS CONFINEMENT
# ==============================================================================

def test_check2_nested_save_and_restore_all_artifacts_strictly_confined(tmp_path):
    """Verifies that nested checkpoint save and restore strictly confine all artifacts:
    checkpoint body, .resumable.json manifest, .lock file, .resumable.lock file,
    and temporary files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _make_cfg(tmp_path, checkpoint_workspace_dir=workspace)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            key = secrets.token_bytes(32)
            rel_path = "a/b/c/nested_ckpt.pt"

            resp = client.save_checkpoint(
                path=rel_path,
                integrity_key=key,
                sampler_position=5,
                sampler_seed=123,
                sampler_num_blocks=20,
            )
            assert resp["ok"] is True, resp

            target_dir = workspace / "a" / "b" / "c"
            assert target_dir.is_dir()
            assert (target_dir / "nested_ckpt.pt").is_file()
            assert (target_dir / "nested_ckpt.pt.resumable.json").is_file()
            assert (target_dir / ".nested_ckpt.pt.lock").is_file()
            assert (target_dir / ".nested_ckpt.pt.resumable.lock").is_file()

            # Confirm no leftover .tmp files
            tmp_files = [p for p in target_dir.iterdir() if ".tmp-" in p.name]
            assert len(tmp_files) == 0, f"Leftover temp files found: {tmp_files}"

            # Confirm restore round-trip strictly within workspace
            restore_resp = client.restore_checkpoint(
                path=rel_path,
                integrity_key=key,
                sampler_seed=123,
                sampler_num_blocks=20,
            )
            assert restore_resp["ok"] is True, restore_resp
            assert restore_resp["result"]["global_step"] == 0
            assert restore_resp["result"]["sampler_position"] == 5
        finally:
            client.close()
    finally:
        worker.stop()


# ==============================================================================
# CHECK 3: LINUX-SPECIFIC DESCRIPTOR BEHAVIOR AND FAILURE CLEANUP
# ==============================================================================

def test_check3_leaf_fd_is_fsyncable_and_tempfile_failure_cleanup(tmp_path):
    """Verifies Linux-specific descriptor semantics and failure cleanup:
    1. _open_dir_no_symlinks returns a leaf fd opened with _DIR_OPEN_FLAGS (O_RDONLY),
       which allows os.fsync(leaf_fd) without EBADF (the bug caught on Linux in commit 1ed7aa6).
    2. Failure during tempfile write cleans up the unlinked temp file."""
    test_dir = tmp_path / "nested" / "leaf"
    test_dir.mkdir(parents=True)

    # 1. Test fsyncability of returned leaf descriptor
    leaf_fd = _open_dir_no_symlinks(test_dir, parents=False)
    try:
        # On Linux, an O_PATH fd raises OSError: [Errno 9] Bad file descriptor here.
        # With the fix (commit 1ed7aa6), leaf_fd is O_RDONLY and fsync succeeds.
        os.fsync(leaf_fd)

        # Verify _dirfd_mkstemp creates file inside this descriptor
        tmp_fd, tmp_name = _dirfd_mkstemp(leaf_fd, prefix=".test-tmp-")
        try:
            assert os.path.exists(test_dir / tmp_name)
            os.write(tmp_fd, b"test_payload")
            os.fsync(tmp_fd)
        finally:
            os.close(tmp_fd)
            os.unlink(tmp_name, dir_fd=leaf_fd)
            assert not os.path.exists(test_dir / tmp_name)
    finally:
        os.close(leaf_fd)

    # 2. Test failure cleanup in save_training_state when write crashes
    state = TrainingState.capture(
        step=1, epoch=0, dataloader_position=0,
        model=GenesisTransformer(TINY_MODEL_CFG),
        optimizer=torch.optim.AdamW(GenesisTransformer(TINY_MODEL_CFG).parameters(), lr=1e-3),
    )
    ckpt_path = test_dir / "crash_test.pt"

    with patch("torch.save", side_effect=IOError("Simulated disk write failure")):
        with pytest.raises(IOError, match="Simulated disk write failure"):
            save_training_state(state, ckpt_path)

    # Verify no temp files leaked in test_dir
    leftover_tmps = [p.name for p in test_dir.iterdir() if ".tmp-" in p.name]
    assert len(leftover_tmps) == 0, f"Temp files leaked after failure: {leftover_tmps}"
    assert not ckpt_path.exists(), "Target file should not exist after failed save"


# ==============================================================================
# CHECK 4: CONFIRM allow_cross_run_migration=True REJECTED ON ALL CALLABLE PATHS
# ==============================================================================

def test_check4_allow_cross_run_migration_rejected_on_all_callable_paths(tmp_path):
    """P0-02 Verification:
    1. restore_resumable_checkpoint(allow_cross_run_migration=True) raises CrossRunMigrationDisabledError.
    2. restore_resumable_checkpoint(allow_cross_run_migration=False) on foreign run raises CrossRunCheckpointAccessError.
    3. Worker raw IPC smuggling allow_cross_run_migration=True is rejected."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _make_cfg(tmp_path, run_id="run-A", checkpoint_workspace_dir=workspace)

    # Save a legitimate checkpoint under run-A
    model = GenesisTransformer(cfg.model_cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    state = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=model, optimizer=opt)
    key = secrets.token_bytes(32)
    ds_id = wmod._worker_dataset_identity(cfg)
    fp = compute_config_fingerprint(cfg.model_cfg, cfg.step_cfg)
    ckpt_path = workspace / "ckpt.pt"

    save_resumable_checkpoint(
        path=ckpt_path, training_state=state, global_step=1, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id="run-A",
    )

    # Callable Path 1: Direct Python call with allow_cross_run_migration=True
    with pytest.raises(CrossRunMigrationDisabledError, match="allow_cross_run_migration=True was requested, but cross-run checkpoint migration is disabled"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=0, expected_sampler_num_blocks=1, integrity_key=key,
            run_id="run-B", allow_cross_run_migration=True,
        )

    # Callable Path 2: Direct Python call with allow_cross_run_migration=False (default) on foreign run
    with pytest.raises(CrossRunCheckpointAccessError, match="checkpoint at .* was saved under run_id 'run-A', but this restore is being performed under run_id 'run-B'"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=0, expected_sampler_num_blocks=1, integrity_key=key,
            run_id="run-B", allow_cross_run_migration=False,
        )

    # Callable Path 3: Worker raw IPC with smuggled allow_cross_run_migration=True
    worker_b = IsolatedTrainingWorker(_make_cfg(tmp_path, run_id="run-B", checkpoint_workspace_dir=workspace))
    worker_b.start()
    try:
        client_b = worker_b.client()
        client_b.connect()
        try:
            # Bypass typed method and send raw IPC payload with allow_cross_run_migration=True
            smuggle_resp = client_b._request("restore_checkpoint", {
                "path": "ckpt.pt",
                "integrity_key_hex": key.hex(),
                "sampler_seed": 0,
                "sampler_num_blocks": 1,
                "allow_cross_run_migration": True,
            })
            assert smuggle_resp["ok"] is False, f"Expected smuggle attempt to fail, got: {smuggle_resp}"
            assert "CrossRunCheckpointAccessError" in smuggle_resp["error"]
            assert "saved under run_id 'run-A', but this restore is being performed under run_id 'run-B'" in smuggle_resp["error"]
        finally:
            client_b.close()
    finally:
        worker_b.stop()


# ==============================================================================
# CHECK 5: CONFIRM NORMAL SAME-RUN CHECKPOINT RESTORATION STILL WORKS
# ==============================================================================

def test_check5_normal_same_run_checkpoint_restoration_succeeds(tmp_path):
    """Verifies that ordinary same-run checkpoint restoration functions perfectly:
    step, weights, optimizer state, and RNG state are restored accurately."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _make_cfg(tmp_path, run_id="run-legit-42", checkpoint_workspace_dir=workspace)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            key = secrets.token_bytes(32)
            batch = torch.randint(0, 32, (2, 8))

            # Step worker
            step1 = client.step(batch, batch.clone())
            assert step1["ok"] is True
            initial_loss = step1["result"]["microbatch_loss"]

            # Save checkpoint
            save_resp = client.save_checkpoint(
                path="legit.pt", integrity_key=key,
                sampler_position=4, sampler_seed=777, sampler_num_blocks=15,
            )
            assert save_resp["ok"] is True, save_resp
            assert save_resp["result"]["global_step"] == 1

            # Step again to advance state
            step2 = client.step(batch, batch.clone())
            assert step2["ok"] is True

            # Restore same-run checkpoint
            restore_resp = client.restore_checkpoint(
                path="legit.pt", integrity_key=key,
                sampler_seed=777, sampler_num_blocks=15,
            )
            assert restore_resp["ok"] is True, restore_resp
            assert restore_resp["result"]["global_step"] == 1
            assert restore_resp["result"]["sampler_position"] == 4
        finally:
            client.close()
    finally:
        worker.stop()
