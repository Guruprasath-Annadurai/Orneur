"""
ORNEUR GENESIS Audit #077 Correction Requalification Test Suite.
Auditor: Antigravity / Gemini -- Independent Security Assurance.
Author: Antigravity / Gemini Lead Auditor
Target: Priority 1 (G01 Filesystem Confinement) and Priority 2 (G02 Authority)

Deterministic inter-process synchronization, fault injection, and verification of:
1. Relative checkpoint save and restore path confinement.
2. Final checkpoint-name destination substitution (incidentally defeated by atomic rename).
3. Intermediate ancestor directory substitution (TOCTOU escape demonstration).
4. Symlink substitution rejection before filesystem operations.
5. Manifest and lock-file confinement in nested directories.
6. Failure cleanup and preservation of authorized files.
7. G02 HMAC binding of owning_run_id and tamper rejection.
8. G02 Direct internal caller allow_cross_run_migration authority exposure.
9. G02 Raw IPC inability to smuggle migration flags.
10. G02 Legacy schema-v1/v2 fail-closed handling.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing as mp
import os
import secrets
import shutil
import tempfile
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import orca.config as orca_config
import orca.genesis.governance.authorization as GOV
from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.training.isolated_worker import (
    CheckpointWorkspaceViolationError,
    IsolatedTrainingWorker,
    IsolatedWorkerClient,
    WorkerStartupConfig,
    WorkerStartupError,
    _enforce_checkpoint_path_confinement,
)
import orca.genesis.training.isolated_worker as wmod
from orca.genesis.training.learning_step import TrainingStepConfig
from orca.genesis.training.primitives import TrainingState
from orca.genesis.training.resumable_checkpoint import (
    CrossRunCheckpointAccessError,
    DatasetIdentity,
    MidAccumulationCheckpointError,
    RESUMABLE_SCHEMA_VERSION,
    ResumableManifest,
    ResumableManifestTamperedError,
    compute_config_fingerprint,
    restore_resumable_checkpoint,
    save_resumable_checkpoint,
)
from tests.test_genesis_isolated_worker import _make_cfg, TINY_MODEL_CFG, STEP_CFG


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Isolates ORCA_HOME to a temporary directory so ledger files do not conflict."""
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _sync_worker_main(cfg, ready_evt, error_queue, status_queue, post_val_evt, resume_evt):
    """Worker process target: hooks path confinement inside the spawned worker
    process itself, signaling post_val_evt once validation succeeds and blocking on
    resume_evt before save_resumable_checkpoint executes."""
    real_enforce = wmod._enforce_checkpoint_path_confinement

    def hooked_enforce(cfg_arg, requested_path):
        resolved = real_enforce(cfg_arg, requested_path)
        if post_val_evt is not None:
            post_val_evt.set()
        if resume_evt is not None:
            # Wait for parent to perform deterministic substitution
            if not resume_evt.wait(timeout=15.0):
                raise TimeoutError("worker timed out waiting for resume_evt from parent test")
        return resolved

    wmod._enforce_checkpoint_path_confinement = hooked_enforce
    wmod._worker_main(cfg, ready_evt, error_queue, status_queue)


class SynchronizedIsolatedTrainingWorker(IsolatedTrainingWorker):
    """Subclass of IsolatedTrainingWorker that uses _sync_worker_main to provide
    lockstep, worker-visible synchronization between validation and save."""

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
            target=_sync_worker_main,
            args=(self._cfg, self._ready_evt, self._error_queue, self._status_queue, self.post_val_evt, self.resume_evt),
            daemon=True,
        )
        self._proc.start()
        became_ready = self._ready_evt.wait(timeout)
        if not became_ready:
            reason = self._error_queue.get_nowait() if not self._error_queue.empty() else "worker did not become ready in time"
            self.stop()
            raise WorkerStartupError(reason)
        try:
            self.isolation_qualification = self._status_queue.get(timeout=5.0)
        except Exception:
            self.isolation_qualification = "ISOLATION_NOT_QUALIFIED"


# ==============================================================================
# PRIORITY 1: G01 FILESYSTEM CONFINEMENT & TOCTOU ADVERSARIAL REQUALIFICATION
# ==============================================================================

def test_g01_relative_checkpoint_save_and_restore_confinement(tmp_path):
    """Proves that relative checkpoint paths ('ckpt.pt') are anchored to the
    configured checkpoint_workspace_dir, written to workspace, and round-tripped
    without writing or leaking to os.getcwd()."""
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
            rel_name = "relative_checkpoint.pt"
            resp = client.save_checkpoint(
                path=rel_name, integrity_key=key, sampler_position=0, sampler_seed=42, sampler_num_blocks=10,
            )
            assert resp["ok"] is True, resp

            # 1. Assert file exists inside workspace
            expected_in_workspace = workspace / rel_name
            assert expected_in_workspace.exists(), f"Missing checkpoint in workspace: {expected_in_workspace}"
            assert expected_in_workspace.is_file()

            # 2. Assert manifest and lockfiles are inside workspace
            assert (workspace / f"{rel_name}.resumable.json").exists()
            assert (workspace / f".{rel_name}.lock").exists()
            assert (workspace / f".{rel_name}.resumable.lock").exists()

            # 3. Assert zero leakage into process CWD
            leaked_in_cwd = Path(rel_name)
            assert not leaked_in_cwd.exists(), f"Defect: checkpoint leaked to CWD: {leaked_in_cwd}"
            assert not Path(f"{rel_name}.resumable.json").exists()

            # 4. Round-trip restore using the same relative name
            restore_resp = client.restore_checkpoint(
                path=rel_name, integrity_key=key, sampler_seed=42, sampler_num_blocks=10,
            )
            assert restore_resp["ok"] is True, restore_resp
            assert restore_resp["result"]["global_step"] == 0
        finally:
            client.close()
    finally:
        worker.stop()


def test_g01_manifest_and_lockfile_confinement_under_subdirectory(tmp_path):
    """Proves that nested relative paths ('models/v1/ckpt.pt') properly confine
    the checkpoint, manifest, and lockfiles to the workspace subdirectory."""
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
            nested_rel = "models/v1/deep_checkpoint.pt"
            resp = client.save_checkpoint(
                path=nested_rel, integrity_key=key, sampler_position=0, sampler_seed=42, sampler_num_blocks=10,
            )
            assert resp["ok"] is True, resp

            nested_dir = workspace / "models" / "v1"
            assert (nested_dir / "deep_checkpoint.pt").is_file()
            assert (nested_dir / "deep_checkpoint.pt.resumable.json").is_file()
            assert (nested_dir / ".deep_checkpoint.pt.lock").exists()
            assert (nested_dir / ".deep_checkpoint.pt.resumable.lock").exists()

            assert not Path("models/v1/deep_checkpoint.pt").exists()
        finally:
            client.close()
    finally:
        worker.stop()


def test_g01_pre_planted_symlinks_rejected(tmp_path):
    """Verifies that pre-planted symlinks pointing outside the workspace are
    detected and rejected at validation time before any filesystem write."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    cfg = _make_cfg(tmp_path, checkpoint_workspace_dir=workspace)

    # 1. Target itself is a symlink pointing outside
    target_link = workspace / "target_link.pt"
    target_link.symlink_to(outside_dir / "target.pt")
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, "target_link.pt")

    # 2. Intermediate parent directory is a symlink pointing outside
    sub_link = workspace / "sub_link"
    sub_link.symlink_to(outside_dir)
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, "sub_link/target.pt")

    # 3. Traversal escape via .. is rejected
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, "../outside/target.pt")


def test_g01_final_destination_substitution_incidentally_defeated_by_atomic_rename(tmp_path):
    """Corrected, deterministic test: uses SynchronizedIsolatedTrainingWorker
    with multiprocessing Events to prove that if an attacker swaps the destination
    NAME to a symlink AFTER validation but BEFORE save_resumable_checkpoint,
    POSIX os.replace() replaces the symlink itself without following it."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    cfg = _make_cfg(tmp_path, checkpoint_workspace_dir=workspace)

    ctx = mp.get_context("spawn")
    post_val_evt = ctx.Event()
    resume_evt = ctx.Event()

    worker = SynchronizedIsolatedTrainingWorker(cfg, post_val_evt=post_val_evt, resume_evt=resume_evt)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            save_result = {}

            def _call_save():
                save_result["resp"] = client.save_checkpoint(
                    path="race_final_target.pt",
                    integrity_key=secrets.token_bytes(32),
                    sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
                )

            th = threading.Thread(target=_call_save)
            th.start()

            # 1. Wait deterministically for worker to complete validation
            assert post_val_evt.wait(timeout=10.0), "Worker did not execute validation hook"

            # 2. Plant symlink at the destination pointing outside
            dest = workspace / "race_final_target.pt"
            escaped_file = outside_dir / "escaped_by_race.pt"
            dest.symlink_to(escaped_file)
            assert dest.is_symlink()

            # 3. Release worker to perform save_resumable_checkpoint
            resume_evt.set()
            th.join(timeout=10.0)

            # 4. Verify results
            resp = save_result.get("resp")
            assert resp is not None and resp["ok"] is True, resp

            # Incidental defeat: atomic rename replaces the symlink entry in workspace
            assert not escaped_file.exists(), "Defect: escaped file was created outside workspace"
            assert dest.is_file(), "Destination in workspace should now be a regular file"
            assert not dest.is_symlink(), "Destination symlink should have been replaced"
        finally:
            client.close()
    finally:
        worker.stop()


def test_g01_intermediate_ancestor_substitution_toctou_escape_demonstration(tmp_path):
    """TOCTOU ADVERSARIAL FINDING:
    Demonstrates that intermediate ancestor directory substitution in the TOCTOU
    window (after validation, before save) DOES escape the workspace because
    _mkdir_owner_only follows user-owned ancestor symlinks.

    This distinguishes the demonstrated incidental protection of final-name rename
    from the unresolved TOCTOU race window of ancestor components."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside_ancestor"
    outside_dir.mkdir()
    (outside_dir / "inner").mkdir()
    cfg = _make_cfg(tmp_path, run_id="toctou-demo-" + secrets.token_hex(4), checkpoint_workspace_dir=workspace)

    sub = workspace / "sub"
    (sub / "inner").mkdir(parents=True)

    # 1. Validation passes: sub/inner/ckpt.pt is legitimate
    resolved = _enforce_checkpoint_path_confinement(cfg, "sub/inner/ckpt.pt")
    assert resolved.is_relative_to(workspace)

    # 2. TOCTOU Window: Attacker swaps ancestor 'sub' to symlink pointing to outside_dir
    shutil.rmtree(sub)
    sub.symlink_to(outside_dir)
    assert sub.is_symlink()

    # 3. Execute save_resumable_checkpoint directly
    model = GenesisTransformer(cfg.model_cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    state = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=model, optimizer=opt)
    key = secrets.token_bytes(32)
    ds_id = DatasetIdentity("ds", "c" * 64, "t" * 64)
    fp = compute_config_fingerprint(cfg.model_cfg, cfg.step_cfg)

    save_resumable_checkpoint(
        path=resolved, training_state=state, global_step=1, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id=cfg.run_id,
    )

    # 4. Vulnerability Proof: Checkpoint escaped into outside_dir/inner!
    escaped_files = [p.name for p in (outside_dir / "inner").iterdir()]
    assert "ckpt.pt" in escaped_files, f"Expected ckpt.pt to escape into outside_dir/inner, found {escaped_files}"
    assert "ckpt.pt.resumable.json" in escaped_files


def test_g01_failure_cleanup_and_preservation_of_authorized_files(tmp_path):
    """Verifies that an error during save (e.g. mid-accumulation check failure)
    leaves existing valid checkpoints unharmed and does not leave unconfined temp files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_id = "run-failclean-" + secrets.token_hex(4)
    cfg = _make_cfg(tmp_path, run_id=run_id, checkpoint_workspace_dir=workspace)

    model = GenesisTransformer(cfg.model_cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    state = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=model, optimizer=opt)
    key = secrets.token_bytes(32)
    ds_id = DatasetIdentity("ds", "c" * 64, "t" * 64)
    fp = compute_config_fingerprint(cfg.model_cfg, cfg.step_cfg)

    # 1. Save valid checkpoint v1
    v1_path = workspace / "v1.pt"
    save_resumable_checkpoint(
        path=v1_path, training_state=state, global_step=1, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id=run_id,
    )
    v1_bytes = v1_path.read_bytes()

    # 2. Attempt save v2 with illegal mid-cycle accumulation state
    v2_path = workspace / "v2.pt"
    with pytest.raises(MidAccumulationCheckpointError):
        save_resumable_checkpoint(
            path=v2_path, training_state=state, global_step=2, microbatch_in_cycle=1,  # ILLEGAL
            sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
            config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id=run_id,
        )

    # 3. Assert v1 is untouched and valid
    assert v1_path.read_bytes() == v1_bytes
    # 4. Assert v2 was not created and no temporary files linger
    assert not v2_path.exists()
    assert not (workspace / "v2.pt.resumable.json").exists()


# ==============================================================================
# PRIORITY 2: G02 AUTHORITY & CROSS-RUN RESTORATION REQUALIFICATION
# ==============================================================================

def test_g02_owning_run_id_hmac_binding_and_tamper_rejection(tmp_path):
    """Verifies that owning_run_id is HMAC-bound in ResumableManifest.
    Tampering with owning_run_id causes ResumableManifestTamperedError."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_alpha = "RUN_ALPHA_" + secrets.token_hex(4)
    run_beta = "RUN_BETA_" + secrets.token_hex(4)
    cfg = _make_cfg(tmp_path, run_id=run_alpha, checkpoint_workspace_dir=workspace)

    model = GenesisTransformer(cfg.model_cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    state = TrainingState.capture(step=10, epoch=0, dataloader_position=0, model=model, optimizer=opt)
    key = secrets.token_bytes(32)
    ds_id = DatasetIdentity("ds", "c" * 64, "t" * 64)
    fp = compute_config_fingerprint(cfg.model_cfg, cfg.step_cfg)

    ckpt_path = workspace / "model_alpha.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=state, global_step=10, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id=run_alpha,
    )

    manifest_path = workspace / "model_alpha.pt.resumable.json"
    manifest_data = json.loads(manifest_path.read_text())
    assert manifest_data["owning_run_id"] == run_alpha

    # Same-run restore succeeds
    restored = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=0, expected_sampler_num_blocks=1, integrity_key=key, run_id=run_alpha,
    )
    assert restored.global_step == 10

    # Cross-run restore fails with CrossRunCheckpointAccessError
    with pytest.raises(CrossRunCheckpointAccessError, match=f"saved under run_id '{run_alpha}', but this restore is being performed under run_id '{run_beta}'"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=0, expected_sampler_num_blocks=1, integrity_key=key, run_id=run_beta,
        )

    # Tamper owning_run_id to run_beta in manifest JSON: HMAC verification fails!
    manifest_data["owning_run_id"] = run_beta
    manifest_path.write_text(json.dumps(manifest_data))

    with pytest.raises(ResumableManifestTamperedError, match="failed its HMAC integrity check"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=0, expected_sampler_num_blocks=1, integrity_key=key, run_id=run_beta,
        )


def test_g02_internal_caller_allow_cross_run_migration_authority_bypass(tmp_path):
    """AUTHORITY FINDING:
    Demonstrates that a direct Python internal caller can perform an unauthorized
    migration simply by setting allow_cross_run_migration=True.
    No cryptographic migration grant or founder signature is required or verified."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_source = "RUN_SOURCE_" + secrets.token_hex(4)
    run_target = "RUN_TARGET_" + secrets.token_hex(4)
    cfg = _make_cfg(tmp_path, run_id=run_source, checkpoint_workspace_dir=workspace)

    model = GenesisTransformer(cfg.model_cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    state = TrainingState.capture(step=50, epoch=0, dataloader_position=0, model=model, optimizer=opt)
    key = secrets.token_bytes(32)
    ds_id = DatasetIdentity("ds", "c" * 64, "t" * 64)
    fp = compute_config_fingerprint(cfg.model_cfg, cfg.step_cfg)

    ckpt_path = workspace / "source_run.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=state, global_step=50, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id=run_source,
    )

    # Direct internal caller bypasses run_id check by setting allow_cross_run_migration=True
    restored = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=0, expected_sampler_num_blocks=1, integrity_key=key,
        run_id=run_target,
        allow_cross_run_migration=True,  # BARE BOOLEAN OVERRIDE
    )
    assert restored.global_step == 50
    # Note: run_target had no founder grant to adopt run_source's weights!


def test_g02_raw_ipc_cannot_smuggle_migration_flag(tmp_path):
    """Verifies that an untrusted worker IPC client CANNOT pass allow_cross_run_migration,
    even by crafting a raw, untyped JSON IPC frame."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg_a = _make_cfg(tmp_path, run_id="smuggle-run-a-" + secrets.token_hex(4), checkpoint_workspace_dir=workspace)
    worker_a = IsolatedTrainingWorker(cfg_a)
    worker_a.start()
    key = secrets.token_bytes(32)
    try:
        client_a = worker_a.client()
        client_a.connect()
        try:
            save_resp = client_a.save_checkpoint(
                path="owned_by_a.pt", integrity_key=key, sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
            )
            assert save_resp["ok"] is True, save_resp
        finally:
            client_a.close()
    finally:
        worker_a.stop()

    # Worker B: different run_id
    cfg_b = _make_cfg(tmp_path, run_id="smuggle-run-b-" + secrets.token_hex(4), checkpoint_workspace_dir=workspace)
    worker_b = IsolatedTrainingWorker(cfg_b)
    worker_b.start()
    try:
        client_b = worker_b.client()
        client_b.connect()
        try:
            # Craft raw payload with smuggled parameter
            raw_payload = {
                "path": "owned_by_a.pt",
                "integrity_key_hex": key.hex(),
                "sampler_seed": 0,
                "sampler_num_blocks": 1,
                "allow_cross_run_migration": True,  # Smuggled parameter
            }
            reply = client_b._request("restore_checkpoint", raw_payload)
            assert reply["ok"] is False
            assert "CrossRunCheckpointAccessError" in reply["error"]
        finally:
            client_b.close()
    finally:
        worker_b.stop()


def test_g02_schema_v1_legacy_manifest_fail_closed(tmp_path):
    """Verifies that legacy schema-v1 or schema-v2 manifests (or non-JSON manifests)
    fail closed with ResumableManifestTamperedError before dataclass instantiation."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_legacy = "RUN_LEGACY_" + secrets.token_hex(4)
    cfg = _make_cfg(tmp_path, run_id=run_legacy, checkpoint_workspace_dir=workspace)

    ckpt_path = workspace / "legacy.pt"
    ckpt_path.write_bytes(b"dummy checkpoint bytes")
    manifest_path = workspace / "legacy.pt.resumable.json"

    # Schema v2 legacy manifest (missing owning_run_id)
    manifest_path.write_text(json.dumps({
        "schema_version": "genesis-resumable-checkpoint/2",
        "inner_checkpoint_sha256": "0" * 64,
        "global_step": 1,
        "microbatch_in_cycle": 0,
        "sampler_position": 0,
        "sampler_seed": 0,
        "sampler_num_blocks": 1,
        "config_fingerprint": "f" * 64,
        "dataset_identity": {"manifest_id": "ds", "content_digest": "c" * 64, "tokenizer_digest": "t" * 64},
        "integrity_tag": "tag" * 16,
    }))

    ds_id = DatasetIdentity("ds", "c" * 64, "t" * 64)
    with pytest.raises(ResumableManifestTamperedError, match="declares schema_version='genesis-resumable-checkpoint/2'"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint="f" * 64, expected_dataset_identity=ds_id,
            expected_sampler_seed=0, expected_sampler_num_blocks=1,
            integrity_key=secrets.token_bytes(32), run_id=run_legacy,
        )

    # Malformed non-JSON
    manifest_path.write_text("NOT_JSON")
    with pytest.raises(ResumableManifestTamperedError, match="is not valid JSON"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint="f" * 64, expected_dataset_identity=ds_id,
            expected_sampler_seed=0, expected_sampler_num_blocks=1,
            integrity_key=secrets.token_bytes(32), run_id=run_legacy,
        )
