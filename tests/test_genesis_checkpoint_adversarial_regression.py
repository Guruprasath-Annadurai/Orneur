"""
ORNEUR GENESIS Native Learning Engine -- Checkpoint & Authorization Adversarial Regression Test Suite.
Auditor/Author: Antigravity / Gemini -- Independent Security, Research & Model Assurance Lead.
Target: Priority 2 -- GENESIS Checkpoint and Authorization Boundary Regressions.

Adversarial Tests Covering:
1. G01: Checkpoint Path Confinement & Workspace Escape Discrepancy
   - Defect Reproduction: Relative path validation discrepancy where `_enforce_checkpoint_path_confinement`
     validates `workspace / path`, but the worker calls `save_resumable_checkpoint(path=Path(payload["path"]))`,
     causing writes to land in `os.getcwd()` outside `checkpoint_workspace_dir`.
   - Absolute path escape outside workspace rejected.
   - Parent directory traversal (../outside.pt) rejected.
   - Pre-planted symlinks inside workspace pointing outside rejected.
   - Worker live IPC execution with relative path reproducing the workspace escape.
2. G02: Cross-Run Checkpoint Authority & Scope Limitation
   - Checkpoint manifest HMAC tag scope analysis: `run_id` is NOT bound in `tagged_fields`.
   - Cross-run restore reproduction: Run A's checkpoint restored into Run B without migration grant.
   - Monotonic ledger isolation: Run B's ledger is separate from Run A's ledger, allowing unvetted migration.
3. G03: Integrity-Key Custody & Anti-Rollback Threat Model
   - Worker blind trust of client-supplied integrity key (no founder key binding).
   - Local ledger simultaneous rollback replay reproduction.
"""
from __future__ import annotations

import os
import secrets
import tempfile
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
    WorkerStartupConfig,
    _enforce_checkpoint_path_confinement,
)
from orca.genesis.training.learning_step import TrainingStepConfig
from orca.genesis.training.primitives import TrainingState
from orca.genesis.training.resumable_checkpoint import (
    CheckpointRollbackError,
    DatasetIdentity,
    RESUMABLE_SCHEMA_VERSION,
    ResumableManifest,
    WeakIntegrityKeyError,
    compute_config_fingerprint,
    restore_resumable_checkpoint,
    save_resumable_checkpoint,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"
VOCAB = 32
SEQ_LEN = 16

TINY_MODEL_CFG = GenesisModelConfig(
    vocab_size=VOCAB,
    d_model=16,
    n_layers=2,
    n_heads=2,
    n_kv_heads=1,
    d_ff=32,
    max_seq_len=SEQ_LEN,
)

STEP_CFG = TrainingStepConfig(
    grad_accum_steps=1,
    warmup_steps=2,
    total_steps=50,
    max_lr=1e-2,
)


def _digest(label: str) -> str:
    import hashlib
    return hashlib.sha256(label.encode()).hexdigest()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_head() -> str:
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    return p.stdout.strip() if p.returncode == 0 else "0" * 40


HEAD_SHA = _git_head()


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _make_worker_startup_cfg(tmp_path: Path, *, run_id: str | None = None, checkpoint_workspace_dir: Path | None = None) -> WorkerStartupConfig:
    import hashlib
    mcfg, tcd, ocd = (_digest(x) for x in ("mcfg", "tcd", "ocd"))
    tok_digest = _digest("tok")
    dataset_digest = _digest("dataset")
    shard_dir = tmp_path / "worker_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "worker genesis regression fixture shard"}\n')
    authorized_shard_digests = (hashlib.sha256(shard_file.read_bytes()).hexdigest(),)

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    now = datetime.now(timezone.utc)
    registry = {
        "schema_version": GOV.REGISTRY_SCHEMA_VERSION,
        "records": [{
            "id": "gov-worker-authority", "role": "OWNER", "public_key_hex": pub,
            "activation_timestamp": _ts(now - timedelta(days=1)), "expiry": None, "revoked": False,
            "gpu_permission": False, "spend_permission": False,
        }],
    }
    actual_run_id = run_id or f"worker-regress-{secrets.token_hex(4)}"
    req = GOV.NativePretrainingRequest(
        run_id=actual_run_id, nonce=_digest(f"nonce-{actual_run_id}"), model_family="genesis",
        architecture_version="genesis-arch-v1", model_config_digest=mcfg, tokenizer_digest=tok_digest,
        dataset_manifest_id="iso-worker-manifest", dataset_content_digest=dataset_digest,
        authorized_shard_digests=authorized_shard_digests, reviewed_commit_sha=HEAD_SHA,
        transformation_code_digest=tcd, optimizer_config_digest=ocd, environment_class=ENV, gpu_requested=False,
        max_wall_clock_minutes=60, requested_spend_usd=0.0,
    )
    record = {
        "schema_version": GOV.SCHEMA_VERSION, "authorization_id": f"gnpauth-{secrets.token_hex(8)}",
        "status": "AUTHORIZED", "run_id": req.run_id, "nonce": req.nonce,
        "model": {"family": req.model_family, "architecture_version": req.architecture_version, "model_config_digest": req.model_config_digest},
        "tokenizer": {"tokenizer_digest": req.tokenizer_digest},
        "dataset": {"dataset_manifest_id": req.dataset_manifest_id, "dataset_content_digest": req.dataset_content_digest, "authorized_shard_digests": list(req.authorized_shard_digests)},
        "code": {"reviewed_commit_sha": req.reviewed_commit_sha, "transformation_code_digest": req.transformation_code_digest},
        "training": {"optimizer_config_digest": req.optimizer_config_digest},
        "environment_class": req.environment_class,
        "limits": {"max_wall_clock_minutes": 120, "max_spend_usd": 0, "gpu_allowed": False},
        "issued_at": _ts(now - timedelta(minutes=1)), "expires_at": _ts(now + timedelta(hours=2)),
        "authorizing_authority": {"identity": "gov-worker-authority", "role": "OWNER", "key_id": "gov-worker-authority"},
        "signature": None,
    }
    record["signature"] = priv.sign(GOV.canonical_signing_bytes(record)).hex()

    sock_dir = Path(tempfile.mkdtemp(prefix="isow-regr-"))
    os.chmod(sock_dir, 0o700)

    revoked_ids_path = tmp_path / "revoked_worker.json"
    revoked_ids_path.write_text("[]")
    pinned_registry_sha256 = GOV.registry_digest(registry)

    return WorkerStartupConfig(
        workload_id=actual_run_id,
        auth_token=secrets.token_bytes(32),
        sock_path=str(sock_dir / "worker.sock"),
        model_cfg=TINY_MODEL_CFG,
        step_cfg=STEP_CFG,
        run_id=actual_run_id,
        dataset_manifest_ids=("iso-worker-manifest",),
        environment_class=ENV,
        repo_root=str(REPO_ROOT),
        dataset_digest=dataset_digest,
        model_config_digest=mcfg,
        tokenizer_digest=tok_digest,
        authorized_shard_digests=authorized_shard_digests,
        shard_dir=str(shard_dir),
        reviewed_commit_sha=req.reviewed_commit_sha,
        transformation_code_digest=tcd,
        optimizer_config_digest=ocd,
        record=record,
        registry=registry,
        req=req,
        revoked_ids_path=str(revoked_ids_path),
        drop_to_uid=None,
        checkpoint_workspace_dir=checkpoint_workspace_dir,
        orca_home_override=str(tmp_path / "ornhome"),
        test_only_bypass_founder_ledger=True,
        test_only_pinned_registry_sha256=pinned_registry_sha256,
    )


# ==============================================================================
# G01: Checkpoint Path Confinement & Workspace Escape Discrepancy
# ==============================================================================

def test_g01_checkpoint_path_confinement_relative_path_discrepancy(tmp_path):
    """CONFIRMED DEFECT REPRODUCTION (G01):
    `_enforce_checkpoint_path_confinement` validates `(workspace / requested_path).resolve()`,
    but does NOT return it or re-bind it.
    When a client provides a relative path like `ckpt.pt`, `_enforce_checkpoint_path_confinement`
    passes because `workspace / ckpt.pt` is inside `workspace`.
    However, the worker then passes `path=Path(payload["path"])` (a relative path) to `save_resumable_checkpoint()`.
    Inside `save_resumable_checkpoint()`, `path.parent` resolves to `.` (the process working directory),
    meaning files are written to `os.getcwd()` OUTSIDE the configured checkpoint workspace!
    """
    workspace = tmp_path / "authorized_workspace"
    workspace.mkdir()
    cfg = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=workspace)

    relative_requested_path = "escaped_checkpoint.pt"

    # Step 1: Confinement check passes because it constructs (workspace / relative_requested_path)
    _enforce_checkpoint_path_confinement(cfg, relative_requested_path)

    # Step 2: Show the discrepancy: what the worker actually executes vs what it validated
    validated_path = (workspace / relative_requested_path).resolve()
    used_path = Path(relative_requested_path).resolve()

    # The validated path is in workspace, but the used path is in os.getcwd()!
    assert validated_path.parent == workspace.resolve()
    assert used_path.parent == Path(os.getcwd()).resolve()
    assert validated_path != used_path, (
        f"Path mismatch defect confirmed: validated {validated_path} != used {used_path}"
    )


def test_g01_checkpoint_path_confinement_directory_traversal_and_absolute_escapes(tmp_path):
    """Test standard boundary rejections in _enforce_checkpoint_path_confinement."""
    workspace = tmp_path / "authorized_ws"
    workspace.mkdir()
    outside = tmp_path / "outside_ws"
    outside.mkdir()

    cfg = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=workspace)

    # 1. Directory traversal escape
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, "../outside_ws/ckpt.pt")

    # 2. Absolute path escape
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, str(outside / "ckpt.pt"))

    # 3. Pre-existing symlink escape
    symlink_target = workspace / "escape_symlink"
    symlink_target.symlink_to(outside)
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, "escape_symlink/target.pt")

    # 4. Unconfigured workspace fail-closed
    cfg_none = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=None)
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg_none, "anything.pt")


def test_g01_dynamic_symlink_substitution_toctou(tmp_path):
    """ADVERSARIAL REPRODUCTION (G01 - TOCTOU Symlink Window):
    Demonstrates that merely resolving a path string once before file creation does not prevent
    a Time-of-Check to Time-of-Use (TOCTOU) race if a directory component inside workspace
    can be swapped for a symlink pointing outside the workspace.
    """
    workspace = tmp_path / "authorized_ws"
    workspace.mkdir()
    outside = tmp_path / "outside_target"
    outside.mkdir()

    cfg = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=workspace)

    sub_dir = workspace / "sub"
    sub_dir.mkdir()

    # Step 1: Check passes when sub is a valid directory
    relative_target = "sub/checkpoint.pt"
    _enforce_checkpoint_path_confinement(cfg, relative_target)

    # Step 2: Attacker replaces sub_dir with a symlink to outside directory
    sub_dir.rmdir()
    sub_dir.symlink_to(outside)

    # Step 3: A subsequent open/write following standard path resolution would write outside!
    resolved_now = (workspace / relative_target).resolve()
    assert resolved_now.is_relative_to(outside.resolve()), (
        "TOCTOU demonstrated: dynamic symlink swap redirected target outside workspace"
    )


def test_g01_worker_ipc_vulnerability_demonstration_relative_path_escapes_to_cwd(tmp_path):
    """ADVERSARIAL REPRODUCTION (G01 - Live Isolated Worker IPC):
    Demonstrates the live defect over Unix domain socket IPC:
    When a client commands the isolated worker to save with a relative path 'ipc_leak.pt',
    the worker's handler validates (workspace / 'ipc_leak.pt'), but passes Path('ipc_leak.pt')
    to save_resumable_checkpoint.
    Result: The worker reports ok:True, but the checkpoint and manifest are written to
    os.getcwd() (the repository root), escaping the authorized workspace directory!
    """
    workspace = tmp_path / "authorized_ipc_ws"
    workspace.mkdir()
    cfg = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=workspace)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()

    rel_name = "ipc_leak_demonstration.pt"
    try:
        client = worker.client()
        client.connect()
        try:
            resp = client.save_checkpoint(
                path=rel_name,
                integrity_key=secrets.token_bytes(32),
                sampler_position=0,
                sampler_seed=0,
                sampler_num_blocks=1,
            )
            # The worker reports success
            assert resp["ok"] is True, f"Worker unexpectedly rejected relative path: {resp}"

            # VULNERABILITY PROOF:
            # 1. Checkpoint was NOT written to the authorized workspace:
            assert not (workspace / rel_name).exists(), "File should not exist in workspace on vulnerable code"
            # 2. Checkpoint WAS leaked into os.getcwd() (repository root):
            leaked_in_cwd = Path(rel_name)
            assert leaked_in_cwd.exists(), "Defect confirmed: file was leaked into process CWD"
        finally:
            client.close()
    finally:
        worker.stop()
        # Clean up any leaked artifacts in CWD
        for suffix in ("", ".resumable.json", ".lock", ".resumable.lock"):
            f = Path(f"{rel_name}{suffix}")
            if f.exists():
                try: f.unlink()
                except OSError: pass
            f_dot = Path(f".{rel_name}{suffix}")
            if f_dot.exists():
                try: f_dot.unlink()
                except OSError: pass


@pytest.mark.xfail(
    reason="Fix-acceptance test for G01: fails on current vulnerable worker because relative paths write to os.getcwd() instead of workspace",
    strict=True,
)
def test_g01_fix_acceptance_worker_confinement_desired_behavior(tmp_path):
    """FIX-ACCEPTANCE TEST (G01):
    Desired Safe Behavior: When a relative path 'ipc_safe_target.pt' is commanded to the worker,
    the checkpoint and manifest MUST be created inside cfg.checkpoint_workspace_dir, and MUST NOT
    be created in os.getcwd().

    Fails on current vulnerable worker implementation (where file lands in os.getcwd()).
    """
    workspace = tmp_path / "workspace_fix_acceptance"
    workspace.mkdir()
    cfg = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=workspace)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()

    rel_name = "ipc_safe_target.pt"
    try:
        client = worker.client()
        client.connect()
        try:
            resp = client.save_checkpoint(
                path=rel_name,
                integrity_key=secrets.token_bytes(32),
                sampler_position=0,
                sampler_seed=0,
                sampler_num_blocks=1,
            )
            assert resp["ok"] is True

            # DESIRED SAFE BEHAVIOR:
            target_in_workspace = workspace / rel_name
            target_in_cwd = Path(rel_name)

            assert target_in_workspace.exists(), (
                f"DESIRED SAFE BEHAVIOR: Checkpoint must exist at {target_in_workspace}, but does not!"
            )
            assert not target_in_cwd.exists(), (
                f"DESIRED SAFE BEHAVIOR: Checkpoint must NOT exist in CWD {target_in_cwd}, but does!"
            )
        finally:
            client.close()
    finally:
        worker.stop()
        for suffix in ("", ".resumable.json", ".lock", ".resumable.lock"):
            f = Path(f"{rel_name}{suffix}")
            if f.exists():
                try: f.unlink()
                except OSError: pass
            f_dot = Path(f".{rel_name}{suffix}")
            if f_dot.exists():
                try: f_dot.unlink()
                except OSError: pass


# ==============================================================================
# G02: Cross-Run Checkpoint Authority
# ==============================================================================

def test_g02_ordinary_same_run_restore_succeeds(tmp_path):
    """SPECIFICATION & REGRESSION (G02):
    Ordinary same-run checkpoint save and restore within the same logical run_id is authorized
    and must succeed deterministically.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    ckpt_dir = tmp_path / "same_run_ckpts"
    ckpt_dir.mkdir()
    key = secrets.token_bytes(32)
    ds_id = DatasetIdentity("same-run", _digest("dataset"), _digest("tokenizer"))
    fp = compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG)

    state = TrainingState.capture(step=10, epoch=0, dataloader_position=100, model=model, optimizer=opt)
    ckpt_path = ckpt_dir / "step10.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=state, global_step=10, microbatch_in_cycle=0,
        sampler_position=100, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id="RUN_SAME",
    )

    # Same-run restore succeeds
    restored = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=100,
        integrity_key=key, run_id="RUN_SAME",
    )
    assert restored.global_step == 10
    assert restored.sampler_position == 100


def test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration(tmp_path):
    """ADVERSARIAL REPRODUCTION (G02):
    Demonstrates the confirmed vulnerability on current HEAD:
    Because `run_id` is omitted from `ResumableManifest` HMAC-tagged fields,
    Run B can restore Run A's checkpoint without explicit migration authorization.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    ckpt_dir = tmp_path / "ckpts"
    ckpt_dir.mkdir()

    key = secrets.token_bytes(32)
    ds_id = DatasetIdentity("cross-run-manifest", _digest("dataset"), _digest("tokenizer"))
    fp = compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG)

    # Run A saves checkpoint at step 15
    state_a = TrainingState.capture(step=15, epoch=0, dataloader_position=150, model=model, optimizer=opt)
    ckpt_path = ckpt_dir / "checkpoint_run_a.pt"
    manifest = save_resumable_checkpoint(
        path=ckpt_path, training_state=state_a, global_step=15, microbatch_in_cycle=0,
        sampler_position=150, sampler_seed=42, sampler_num_blocks=200,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id="RUN_ALPHA",
    )

    # Prove structurally that run_id is omitted from tagged_fields
    tagged_dict = manifest._tagged_fields_dict()
    assert "run_id" not in tagged_dict, "run_id must be absent from tagged_dict"

    # Now Run B (RUN_BETA) attempts restore with its OWN run_id
    restored_in_run_b = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=200,
        integrity_key=key, run_id="RUN_BETA",  # Different run ID!
    )
    # Cross-run restore succeeds on current vulnerable code without a migration receipt!
    assert restored_in_run_b.global_step == 15


@pytest.mark.xfail(
    reason="Fix-acceptance test for G02: fails on current vulnerable resumable_checkpoint because cross-run restore does not raise authority mismatch exception",
    strict=True,
)
def test_g02_fix_acceptance_cross_run_restore_without_migration_denied(tmp_path):
    """FIX-ACCEPTANCE TEST (G02):
    Desired Safe Behavior: Restoring a checkpoint saved under Run A into an unrelated Run B
    without an explicit migration grant MUST be rejected by raising an actual authority
    mismatch or tamper exception from the restoration implementation.

    No substitute exception is raised inside the test itself. Fails on current code because
    restore_resumable_checkpoint succeeds without error.
    """
    from orca.genesis.training.resumable_checkpoint import ResumableManifestTamperedError

    model = GenesisTransformer(TINY_MODEL_CFG)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    ckpt_dir = tmp_path / "g02_fix_ckpts"
    ckpt_dir.mkdir()
    key = secrets.token_bytes(32)
    ds_id = DatasetIdentity("g02-fix", _digest("dataset"), _digest("tokenizer"))
    fp = compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG)

    state_a = TrainingState.capture(step=20, epoch=0, dataloader_position=200, model=model, optimizer=opt)
    ckpt_path = ckpt_dir / "checkpoint_run_a.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=state_a, global_step=20, microbatch_in_cycle=0,
        sampler_position=200, sampler_seed=42, sampler_num_blocks=200,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id="RUN_ALPHA",
    )

    # Desired safe behavior: restore_resumable_checkpoint must raise an authority mismatch
    # or manifest tamper exception when called with a different run_id.
    # Note: On current vulnerable code, this does NOT raise, causing pytest.raises to fail (XFAIL).
    with pytest.raises((ResumableManifestTamperedError, PermissionError)):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=42, expected_sampler_num_blocks=200,
            integrity_key=key, run_id="RUN_BETA",
        )


# ==============================================================================
# G03: Integrity-Key Custody & Anti-Rollback Threat Model
# ==============================================================================

def test_g03_integrity_key_custody_and_local_ledger_replay_limitation(tmp_path):
    """ADVERSARIAL REPRODUCTION (G03):
    1. Weak key rejection: keys shorter than 32 bytes are rejected.
    2. Local filesystem replay limitation: An attacker with filesystem access can save a backup
       of an older valid checkpoint + manifest + matching ledger file, and restore both simultaneously.
       Because all three live on the same local filesystem, the local HMAC-tagged ledger cannot detect
       a synchronized rollback to an older state.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    ckpt_dir = tmp_path / "g03_ckpts"
    ckpt_dir.mkdir()
    fp = compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG)
    ds_id = DatasetIdentity("g03-manifest", _digest("dataset"), _digest("tokenizer"))

    # 1. Weak key rejection
    weak_key = b"short_key_16_byt"
    state = TrainingState.capture(step=1, epoch=0, dataloader_position=10, model=model, optimizer=opt)
    with pytest.raises(WeakIntegrityKeyError):
        save_resumable_checkpoint(
            path=ckpt_dir / "weak.pt", training_state=state, global_step=1, microbatch_in_cycle=0,
            sampler_position=10, sampler_seed=42, sampler_num_blocks=100,
            config_fingerprint=fp, dataset_identity=ds_id, integrity_key=weak_key, run_id="g03_run",
        )

    # 2. Local ledger simultaneous replay reproduction
    strong_key = secrets.token_bytes(32)
    state_step5 = TrainingState.capture(step=5, epoch=0, dataloader_position=50, model=model, optimizer=opt)
    ckpt_step5 = ckpt_dir / "step5.pt"
    save_resumable_checkpoint(
        path=ckpt_step5, training_state=state_step5, global_step=5, microbatch_in_cycle=0,
        sampler_position=50, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=strong_key, run_id="g03_run",
    )

    # Backup the step 5 ledger and checkpoint files
    import shutil
    from orca.genesis.training.resumable_checkpoint import _ledger_path
    ledger_path = _ledger_path("g03_run")
    backup_dir = tmp_path / "backup_step5"
    backup_dir.mkdir()
    shutil.copy(ledger_path, backup_dir / "ledger.json")
    shutil.copy(ckpt_step5, backup_dir / "step5.pt")
    shutil.copy(ckpt_dir / "step5.pt.resumable.json", backup_dir / "step5.pt.resumable.json")

    # Run advances to step 100
    state_step100 = TrainingState.capture(step=100, epoch=0, dataloader_position=1000, model=model, optimizer=opt)
    ckpt_step100 = ckpt_dir / "step100.pt"
    save_resumable_checkpoint(
        path=ckpt_step100, training_state=state_step100, global_step=100, microbatch_in_cycle=0,
        sampler_position=1000, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=strong_key, run_id="g03_run",
    )

    # An ordinary restore of step 5 fails with CheckpointRollbackError because ledger is at 100
    with pytest.raises(CheckpointRollbackError):
        restore_resumable_checkpoint(
            path=ckpt_step5, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=42, expected_sampler_num_blocks=100,
            integrity_key=strong_key, run_id="g03_run",
        )

    # Attacker with local filesystem write access simultaneously replays step 5 checkpoint + ledger
    shutil.copy(backup_dir / "ledger.json", ledger_path)

    # Now the restore succeeds because the local ledger was rolled back in lockstep
    restored_replayed = restore_resumable_checkpoint(
        path=ckpt_step5, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=100,
        integrity_key=strong_key, run_id="g03_run",
    )
    assert restored_replayed.global_step == 5, "Replayed older checkpoint accepted when ledger was simultaneously rolled back"
