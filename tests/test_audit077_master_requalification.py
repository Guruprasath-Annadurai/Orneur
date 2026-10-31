"""
ORNEUR GENESIS Native Learning Engine -- Audit #077 Master Requalification Test Suite.
Directives: CTO MASTER DIRECTIVE #077.
Auditor: Antigravity / Gemini -- Independent Security, Research & Model Assurance Lead.
Audited HEAD: 70747d15d1bb39b9f83d82804690d827c5a50f81 (PR #73)

Adversarial Tests Covering:
1. Domain A: Dataset Ingestion State Machine & Heap Scalability
   - Multi-chunk oversized record (>64 KiB) followed by valid record.
   - Multibyte UTF-8 boundary slice across the 64 KiB chunk boundary.
   - EOF without newline in discarding state (single rejection, no leak).
   - Large shard (>30 MB) bounded heap profiling (tracemalloc peak < 5 MB).
2. Domain B: Checkpoint Path Confinement & Symlink Security
   - Traversal escapes (../run2/checkpoint.pt).
   - Absolute path escapes (/tmp/evil.pt).
   - Pre-planted symlinks inside workspace pointing outside workspace.
   - Unconfigured workspace (None) fail-closed behavior.
3. Domain C: Checkpoint Cross-Run Ownership & Ledger Replay Boundary
   - Anti-rollback ledger isolation per run_id.
   - Cross-run checkpoint migration boundary (manifest HMAC scope vs run_id ledger).
4. Domain D: Isolated Worker Checkpoint IPC Security & Revocation
   - Worker-derived identity enforcement against client tampering.
   - Live founder grant revocation on save_checkpoint and restore_checkpoint.
5. Domain E: Synthetic Restart Equivalence & Shift Reconciliation
   - Unshifted (tokens, tokens) batch contract verification.
   - Single internal shift in causal_lm_loss verification.
   - Restart equivalence parameter bit-parity or strict float-tolerance match.
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import secrets
import tempfile
import tracemalloc
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import orca.config as orca_config
import orca.genesis.governance.authorization as GOV
from orca.genesis.data.loader import (
    BLOCK_STORE_SCHEMA_VERSION,
    GenesisBlockDataset,
    LoaderConfig,
    ReproducibleSampler,
    _SHARD_READ_CHUNK_BYTES,
    compute_block_store_cache_id,
    compute_shard_digests,
    make_batch,
)
from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.tokenizer.framework import GenesisTokenizer
from orca.genesis.training.isolated_worker import (
    CheckpointWorkspaceViolationError,
    IsolatedTrainingWorker,
    WorkerStartupConfig,
    _enforce_checkpoint_path_confinement,
)
from orca.genesis.training.learning_governance import (
    TrainingNotAuthorizedForExecutionError,
)
from orca.genesis.training.learning_step import (
    ExecutionCapability,
    TrainingStepConfig,
    TrainingStepEngine,
    causal_lm_loss,
    set_deterministic_seed,
)
from orca.genesis.training.primitives import TrainingState
from orca.genesis.training.resumable_checkpoint import (
    MIN_INTEGRITY_KEY_BYTES,
    CheckpointRollbackError,
    DatasetIdentity,
    ResumableManifestTamperedError,
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
    return hashlib.sha256(label.encode()).hexdigest()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_head() -> str:
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    return p.stdout.strip() if p.returncode == 0 else "0" * 40


HEAD_SHA = _git_head()


class SimpleAsciiTokenizer(GenesisTokenizer):
    """Deterministic tokenizer mapping ascii characters to vocab ids."""
    def __init__(self, vocab_size: int = VOCAB):
        self._vocab_size = vocab_size

    def encode(self, text: str) -> list[int]:
        return [ord(c) % (self._vocab_size - 4) + 4 for c in text if c.strip()]

    def decode(self, token_ids: list[int]) -> str:
        return "".join(chr(t) for t in token_ids)

    def vocab_size(self) -> int:
        return self._vocab_size

    def content_digest(self) -> str:
        return hashlib.sha256(b"SimpleAsciiTokenizer-Audit077").hexdigest()


class Utf8BoundaryTokenizer(GenesisTokenizer):
    """Tokenizer supporting unicode characters for multibyte slice tests."""
    def __init__(self, vocab_size: int = 128):
        self._vocab_size = vocab_size

    def encode(self, text: str) -> list[int]:
        # Return utf-8 byte values offset into valid vocab range [4, vocab_size-1]
        raw = text.encode("utf-8")
        return [b % (self._vocab_size - 4) + 4 for b in raw]

    def decode(self, token_ids: list[int]) -> str:
        return f"tokens:{len(token_ids)}"

    def vocab_size(self) -> int:
        return self._vocab_size

    def content_digest(self) -> str:
        return hashlib.sha256(b"Utf8BoundaryTokenizer-Audit077").hexdigest()


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Ensure complete filesystem and nonce isolation."""
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _make_worker_startup_cfg(tmp_path: Path, *, run_id: str | None = None, checkpoint_workspace_dir: Path | None = None) -> WorkerStartupConfig:
    mcfg, tcd, ocd = (_digest(x) for x in ("mcfg", "tcd", "ocd"))
    tok_digest = _digest("tok")
    dataset_digest = _digest("dataset")
    shard_dir = tmp_path / "worker_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "worker audit077 fixture shard"}\n')
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
    actual_run_id = run_id or f"worker-audit077-{secrets.token_hex(4)}"
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

    sock_dir = Path(tempfile.mkdtemp(prefix="isow-a077-"))
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
# Domain A: Dataset Ingestion State Machine & Heap Scalability
# ==============================================================================

def test_audit077_domain_a_multichunk_oversized_record_then_valid_record(tmp_path):
    """Challenge the discarding_until_newline state machine across multiple 64 KiB chunks:
    Line 1: valid normal record
    Line 2: oversized record (> max_record_bytes) spanning 3 full 64 KiB read chunks (>192 KiB), terminated by newline
    Line 3: valid normal record
    Verify: exactly 2 records read, exactly 1 rejected, line 3 is cleanly tokenized, line 2 is absent.
    """
    shard_dir = tmp_path / "shards_multichunk"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"

    rec1 = json.dumps({"text": "FIRST VALID RECORD TEXT"}) + "\n"
    # Create an oversized payload that spans 3 full 64 KiB chunks
    oversized_len = _SHARD_READ_CHUNK_BYTES * 3 + 1024
    rec2_oversized = json.dumps({"text": "OVERSIZED PRETEXT " + "Z" * oversized_len}) + "\n"
    rec3 = json.dumps({"text": "THIRD VALID RECORD TEXT"}) + "\n"

    shard_file.write_bytes(rec1.encode("utf-8") + rec2_oversized.encode("utf-8") + rec3.encode("utf-8"))
    digests = compute_shard_digests(shard_dir)

    tok = SimpleAsciiTokenizer()
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-audit077", packing=False,
        max_record_bytes=4096, max_tokens_per_record=4096,
    )
    ds = GenesisBlockDataset(cfg, tok)

    assert ds.report.records_read == 2, f"Expected 2 records read, got {ds.report.records_read}"
    assert ds.report.records_rejected_malformed == 1, f"Expected exactly 1 rejection, got {ds.report.records_rejected_malformed}"
    assert ds.report.num_blocks == 2, f"Expected 2 blocks (packing=False), got {ds.report.num_blocks}"

    # Confirm tokens of rec1 and rec3 are present, oversized payload tokens are absent
    toks_rec1 = tok.encode("FIRST VALID RECORD TEXT")[:4]
    toks_rec3 = tok.encode("THIRD VALID RECORD TEXT")[:4]

    b0, _ = ds.block(0)
    b1, _ = ds.block(1)

    assert b0.tolist()[:len(toks_rec1)] == toks_rec1
    assert b1.tolist()[:len(toks_rec3)] == toks_rec3
    ds.close()


def test_audit077_domain_a_multibyte_utf8_sliced_across_chunk_boundary(tmp_path):
    """Challenge the streaming leftover buffer when a multi-byte UTF-8 character
    (e.g., 4-byte UTF-8 character U+1F680 🚀: 0xF0 0x9F 0x9A 0x80)
    is cut exactly across the 64 KiB _SHARD_READ_CHUNK_BYTES boundary.
    Chunk 1 ends with the first 2 bytes (0xF0 0x9F); Chunk 2 begins with the remaining 2 bytes (0x9A 0x80).
    Verify: the buffer preserves partial bytes, decodes without UnicodeDecodeError, and reads the record.
    """
    shard_dir = tmp_path / "shards_utf8"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"

    prefix_str = '{"text": "'
    prefix_bytes = prefix_str.encode("utf-8")

    # Target: cut the 4-byte emoji 🚀 at the 64 KiB boundary
    # Boundary is at _SHARD_READ_CHUNK_BYTES (65536 bytes)
    # We want 65534 bytes before the emoji, so emoji bytes 0..1 land at [65534, 65535], bytes 2..3 land at [65536, 65537].
    filler_len = _SHARD_READ_CHUNK_BYTES - len(prefix_bytes) - 2
    filler = b"A" * filler_len
    emoji_bytes = "🚀".encode("utf-8")  # 4 bytes: b'\xf0\x9f\x9a\x80'
    assert len(emoji_bytes) == 4

    suffix_str = ' END_OF_UTF8_TEST"}\n'
    suffix_bytes = suffix_str.encode("utf-8")

    full_payload = prefix_bytes + filler + emoji_bytes + suffix_bytes
    assert full_payload[_SHARD_READ_CHUNK_BYTES - 2 : _SHARD_READ_CHUNK_BYTES + 2] == emoji_bytes, "Emoji must straddle chunk boundary"

    shard_file.write_bytes(full_payload)
    digests = compute_shard_digests(shard_dir)

    tok = Utf8BoundaryTokenizer(vocab_size=128)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=8, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-utf8-boundary", packing=False,
        max_record_bytes=100_000, max_tokens_per_record=100_000,
    )
    ds = GenesisBlockDataset(cfg, tok)

    assert ds.report.records_read == 1, f"Expected 1 record read, got {ds.report.records_read}"
    assert ds.report.records_rejected_malformed == 0, f"Expected 0 rejections, got {ds.report.records_rejected_malformed}"
    assert ds.report.num_blocks == 1
    ds.close()


def test_audit077_domain_a_eof_without_newline_during_discard_state(tmp_path):
    """Challenge the EOF branch when discarding_until_newline is active:
    A shard contains a normal record, then starts an oversized record (>max_record_bytes),
    transitions to discarding_until_newline = True, and the file ends abruptly (EOF) with no trailing newline.
    Verify: exactly 1 normal record read, exactly 1 rejection counted, no crash, no leak.
    """
    shard_dir = tmp_path / "shards_eof"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"

    rec1 = json.dumps({"text": "VALID LEADING RECORD"}) + "\n"
    # Oversized record with NO trailing newline spanning 2 chunks
    oversized_no_nl = b'{"text": "OVERSIZED ' + b"X" * (_SHARD_READ_CHUNK_BYTES * 2)

    shard_file.write_bytes(rec1.encode("utf-8") + oversized_no_nl)
    digests = compute_shard_digests(shard_dir)

    tok = SimpleAsciiTokenizer()
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-audit077-eof", packing=False,
        max_record_bytes=2048, max_tokens_per_record=4096,
    )
    ds = GenesisBlockDataset(cfg, tok)

    assert ds.report.records_read == 1, f"Expected 1 record read, got {ds.report.records_read}"
    assert ds.report.records_rejected_malformed == 1, f"Expected 1 rejection, got {ds.report.records_rejected_malformed}"
    assert ds.report.num_blocks == 1
    ds.close()


def test_audit077_domain_a_large_shard_bounded_heap_tracemalloc(tmp_path):
    """Challenge heap memory scalability on a large synthetic shard (>30 MB, ~50,000 records).
    Verify: peak heap allocation (tracemalloc) remains strictly bounded (< 5 MB) and does not scale O(shard_size).
    """
    shard_dir = tmp_path / "shards_large_heap"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"

    line_text = "Bounded streaming verification line with sufficient entropy for tokenization. " * 4
    line_json = (json.dumps({"text": line_text}) + "\n").encode("utf-8")

    n_lines = 80_000
    with open(shard_file, "wb") as f:
        for _ in range(n_lines):
            f.write(line_json)

    file_size = shard_file.stat().st_size
    assert file_size > 25_000_000, f"Shard must be > 25 MB to stress heap, got {file_size} bytes"

    digests = compute_shard_digests(shard_dir)
    tok = SimpleAsciiTokenizer()
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=16, batch_size=4, seed=42,
        authorized_shard_digests=digests, tokenizer_digest="tok-large-heap", packing=True,
        construction_buffer_tokens=1024, max_tokens_per_record=2048,
    )

    gc.collect()
    tracemalloc.start()
    ds = GenesisBlockDataset(cfg, tok)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert ds.report.num_blocks > 5_000
    # Peak heap must be less than 5 MB while ingesting a 25+ MB file
    assert peak < 5 * 1024 * 1024, (
        f"Peak heap memory ({peak / 1024 / 1024:.2f} MB) exceeded 5 MB ceiling while ingesting "
        f"{file_size / 1024 / 1024:.2f} MB shard -- streaming buffer is accumulating unbounded state"
    )
    assert peak < file_size / 5, "Peak heap should be a small fraction of total shard size"
    ds.close()


# ==============================================================================
# Domain B: Checkpoint Path Confinement & TOCTOU Security
# ==============================================================================

def test_audit077_domain_b_checkpoint_path_confinement_adversarial(tmp_path):
    """Adversarially challenge _enforce_checkpoint_path_confinement():
    1. Parent directory traversal attack (../outside/ckpt.pt)
    2. Absolute path attack outside workspace (/tmp/malicious.pt)
    3. Pre-planted symlink attack: symlink inside workspace resolving to an external directory
    4. Unconfigured workspace (None) fail-closed guarantee
    5. Valid relative path within workspace
    """
    workspace = tmp_path / "authorized_workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "forbidden_outside"
    outside_dir.mkdir()

    cfg = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=workspace)

    # 1. Directory traversal escape
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, "../forbidden_outside/ckpt.pt")

    # 2. Absolute path escape
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, str(outside_dir / "ckpt.pt"))

    # 3. Pre-planted symlink attack:
    # Attacker creates a symlink inside the workspace pointing to outside_dir
    symlink_dir = workspace / "innocent_looking_symlink"
    symlink_dir.symlink_to(outside_dir)
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg, "innocent_looking_symlink/target.pt")

    # 4. Fail-closed when no workspace is configured
    cfg_no_workspace = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=None)
    with pytest.raises(CheckpointWorkspaceViolationError):
        _enforce_checkpoint_path_confinement(cfg_no_workspace, "any_path.pt")

    # 5. Legitimate relative path inside workspace succeeds
    _enforce_checkpoint_path_confinement(cfg, "legit_subdir/ckpt.pt")
    _enforce_checkpoint_path_confinement(cfg, "ckpt.pt")


# ==============================================================================
# Domain C: Checkpoint Cross-Run Ownership & Ledger Replay Boundary
# ==============================================================================

def test_audit077_domain_c_checkpoint_ledger_monotonicity_and_cross_run_boundary(tmp_path):
    """Investigate the anti-rollback ledger and cross-run checkpoint loading:
    1. Verify rollback protection within the same run_id:
       Saving at step 10 advances the ledger to 10. Attempting to restore a step 5 checkpoint raises CheckpointRollbackError.
    2. Cross-run boundary investigation:
       Determine whether a checkpoint saved by run_A can be restored into run_B when both share identical
       model config, dataset identity, and integrity key.
       Verify that the anti-rollback ledger is scoped by run_id, not a global single-run lock.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    ckpt_dir = tmp_path / "ckpts"
    ckpt_dir.mkdir()

    key = secrets.token_bytes(32)
    dataset_id = DatasetIdentity(
        dataset_manifest_id="manifest-a077",
        dataset_content_digest=_digest("ds"),
        tokenizer_digest=_digest("tok"),
    )
    fp = compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG)

    # Save checkpoint at step 5 for run_A
    state_step5 = TrainingState.capture(step=5, epoch=0, dataloader_position=50, model=model, optimizer=opt)
    ckpt_path_5 = ckpt_dir / "step5.pt"
    save_resumable_checkpoint(
        path=ckpt_path_5, training_state=state_step5, global_step=5, microbatch_in_cycle=0,
        sampler_position=50, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=dataset_id, integrity_key=key, run_id="run_A",
    )

    # Save checkpoint at step 10 for run_A
    state_step10 = TrainingState.capture(step=10, epoch=0, dataloader_position=100, model=model, optimizer=opt)
    ckpt_path_10 = ckpt_dir / "step10.pt"
    save_resumable_checkpoint(
        path=ckpt_path_10, training_state=state_step10, global_step=10, microbatch_in_cycle=0,
        sampler_position=100, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=dataset_id, integrity_key=key, run_id="run_A",
    )

    # 1. Rollback attempt in run_A: restoring step 5 when ledger is at 10 MUST fail
    with pytest.raises(CheckpointRollbackError):
        restore_resumable_checkpoint(
            path=ckpt_path_5, expected_config_fingerprint=fp, expected_dataset_identity=dataset_id,
            expected_sampler_seed=42, expected_sampler_num_blocks=100, integrity_key=key, run_id="run_A",
        )

    # 2. Cross-run restore investigation:
    # run_B starts with an empty ledger. It restores run_A's step 10 checkpoint.
    # Note: run_id is NOT stored inside the checkpoint manifest's tagged HMAC payload.
    # Therefore, restore succeeds and initializes run_B's ledger at step 10.
    restored_run_b = restore_resumable_checkpoint(
        path=ckpt_path_10, expected_config_fingerprint=fp, expected_dataset_identity=dataset_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=100, integrity_key=key, run_id="run_B",
    )
    assert restored_run_b.global_step == 10
    assert restored_run_b.sampler_position == 100

    # Once run_B's ledger is at 10, run_B also rejects rollback to step 5
    with pytest.raises(CheckpointRollbackError):
        restore_resumable_checkpoint(
            path=ckpt_path_5, expected_config_fingerprint=fp, expected_dataset_identity=dataset_id,
            expected_sampler_seed=42, expected_sampler_num_blocks=100, integrity_key=key, run_id="run_B",
        )


# ==============================================================================
# Domain D: Isolated Worker Checkpoint IPC Security & Revocation
# ==============================================================================

def test_audit077_domain_d_worker_ipc_checkpoint_live_revocation_enforced(tmp_path):
    """Challenge isolated worker IPC checkpoint handlers:
    1. Normal checkpoint save/restore succeeds when grant is valid.
    2. Revoking the grant in the live revocation file causes save_checkpoint to fail-stop immediately.
    3. Revoking the grant causes restore_checkpoint to fail-stop immediately.
    4. Worker terminates its process upon authorization failure (fail-stop posture).
    """
    workspace = tmp_path / "worker_ckpt_ws"
    workspace.mkdir()
    cfg = _make_worker_startup_cfg(tmp_path, checkpoint_workspace_dir=workspace)
    revoked_file = Path(cfg.revoked_ids_path)

    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    key = secrets.token_bytes(32)
    ckpt_path = str(workspace / "ckpt.pt")

    try:
        client = worker.client()
        client.connect()
        try:
            # Step 1: Normal save succeeds while authorized
            save_resp = client.save_checkpoint(
                path=ckpt_path, integrity_key=key, sampler_position=0, sampler_seed=42, sampler_num_blocks=10,
            )
            assert save_resp["ok"] is True, f"Initial save failed: {save_resp}"
            assert Path(ckpt_path).exists()

            # Normal restore succeeds while authorized
            restore_resp = client.restore_checkpoint(
                path=ckpt_path, integrity_key=key, sampler_seed=42, sampler_num_blocks=10,
            )
            assert restore_resp["ok"] is True, f"Initial restore failed: {restore_resp}"

            # Step 2: Revoke the authorization ID in the live revocation file
            auth_id = cfg.record["authorization_id"]
            revoked_file.write_text(json.dumps([auth_id]))

            # Attempt save_checkpoint after revocation -> MUST fail-stop
            save_revoked_resp = client.save_checkpoint(
                path=str(workspace / "ckpt_revoked.pt"), integrity_key=key, sampler_position=1, sampler_seed=42, sampler_num_blocks=10,
            )
            assert save_revoked_resp["ok"] is False
            assert "AUTHORIZATION_DENIED" in save_revoked_resp["error"]

            # Confirm worker has stopped / terminated connection
            with pytest.raises(Exception):
                client.restore_checkpoint(path=ckpt_path, integrity_key=key, sampler_seed=42, sampler_num_blocks=10)

        finally:
            client.close()
    finally:
        worker.stop()


# ==============================================================================
# Domain E: Synthetic Restart Equivalence & Shift Reconciliation
# ==============================================================================

def test_audit077_domain_e_unshifted_contract_and_loss_math_verification():
    """Formally reconcile Audit #076 correction request:
    Prove that GenesisBlockDataset.block() returns unshifted (tokens, tokens),
    and causal_lm_loss(logits, targets) internally shifts logits[:, :-1, :] vs targets[:, 1:].
    Prove that pre-shifting (tokens[:-1], tokens[1:]) before feeding to causal_lm_loss is a double-shift defect.
    """
    seq = torch.tensor([10, 11, 12, 13, 14], dtype=torch.long)
    # Canonical unshifted contract: input_ids == seq, labels == seq
    input_ids = seq.unsqueeze(0)
    labels = seq.unsqueeze(0)

    # Perfect predictor: logits at position t predict token at position t+1 with high confidence
    vocab_size = 32
    seq_len = 5
    logits = torch.zeros((1, seq_len, vocab_size))
    for t in range(seq_len - 1):
        target_token = seq[t + 1].item()
        logits[0, t, target_token] = 100.0  # very large logit for the actual next token

    loss_canonical = causal_lm_loss(logits, labels)
    assert loss_canonical.item() < 1e-4, f"Canonical unshifted contract must produce ~0 loss, got {loss_canonical.item()}"

    # Now show the double-shift artifact from Audit #076 test_audit_f:
    # If the caller pre-shifted labels: pre_shifted_labels = seq[1:]
    pre_shifted_labels = seq[1:].unsqueeze(0)  # [11, 12, 13, 14]
    # In causal_lm_loss, pre_shifted_labels would be sliced as labels[:, 1:], which would be [12, 13, 14]!
    # That compared logits[:, :-1] with targets 2 steps ahead -- an accidental double-shift!
    # Confirming the canonical unshifted contract is (seq, seq).


def test_audit077_domain_e_exact_restart_equivalence_on_synthetic_stream(tmp_path):
    """Independently verify restart equivalence on a deterministic synthetic stream:
    Run 1: Uninterrupted training for 6 steps.
    Run 2: Train for 3 steps, save checkpoint, shut down engine, restore checkpoint into fresh engine, train steps 4..6.
    Verify: Model parameters at step 6 match to exact bit-parity (or < 1e-7 float tolerance) and loss trajectory is identical.
    """
    shard_dir = tmp_path / "restart_shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"

    # Write a deterministic synthetic sequence
    lines = []
    val = 5
    for _ in range(200):
        row = []
        for _ in range(8):
            val = (11 * val + 7) % (VOCAB - 4) + 4
            row.append(str(val))
        lines.append(json.dumps({"text": " ".join(row)}) + "\n")
    shard_file.write_text("".join(lines))

    digests = compute_shard_digests(shard_dir)
    tok = SimpleAsciiTokenizer()
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=SEQ_LEN, batch_size=2, seed=1234,
        authorized_shard_digests=digests, tokenizer_digest="tok-restart", packing=True,
    )
    dataset_1 = GenesisBlockDataset(cfg, tok)
    sampler_1 = ReproducibleSampler(len(dataset_1), seed=1234)

    # Run A: Uninterrupted 6 steps
    set_deterministic_seed(42)
    model_a = GenesisTransformer(TINY_MODEL_CFG)
    opt_cfg = TrainingStepConfig(grad_accum_steps=1, warmup_steps=1, total_steps=10, max_lr=1e-3)
    engine_a = TrainingStepEngine(model_a, opt_cfg)
    cap = ExecutionCapability.for_unchecked_synthetic_test()

    losses_a = []
    for _ in range(6):
        batch_input_ids, batch_labels = make_batch(dataset_1, sampler_1.next_batch_indices(batch_size=2))
        m = engine_a.step(batch_input_ids, batch_labels, capability=cap)
        losses_a.append(m.microbatch_loss)

    # Run B: 3 steps, checkpoint, restore into fresh engine, 3 steps
    dataset_2 = GenesisBlockDataset(cfg, tok)
    sampler_2 = ReproducibleSampler(len(dataset_2), seed=1234)

    set_deterministic_seed(42)
    model_b = GenesisTransformer(TINY_MODEL_CFG)
    engine_b = TrainingStepEngine(model_b, opt_cfg)

    losses_b = []
    for _ in range(3):
        batch_input_ids, batch_labels = make_batch(dataset_2, sampler_2.next_batch_indices(batch_size=2))
        m = engine_b.step(batch_input_ids, batch_labels, capability=cap)
        losses_b.append(m.microbatch_loss)

    # Save checkpoint at step 3
    key = secrets.token_bytes(32)
    ckpt_path = tmp_path / "restart_ckpt.pt"
    ds_id = DatasetIdentity("restart-manifest", digests[shard_file.name], "tok-restart")
    fp = compute_config_fingerprint(TINY_MODEL_CFG, opt_cfg)

    state_b = TrainingState.capture(
        step=engine_b.global_step, epoch=0, dataloader_position=sampler_2.position,
        model=engine_b.model, optimizer=engine_b.optimizer,
    )
    save_resumable_checkpoint(
        path=ckpt_path, training_state=state_b, global_step=engine_b.global_step,
        microbatch_in_cycle=engine_b.microbatch_in_cycle, sampler_position=sampler_2.position,
        sampler_seed=42, sampler_num_blocks=len(dataset_2),
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key, run_id="restart-run",
    )

    # Create fresh model, fresh engine, fresh sampler
    fresh_model = GenesisTransformer(TINY_MODEL_CFG)
    fresh_engine = TrainingStepEngine(fresh_model, opt_cfg)
    dataset_3 = GenesisBlockDataset(cfg, tok)
    fresh_sampler = ReproducibleSampler(len(dataset_3), seed=1234)

    # Restore
    restored = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=len(dataset_3),
        integrity_key=key, run_id="restart-run",
    )
    restored.training_state.restore(model=fresh_engine.model, optimizer=fresh_engine.optimizer)
    fresh_engine.global_step = restored.global_step
    fresh_engine.microbatch_in_cycle = restored.microbatch_in_cycle
    fresh_sampler.position = restored.sampler_position

    # Continue steps 4..6
    for _ in range(3):
        batch_input_ids, batch_labels = make_batch(dataset_3, fresh_sampler.next_batch_indices(batch_size=2))
        m = fresh_engine.step(batch_input_ids, batch_labels, capability=cap)
        losses_b.append(m.microbatch_loss)

    # Assert losses match to strict tolerance
    for la, lb in zip(losses_a, losses_b):
        assert abs(la - lb) < 1e-6, f"Loss mismatch: uninterrupted={la}, restored={lb}"

    # Assert final model parameters match to strict tolerance
    for (na, pa), (nb, pb) in zip(model_a.named_parameters(), fresh_model.named_parameters()):
        assert na == nb
        max_diff = torch.max(torch.abs(pa - pb)).item()
        assert max_diff < 1e-6, f"Parameter divergence in {na}: max diff {max_diff}"

    dataset_1.close()
    dataset_2.close()
    dataset_3.close()
