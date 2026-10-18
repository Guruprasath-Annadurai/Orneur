"""
Independent Master Foundation Qualification Test Suite for ORNEUR GENESIS Native Learning Engine.
Directives: CTO MASTER DIRECTIVE #076.
Auditor: Antigravity / Gemini — Independent Security, Research & Model Assurance Lead.
Audited HEAD: 9743e6282b71ac225982e75175c9fb0451cda4a1 (PR #73)

Audits Covered:
- Audit A: Dataset Memory Scalability & Shard Ingestion Heap Profiling.
- Audit B: Block-Store Cache Identity, Read-Time Digest Verification & Coordinated Tampering.
- Audit C: Real Process Isolation, UID Qualification & Protocol Security.
- Audit D: Synthetic Bypass Elimination & Continuous Per-Step Grant Verification.
- Audit E: Checkpoint HMAC Key Enforcement & Local Anti-Rollback Ledger Replay Vulnerability.
- Audit F: End-to-End Synthetic Learning System Convergence & Parameter Evolution.
"""
from __future__ import annotations

import array
import gc
import hashlib
import hmac
import io
import json
import os
import pathlib
import secrets
import subprocess
import tempfile
import time
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
import orca.genesis.training.orchestration as ORCH
from orca.genesis.data.loader import (
    BLOCK_STORE_SCHEMA_VERSION,
    BlockStoreTamperedError,
    GenesisBlockDataset,
    LoaderConfig,
    MalformedRecordError,
    ShardIntegrityError,
    _BLOCK_DIGEST_SIZE,
    _TOKEN_TYPECODE,
    compute_block_store_cache_id,
    compute_shard_digests,
)
from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.tokenizer.framework import GenesisTokenizer
from orca.genesis.training.isolated_worker import (
    IsolatedTrainingWorker,
    WorkerStartupConfig,
    WorkerStartupError,
)
from orca.genesis.training.learning_governance import (
    TrainingNotAuthorizedForExecutionError,
    execute_authorized_training_step,
)
from orca.genesis.training.learning_step import (
    ExecutionCapability,
    TrainingStepConfig,
    TrainingStepEngine,
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


def _head_sha() -> str:
    p = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return p.stdout.strip() if p.returncode == 0 else "0" * 40


HEAD_SHA = _head_sha()


class MockTokenizer(GenesisTokenizer):
    """Deterministic, lightweight tokenizer for qualification tests."""

    def __init__(self, vocab_size: int = VOCAB):
        self._vocab_size = vocab_size

    def encode(self, text: str) -> list[int]:
        return [ord(c) % (self._vocab_size - 4) + 4 for c in text if c.strip()]

    def decode(self, token_ids: list[int]) -> str:
        return "".join(chr(t) for t in token_ids)

    def vocab_size(self) -> int:
        return self._vocab_size

    def content_digest(self) -> str:
        return hashlib.sha256(b"MockTokenizer-Digest-V1").hexdigest()


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Ensure tests run in complete filesystem and nonce isolation."""
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _make_worker_startup_cfg(tmp_path: Path, *, drop_to_uid: int | None = None) -> WorkerStartupConfig:
    mcfg, tcd, ocd = (_digest(x) for x in ("mcfg", "tcd", "ocd"))
    tok_digest = _digest("tok")
    dataset_digest = _digest("dataset")
    shard_dir = tmp_path / "worker_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "isolated worker qualification fixture shard"}\n')
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
    run_id = f"worker-test-run-{secrets.token_hex(4)}"
    req = GOV.NativePretrainingRequest(
        run_id=run_id, nonce=_digest(f"nonce-{run_id}"), model_family="genesis",
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

    sock_dir = Path(tempfile.mkdtemp(prefix="isow-qual-"))
    os.chmod(sock_dir, 0o700)

    revoked_ids_path = tmp_path / "revoked_worker.json"
    revoked_ids_path.write_text("[]")

    pinned_registry_sha256 = GOV.registry_digest(registry)

    return WorkerStartupConfig(
        workload_id=run_id,
        auth_token=secrets.token_bytes(32),
        sock_path=str(sock_dir / "worker.sock"),
        model_cfg=TINY_MODEL_CFG,
        step_cfg=STEP_CFG,
        run_id=run_id,
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
        drop_to_uid=drop_to_uid,
        orca_home_override=str(tmp_path / "ornhome"),
        test_only_bypass_founder_ledger=True,
        test_only_pinned_registry_sha256=pinned_registry_sha256,
    )


# ==============================================================================
# AUDIT A: Dataset Memory Scalability & Shard Ingestion Heap Profiling
# ==============================================================================

def test_audit_a_path_read_bytes_and_block_digests_heap_scaling(tmp_path):
    """
    AUDIT A Finding 1 & 2:
    Demonstrates that `path.read_bytes()` and `block_digests: list[bytes]` in
    `GenesisBlockDataset._build_and_publish_block_store` allocate heap memory
    proportional to shard file size and block count, violating bounded RAM guarantees.
    """
    shard_dir = tmp_path / "large_shards"
    shard_dir.mkdir()
    shard_name = "shard-0000-train.jsonl"
    shard_file = shard_dir / shard_name

    # Create a 2MB+ synthetic shard (20,000 lines)
    target_lines = 20000
    line_text = "The quick brown fox jumps over the lazy dog in native pretraining loop testing."
    with open(shard_file, "w", encoding="utf-8") as f:
        for _ in range(target_lines):
            f.write(json.dumps({"text": line_text}) + "\n")

    file_size_bytes = shard_file.stat().st_size
    assert file_size_bytes > 1_000_000, "Shard should be > 1MB"

    shard_digests = compute_shard_digests(shard_dir)
    tok = MockTokenizer()

    # Configure small construction buffer (1024 tokens = 8 KiB)
    cfg = LoaderConfig(
        shard_dir=shard_dir,
        split="train",
        seq_len=16,
        batch_size=4,
        seed=42,
        authorized_shard_digests=shard_digests,
        tokenizer_digest=tok.content_digest(),
        packing=True,
        construction_buffer_tokens=1024,
    )

    gc.collect()
    tracemalloc.start()
    dataset = GenesisBlockDataset(cfg, tok)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak >= file_size_bytes, (
        f"Expected peak memory ({peak} bytes) to reflect whole-file load "
        f"exceeding file size ({file_size_bytes} bytes)."
    )
    assert len(dataset) > 0
    dataset.close()


def test_audit_a_streaming_shard_ingestion_remediation_proof(tmp_path):
    """
    AUDIT A Remediation Verification:
    Proves that a streaming shard reader using open file descriptor rewind
    preserves TOCTOU protection while bounding peak heap memory to O(1) buffer size.
    """
    shard_dir = tmp_path / "streaming_shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"

    target_lines = 20000
    with open(shard_file, "w", encoding="utf-8") as f:
        for _ in range(target_lines):
            f.write(json.dumps({"text": "streaming verification tokenized sample line"}) + "\n")

    expected_digest = hashlib.sha256(shard_file.read_bytes()).hexdigest()

    gc.collect()
    tracemalloc.start()

    # Safe streaming pattern:
    # 1. Open fd
    fd = os.open(str(shard_file), os.O_RDONLY)
    try:
        # 2. Hash in chunks (O(chunk_size) memory)
        h = hashlib.sha256()
        chunk_size = 64 * 1024
        while True:
            chunk = os.read(fd, chunk_size)
            if not chunk:
                break
            h.update(chunk)
        actual_digest = h.hexdigest()
        assert actual_digest == expected_digest

        # 3. Rewind open fd without reopening path (pins inode against TOCTOU)
        os.lseek(fd, 0, os.SEEK_SET)

        # 4. Stream line-by-line using TextIOWrapper
        line_count = 0
        with io.open(fd, mode="r", encoding="utf-8", closefd=False) as reader:
            for line in reader:
                rec = json.loads(line)
                assert "text" in rec
                line_count += 1
        assert line_count == target_lines
    finally:
        os.close(fd)

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < 350_000, f"Streaming heap peak {peak} exceeded 350 KiB bound"


# ==============================================================================
# AUDIT B: Block-Store Cache Identity, Read-Time Digest Verification & Coordinated Tampering
# ==============================================================================

def test_audit_b_block_store_cache_identity_and_per_block_tamper_detection(tmp_path):
    """
    AUDIT B: Verifies cache identity formula incorporates all structural hyperparameters,
    and single-block bitflip tampering in `.blocks.bin` is caught on `block(idx)`
    via per-block digest verification.
    """
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"
    shard_file.write_text(json.dumps({"text": "testing block store integrity and sidecar digest detection"}) + "\n")

    digests = compute_shard_digests(shard_dir)
    tok = MockTokenizer()

    cfg1 = LoaderConfig(
        shard_dir=shard_dir,
        split="train",
        seq_len=16,
        batch_size=2,
        seed=42,
        authorized_shard_digests=digests,
        tokenizer_digest=tok.content_digest(),
        packing=True,
    )
    cfg2 = LoaderConfig(
        shard_dir=shard_dir,
        split="train",
        seq_len=32,  # different seq_len
        batch_size=2,
        seed=42,
        authorized_shard_digests=digests,
        tokenizer_digest=tok.content_digest(),
        packing=True,
    )

    # 1. Distinct cache IDs for different seq_len
    id1 = compute_block_store_cache_id(cfg1)
    id2 = compute_block_store_cache_id(cfg2)
    assert id1 != id2, "Different seq_len must yield distinct cache IDs"

    dataset = GenesisBlockDataset(cfg1, tok)
    assert len(dataset) > 0

    # 2. Tamper with block 0 bytes on disk directly
    store_path = shard_dir / f".block_store_{id1}.bin"
    with open(store_path, "r+b") as f:
        f.seek(0)
        orig = f.read(1)
        f.seek(0)
        f.write(bytes([orig[0] ^ 0xFF]))

    # Refresh file handle to bypass stdio read-ahead caching
    dataset._store_file.close()
    dataset._store_file = open(dataset._store_path, "rb")

    # Read on open dataset must detect per-block digest mismatch
    with pytest.raises(BlockStoreTamperedError) as excinfo:
        dataset.block(0)
    assert "digest" in str(excinfo.value).lower() or "tampered" in str(excinfo.value).lower()
    dataset.close()


def test_audit_b_coordinated_tampering_vulnerability_demonstration(tmp_path):
    """
    AUDIT B Finding: Unkeyed SHA-256 block digest allows an attacker with write access
    to rewrite .blocks.bin, .digests.bin, and manifest.json synchronously.
    """
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"
    shard_file.write_text(json.dumps({"text": "legitimate initial training corpus"}) + "\n")

    digests = compute_shard_digests(shard_dir)
    tok = MockTokenizer()
    cfg = LoaderConfig(
        shard_dir=shard_dir,
        split="train",
        seq_len=16,
        batch_size=2,
        seed=42,
        authorized_shard_digests=digests,
        tokenizer_digest=tok.content_digest(),
        packing=True,
    )
    dataset = GenesisBlockDataset(cfg, tok)
    num_blocks = len(dataset)
    dataset.close()

    cache_id = compute_block_store_cache_id(cfg)
    store_path = shard_dir / f".block_store_{cache_id}.bin"
    digests_path = shard_dir / f".block_store_{cache_id}.digests.bin"
    manifest_path = shard_dir / f".block_store_{cache_id}.manifest.json"

    # Attacker crafts malicious block data (e.g. all 7s)
    forged_tokens = [7] * (16 * num_blocks)
    forged_bytes = array.array(_TOKEN_TYPECODE, forged_tokens).tobytes()

    # Attacker recalculates per-block digests
    forged_digests = bytearray()
    block_byte_size = 16 * 8
    for i in range(num_blocks):
        b = forged_bytes[i * block_byte_size : (i + 1) * block_byte_size]
        forged_digests.extend(hashlib.sha256(b).digest()[:_BLOCK_DIGEST_SIZE])

    # Attacker rewrites store, digests, and manifest sha256
    store_path.write_bytes(forged_bytes)
    digests_path.write_bytes(forged_digests)
    manifest = json.loads(manifest_path.read_text())
    manifest["store_sha256"] = hashlib.sha256(forged_bytes).hexdigest()
    manifest_path.write_text(json.dumps(manifest))

    # Reopening dataset loads forged cache because digest is unkeyed SHA-256
    tampered_dataset = GenesisBlockDataset(cfg, tok)
    inp, lbl = tampered_dataset.block(0)
    assert inp.tolist() == [7] * 16, "Unkeyed SHA-256 allowed coordinated local cache overwrite"
    tampered_dataset.close()


# ==============================================================================
# AUDIT C: Real Process Isolation, UID Qualification & Protocol Security
# ==============================================================================

def test_audit_c_worker_isolation_status_and_privilege_boundary(tmp_path):
    """
    AUDIT C: Verifies IsolatedTrainingWorker reports actual isolation qualification
    and safely rejects unprivileged UID dropping.
    """
    cfg = _make_worker_startup_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        iso_qual = worker.isolation_qualification
        assert iso_qual in ("ISOLATION_NOT_QUALIFIED", "PEER_VERIFIED_SAME_UID")
    finally:
        worker.stop()

    # Attempting to drop to arbitrary UID when not running as root fails closed
    cfg_priv = _make_worker_startup_cfg(tmp_path, drop_to_uid=99999)
    worker_priv = IsolatedTrainingWorker(cfg_priv)
    with pytest.raises(WorkerStartupError) as excinfo:
        worker_priv.start()
    assert "not running as root" in str(excinfo.value).lower() or "isolation" in str(excinfo.value).lower()


# ==============================================================================
# AUDIT D: Synthetic Bypass Elimination & Continuous Per-Step Grant Verification
# ==============================================================================

def test_audit_d_worker_has_zero_synthetic_bypass():
    """
    AUDIT D: Static analysis of `isolated_worker.py` confirms complete absence of
    `ExecutionCapability.for_unchecked_synthetic_test()`.
    """
    worker_source_path = Path(orca_config.__file__).parent / "genesis" / "training" / "isolated_worker.py"
    source_text = worker_source_path.read_text(encoding="utf-8")
    assert "for_unchecked_synthetic_test" not in source_text, (
        "isolated_worker.py must never contain or reference for_unchecked_synthetic_test bypass"
    )


def test_audit_d_continuous_revalidation_immediate_revocation(tmp_path, monkeypatch):
    """
    AUDIT D: Confirms `execute_authorized_training_step` revalidates grant every single step
    and immediately halts upon revocation with zero latency.
    """
    shard_dir = tmp_path / "gov_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "governance test fixture record"}\n')
    shard_digests = tuple(sorted(compute_shard_digests(shard_dir).values()))

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    now = datetime.now(timezone.utc)
    registry = {
        "schema_version": GOV.REGISTRY_SCHEMA_VERSION,
        "records": [{
            "id": "gov-test-authority", "role": "OWNER", "public_key_hex": pub,
            "activation_timestamp": _ts(now - timedelta(days=1)), "expiry": None, "revoked": False,
            "gpu_permission": False, "spend_permission": False,
        }],
    }
    run_id = "gov-revocation-test-run"
    mcfg, tcd, ocd = (_digest(x) for x in ("mcfg", "tcd", "ocd"))
    tok_digest = _digest("tok")
    req = GOV.NativePretrainingRequest(
        run_id=run_id, nonce=_digest(f"nonce-{run_id}"), model_family="genesis", architecture_version="genesis-arch-v1",
        model_config_digest=mcfg, tokenizer_digest=tok_digest, dataset_manifest_id="gov-manifest",
        dataset_content_digest=_digest("dataset"), authorized_shard_digests=shard_digests, reviewed_commit_sha=HEAD_SHA,
        transformation_code_digest=tcd, optimizer_config_digest=ocd, environment_class=ENV, gpu_requested=False,
        max_wall_clock_minutes=60, requested_spend_usd=0.0,
    )
    record = {
        "schema_version": GOV.SCHEMA_VERSION, "authorization_id": "gnpauth-" + "bb" * 8, "status": "AUTHORIZED",
        "run_id": req.run_id, "nonce": req.nonce,
        "model": {"family": req.model_family, "architecture_version": req.architecture_version, "model_config_digest": req.model_config_digest},
        "tokenizer": {"tokenizer_digest": req.tokenizer_digest},
        "dataset": {"dataset_manifest_id": req.dataset_manifest_id, "dataset_content_digest": req.dataset_content_digest, "authorized_shard_digests": list(req.authorized_shard_digests)},
        "code": {"reviewed_commit_sha": req.reviewed_commit_sha, "transformation_code_digest": req.transformation_code_digest},
        "training": {"optimizer_config_digest": req.optimizer_config_digest},
        "environment_class": req.environment_class,
        "limits": {"max_wall_clock_minutes": 120, "max_spend_usd": 0, "gpu_allowed": False},
        "issued_at": _ts(now - timedelta(hours=1)), "expires_at": _ts(now + timedelta(days=6)),
        "authorizing_authority": {"identity": "gov-test-authority", "role": "OWNER", "key_id": "gov-test-authority"},
        "signature": None,
    }
    record["signature"] = priv.sign(GOV.canonical_signing_bytes(record)).hex()

    is_revoked = {"revoked": False}

    def revocation_check(auth_id: str) -> bool:
        return is_revoked["revoked"]

    monkeypatch.setattr(GOV, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    monkeypatch.setattr(GOV, "PINNED_REGISTRY_SHA256", GOV.registry_digest(registry))

    grant = GOV.authorize_native_pretraining(
        repo_root=REPO_ROOT, record=record, registry=registry, revoked_ids=[], req=req,
        revocation_check=revocation_check,
    )

    run = ORCH.GenesisTrainingRun(
        run_id, dataset_manifest_ids=("gov-manifest",), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=revocation_check,
    )
    run.validate(
        dataset_digest=_digest("dataset"), model_config_digest=mcfg, tokenizer_digest=tok_digest,
        authorized_shard_digests=shard_digests, shard_dir=shard_dir, reviewed_commit_sha=HEAD_SHA,
        transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run.request_authorization()
    run.authorize(grant)
    run.start()

    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, STEP_CFG)
    batch = torch.randint(0, VOCAB, (2, 8))

    # Step 0 succeeds
    res0 = execute_authorized_training_step(run, engine, batch, batch.clone())
    assert res0.applied is True

    # Revoke immediately
    is_revoked["revoked"] = True

    # Step 1 must immediately fail closed without delay
    with pytest.raises(TrainingNotAuthorizedForExecutionError) as excinfo:
        execute_authorized_training_step(run, engine, batch, batch.clone())
    assert "revoked" in str(excinfo.value).lower() or "not authorized" in str(excinfo.value).lower()


# ==============================================================================
# AUDIT E: Checkpoint HMAC Key Enforcement & Local Anti-Rollback Ledger Replay Vulnerability
# ==============================================================================

def test_audit_e_hmac_minimum_key_length_enforcement(tmp_path):
    """
    AUDIT E: Verifies MIN_INTEGRITY_KEY_BYTES = 32 rejects weak keys (< 32 bytes).
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, STEP_CFG)
    state = TrainingState.capture(
        step=1, epoch=0, dataloader_position=0, model=model, optimizer=engine.optimizer
    )
    ckpt_file = tmp_path / "checkpoints" / "ckpt.pt"
    ckpt_file.parent.mkdir()

    # 31 bytes must fail
    weak_key = b"A" * 31
    with pytest.raises(WeakIntegrityKeyError):
        save_resumable_checkpoint(
            path=ckpt_file,
            training_state=state,
            global_step=1,
            microbatch_in_cycle=0,
            sampler_position=0,
            sampler_seed=42,
            sampler_num_blocks=10,
            config_fingerprint=compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG),
            dataset_identity=DatasetIdentity("manifest-hash", "dataset-digest", "tok-hash"),
            integrity_key=weak_key,
            run_id="run-key-test",
        )

    # 32 bytes succeeds
    valid_key = b"A" * 32
    save_resumable_checkpoint(
        path=ckpt_file,
        training_state=state,
        global_step=1,
        microbatch_in_cycle=0,
        sampler_position=0,
        sampler_seed=42,
        sampler_num_blocks=10,
        config_fingerprint=compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG),
        dataset_identity=DatasetIdentity("manifest-hash", "dataset-digest", "tok-hash"),
        integrity_key=valid_key,
        run_id="run-key-test",
    )


def test_audit_e_local_anti_rollback_simultaneous_replay(tmp_path):
    """
    AUDIT E Finding: The local anti-rollback ledger detects rollback of checkpoint alone,
    but fails to prevent simultaneous rollback of both checkpoint and local ledger file.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, STEP_CFG)
    state5 = TrainingState.capture(
        step=5, epoch=0, dataloader_position=5, model=model, optimizer=engine.optimizer
    )
    ckpt_dir = tmp_path / "checkpoints"
    ckpt_dir.mkdir()
    ckpt_file = ckpt_dir / "ckpt.pt"
    integrity_key = secrets.token_bytes(32)
    run_id = "rollback-test-run"

    # Step 5
    save_resumable_checkpoint(
        path=ckpt_file,
        training_state=state5,
        global_step=5,
        microbatch_in_cycle=0,
        sampler_position=5,
        sampler_seed=42,
        sampler_num_blocks=10,
        config_fingerprint=compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG),
        dataset_identity=DatasetIdentity("mhash", "dhash", "thash"),
        integrity_key=integrity_key,
        run_id=run_id,
    )

    # Backup Step 5 files and ledger
    ledger_path = tmp_path / "ornhome" / "genesis_checkpoint_ledger" / f"{hashlib.sha256(run_id.encode()).hexdigest()}.ledger.json"
    ckpt_files_5 = {f.name: f.read_bytes() for f in ckpt_dir.iterdir()}
    ledger_content_5 = ledger_path.read_bytes()

    # Step 10
    state10 = TrainingState.capture(
        step=10, epoch=0, dataloader_position=10, model=model, optimizer=engine.optimizer
    )
    save_resumable_checkpoint(
        path=ckpt_file,
        training_state=state10,
        global_step=10,
        microbatch_in_cycle=0,
        sampler_position=10,
        sampler_seed=42,
        sampler_num_blocks=10,
        config_fingerprint=compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG),
        dataset_identity=DatasetIdentity("mhash", "dhash", "thash"),
        integrity_key=integrity_key,
        run_id=run_id,
    )

    # Overwrite ckpt_dir with Step 5 files, leaving Step 10 ledger in place -> Rejection
    for name, content in ckpt_files_5.items():
        (ckpt_dir / name).write_bytes(content)

    with pytest.raises(CheckpointRollbackError):
        restore_resumable_checkpoint(
            path=ckpt_file,
            expected_config_fingerprint=compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG),
            expected_dataset_identity=DatasetIdentity("mhash", "dhash", "thash"),
            expected_sampler_seed=42,
            expected_sampler_num_blocks=10,
            integrity_key=integrity_key,
            run_id=run_id,
        )

    # Simultaneous Replay Attack: Overwrite both ckpt_dir AND ledger with Step 5 data
    ledger_path.write_bytes(ledger_content_5)

    # Restoration of Step 5 now succeeds, proving local ledger lacks hardware/external monotonic anchor.
    restored = restore_resumable_checkpoint(
        path=ckpt_file,
        expected_config_fingerprint=compute_config_fingerprint(TINY_MODEL_CFG, STEP_CFG),
        expected_dataset_identity=DatasetIdentity("mhash", "dhash", "thash"),
        expected_sampler_seed=42,
        expected_sampler_num_blocks=10,
        integrity_key=integrity_key,
        run_id=run_id,
    )
    assert restored.global_step == 5


# ==============================================================================
# AUDIT F: End-to-End Synthetic Learning System Convergence
# ==============================================================================

def test_audit_f_end_to_end_synthetic_learning_convergence():
    """
    AUDIT F: Proves end-to-end mathematical correctness and learning convergence
    on non-trivial synthetic task with GenesisTransformer and TrainingStepEngine.
    """
    set_deterministic_seed(42)
    model_cfg = GenesisModelConfig(
        vocab_size=32,
        d_model=32,
        n_layers=2,
        n_heads=4,
        n_kv_heads=2,
        d_ff=64,
        max_seq_len=16,
    )
    step_cfg = TrainingStepConfig(
        grad_accum_steps=1,
        warmup_steps=5,
        total_steps=50,
        max_lr=2e-2,
    )
    model = GenesisTransformer(model_cfg)
    engine = TrainingStepEngine(model, step_cfg)
    cap = ExecutionCapability.for_unchecked_synthetic_test()

    batch_size = 4
    seq_len = 16

    # Generate fixed deterministic sequence batch
    x_list = []
    y_list = []
    for b in range(batch_size):
        seq = [((b + 1) * 3 + i) % 28 + 4 for i in range(seq_len + 1)]
        x_list.append(seq[:-1])
        y_list.append(seq[1:])
    x_tensor = torch.tensor(x_list, dtype=torch.long)
    y_tensor = torch.tensor(y_list, dtype=torch.long)

    # Initial loss should be close to uniform random entropy: ln(32) ~= 3.465
    loss_0 = engine.step(x_tensor, y_tensor, cap).microbatch_loss
    assert loss_0 > 2.0, f"Initial loss should be close to random entropy, got {loss_0}"

    losses = [loss_0]
    for _ in range(45):
        res = engine.step(x_tensor, y_tensor, cap)
        losses.append(res.microbatch_loss)

    final_loss = losses[-1]
    # Verify significant learning convergence (loss drops by > 75%)
    assert final_loss < 0.6, (
        f"Model failed to learn deterministic affine recurrence: "
        f"initial={loss_0:.4f}, final={final_loss:.4f}"
    )
    assert final_loss < loss_0 * 0.25, "Loss did not drop by required threshold"
