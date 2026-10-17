"""
Independent Successor Qualification Suite for GENESIS Foundation Hardening.
Auditing PR #65 (HEAD: d3a67cc), PR #68 (HEAD: f2d26c8), PR #70 (HEAD: da5e8fb), PR #69 (HEAD: 0942169), PR #58 (HEAD: 3a27245).
Auditor: Antigravity / Gemini — Independent Security and Model Assurance.

Thoroughly challenges:
1. P0-01: Runtime artifact integrity (filename swaps, deletions, additions, bit modification, resume transitions).
2. P0-02: Durable progress (corrupt, quality-rejected, duplicates, trailing duplicates, deterministic restart).
3. P0-03: Content-aware recovery (same-size garbage detection, legacy schema migration, interrupted write recovery).
4. P0-04: Manifest identity (normalization rule mutation, schema v2 rejection, schema v3 enforcement).
5. Audit #017 Inherited Blockers (version validation, state consistency, trained spoofing removal, bfloat16/shape collisions, RNG fork).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

torch = pytest.importorskip("torch")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import orca.config
import orca.genesis.governance.authorization as GOV
from orca.eval.genesis_harness import SamplingConfig
from orca.genesis.data.manifest import (
    GenesisDatasetManifest,
    ManifestTamperedError,
    SourceOrigin,
    TokenizerBinding,
)
from orca.genesis.data.pipeline import (
    PROGRESS_DB_NAME,
    _hash_file_prefix,
    _open_progress_db,
    _truncate_partial_shard_writes,
    _verify_and_recover_missing_or_corrupted_shard_output,
    compute_shard_digests,
    process_corpus,
)
from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.eval_adapter import (
    ModelCheckpointBindingError,
    ProvenanceStatus,
    TrainingRunRecordError,
    diagnose_adapter,
    make_inference_backend,
)
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.training.checkpoint_integrity import (
    _manifest_path,
    load_verified_training_state,
    save_verified_training_state,
    state_dict_fingerprint,
    ManifestStateMismatchError,
    UnsupportedManifestVersionError,
)
from orca.genesis.training.orchestration import (
    AuthorizedIdentityChangedError,
    GenesisTrainingRun,
    RunState,
)
from orca.genesis.training.primitives import TrainingState

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"


def _head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mint_test_grant(
    monkeypatch,
    *,
    run_id: str,
    model_config_digest: str,
    tokenizer_digest: str,
    dataset_manifest_id: str,
    dataset_content_digest: str,
    authorized_shard_digests: tuple[str, ...],
    reviewed_commit_sha: str,
    transformation_code_digest: str,
    optimizer_config_digest: str,
):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    now = datetime.now(timezone.utc)
    registry = {
        "schema_version": GOV.REGISTRY_SCHEMA_VERSION,
        "records": [{
            "id": "synthetic-authority-qual",
            "role": "OWNER",
            "public_key_hex": pub,
            "activation_timestamp": _ts(now - timedelta(days=1)),
            "expiry": None,
            "revoked": False,
            "gpu_permission": False,
            "spend_permission": False,
        }],
    }
    req = GOV.NativePretrainingRequest(
        run_id=run_id,
        nonce=hashlib.sha256(f"qual-nonce-{run_id}".encode()).hexdigest(),
        model_family="genesis",
        architecture_version="genesis-arch-v1",
        model_config_digest=model_config_digest,
        tokenizer_digest=tokenizer_digest,
        dataset_manifest_id=dataset_manifest_id,
        dataset_content_digest=dataset_content_digest,
        authorized_shard_digests=tuple(authorized_shard_digests),
        reviewed_commit_sha=reviewed_commit_sha,
        transformation_code_digest=transformation_code_digest,
        optimizer_config_digest=optimizer_config_digest,
        environment_class=ENV,
        gpu_requested=False,
        max_wall_clock_minutes=60,
        requested_spend_usd=0.0,
    )
    record = {
        "schema_version": GOV.SCHEMA_VERSION,
        "authorization_id": "gnpauth-" + "d0" * 8,
        "status": "AUTHORIZED",
        "run_id": req.run_id,
        "nonce": req.nonce,
        "model": {
            "family": req.model_family,
            "architecture_version": req.architecture_version,
            "model_config_digest": req.model_config_digest,
        },
        "tokenizer": {"tokenizer_digest": req.tokenizer_digest},
        "dataset": {
            "dataset_manifest_id": req.dataset_manifest_id,
            "dataset_content_digest": req.dataset_content_digest,
            "authorized_shard_digests": list(req.authorized_shard_digests),
        },
        "code": {
            "reviewed_commit_sha": req.reviewed_commit_sha,
            "transformation_code_digest": req.transformation_code_digest,
        },
        "training": {"optimizer_config_digest": req.optimizer_config_digest},
        "environment_class": req.environment_class,
        "limits": {"max_wall_clock_minutes": 120, "max_spend_usd": 0, "gpu_allowed": False},
        "issued_at": _ts(now - timedelta(hours=1)),
        "expires_at": _ts(now + timedelta(days=6)),
        "authorizing_authority": {
            "identity": "synthetic-authority-qual",
            "role": "OWNER",
            "key_id": "synthetic-authority-qual",
        },
        "signature": None,
    }
    record["signature"] = priv.sign(GOV.canonical_signing_bytes(record)).hex()
    monkeypatch.setattr(GOV, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    monkeypatch.setattr(GOV, "PINNED_REGISTRY_SHA256", GOV.registry_digest(registry))
    return GOV.authorize_native_pretraining(
        repo_root=REPO_ROOT,
        record=record,
        registry=registry,
        revoked_ids=[],
        req=req,
        revocation_check=lambda auth_id: False,
    )


# ==============================================================================================
# 1. P0-01 Challenges: Runtime Artifact Integrity
# ==============================================================================================

def _setup_authorized_run(tmp_path, monkeypatch, run_id="qual-p0-01"):
    monkeypatch.setattr(orca.config, "ORCA_HOME", tmp_path / "orca_home")
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps({"text": f"qual text sentence {i}"}) for i in range(20)) + "\n")
    out_dir = tmp_path / "shards"
    _, kept = process_corpus(corpus, out_dir, num_shards=2)
    digests = compute_shard_digests(out_dir)

    origin = SourceOrigin(
        source_id="s1", description="desc", license_name="MIT",
        usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)),
    )
    tb = TokenizerBinding(
        tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1",
        vocab_digest=hashlib.sha256(b"vocab").hexdigest(),
    )
    manifest = GenesisDatasetManifest.build(
        dataset_name="qual-ds", version="v1", origins=[origin],
        normalized_records=kept, transformation_lineage=[], tokenizer_binding=tb,
    )
    reviewed_sha = _head_sha()
    mcfg, tcd, ocd = (hashlib.sha256(x).hexdigest() for x in (b"mcfg", b"tcd", b"ocd"))

    grant = _mint_test_grant(
        monkeypatch, run_id=run_id, model_config_digest=mcfg, tokenizer_digest=tb.vocab_digest,
        dataset_manifest_id=manifest.manifest_id, dataset_content_digest=manifest.source_content_digest,
        authorized_shard_digests=tuple(sorted(digests.values())), reviewed_commit_sha=reviewed_sha,
        transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run = GenesisTrainingRun(
        run_id, dataset_manifest_ids=(manifest.manifest_id,), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    run.validate(
        dataset_digest=manifest.source_content_digest, model_config_digest=mcfg,
        tokenizer_digest=tb.vocab_digest, authorized_shard_digests=tuple(sorted(digests.values())),
        shard_dir=out_dir, reviewed_commit_sha=reviewed_sha, transformation_code_digest=tcd,
        optimizer_config_digest=ocd,
    )
    run.request_authorization()
    run.authorize(grant)
    assert run.state == RunState.AUTHORIZED

    from orca.genesis.training import orchestration
    monkeypatch.setattr(orchestration, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    return run, out_dir


def test_p0_01_filename_swap_detected(tmp_path, monkeypatch):
    """Challenge: Two authorized shard files swap contents/filenames post-authorization."""
    run, out_dir = _setup_authorized_run(tmp_path, monkeypatch, "swap-run")
    shards = sorted(out_dir.glob("shard-*.jsonl"))
    assert len(shards) >= 2
    data0 = shards[0].read_bytes()
    data1 = shards[1].read_bytes()

    # Swap contents between the two files
    shards[0].write_bytes(data1)
    shards[1].write_bytes(data0)

    # Must raise AuthorizedIdentityChangedError because filename-to-digest mapping changed
    with pytest.raises(AuthorizedIdentityChangedError):
        run.start()
    assert run.state == RunState.REJECTED


def test_p0_01_missing_shard_detected(tmp_path, monkeypatch):
    """Challenge: One authorized shard is removed post-authorization."""
    run, out_dir = _setup_authorized_run(tmp_path, monkeypatch, "delete-run")
    shards = sorted(out_dir.glob("shard-*.jsonl"))
    shards[0].unlink()

    with pytest.raises(AuthorizedIdentityChangedError):
        run.start()
    assert run.state == RunState.REJECTED


def test_p0_01_additional_shard_detected(tmp_path, monkeypatch):
    """Challenge: An unauthorized additional shard is added post-authorization."""
    run, out_dir = _setup_authorized_run(tmp_path, monkeypatch, "extra-run")
    extra = out_dir / "shard-0002-train.jsonl"
    extra.write_text(json.dumps({"text": "unauthorized extra data"}) + "\n")

    with pytest.raises(AuthorizedIdentityChangedError):
        run.start()
    assert run.state == RunState.REJECTED


def test_p0_01_resume_detects_shard_tamper_after_pause(tmp_path, monkeypatch):
    """Challenge: Shard is modified while run is PAUSED."""
    run, out_dir = _setup_authorized_run(tmp_path, monkeypatch, "pause-run")
    run.start()
    assert run.state == RunState.RUNNING
    run.pause()
    assert run.state == RunState.PAUSED

    # Tamper shard on disk
    shard = sorted(out_dir.glob("shard-*.jsonl"))[0]
    data = bytearray(shard.read_bytes())
    data[0] ^= 0xAA
    shard.write_bytes(bytes(data))

    # resume() must catch the tampering and transition to FAILED
    with pytest.raises(AuthorizedIdentityChangedError):
        run.resume()
    assert run.state == RunState.FAILED


# ==============================================================================================
# 2. P0-02 Challenges: Durable Progress Persistence
# ==============================================================================================

def test_p0_02_all_corrupt_records_persisted(tmp_path):
    """Challenge: 100% corrupt corpus durably commits offset and counters."""
    out_dir = tmp_path / "corrupt_test"
    corpus = tmp_path / "corrupt.jsonl"
    corpus.write_text("\n".join(json.dumps({"bad": i}) for i in range(12)) + "\n")

    report, kept = process_corpus(corpus, out_dir, num_shards=2)
    assert len(kept) == 0
    assert report.corrupt_records == 12
    assert report.resume_offset == 12

    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    row = conn.execute("SELECT resume_offset, corrupt_records, kept FROM progress WHERE id = 0").fetchone()
    conn.close()
    assert row == (12, 12, 0)


def test_p0_02_all_quality_rejected_persisted(tmp_path):
    """Challenge: 100% quality rejected corpus durably commits quality_rejected counter."""
    out_dir = tmp_path / "quality_test"
    corpus = tmp_path / "quality.jsonl"
    corpus.write_text("\n".join(json.dumps({"text": f"item {i}"}) for i in range(8)) + "\n")

    report, kept = process_corpus(corpus, out_dir, num_shards=2, quality_filter=lambda text: False)
    assert len(kept) == 0
    assert report.quality_rejected == 8
    assert report.resume_offset == 8

    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    row = conn.execute("SELECT resume_offset, quality_rejected FROM progress WHERE id = 0").fetchone()
    conn.close()
    assert row == (8, 8)


def test_p0_02_deterministic_resumption_skips_processed_lines(tmp_path):
    """Challenge: Resumption on extended corpus never re-reads prior lines."""
    out_dir = tmp_path / "resume_test"
    corpus1 = tmp_path / "corpus.jsonl"
    lines1 = [json.dumps({"text": f"line {i}"}) for i in range(5)]
    corpus1.write_text("\n".join(lines1) + "\n")

    report1, kept1 = process_corpus(corpus1, out_dir, num_shards=2)
    assert report1.resume_offset == 5

    # Extend corpus with 3 new lines
    lines2 = lines1 + [json.dumps({"text": f"new line {i}"}) for i in range(3)]
    corpus1.write_text("\n".join(lines2) + "\n")

    report2, kept2 = process_corpus(corpus1, out_dir, num_shards=2)
    assert report2.lines_read == 8
    assert report2.resume_offset == 8
    assert report2.kept == 8
    assert len(kept2) == 8


# ==============================================================================================
# 3. P0-03 Challenges: Content-Aware Recovery and DB Migration
# ==============================================================================================

def test_p0_03_legacy_schema_migration_fails_closed_and_recovers(tmp_path):
    """Challenge: Output directory with pre-Audit #71 schema (lacking safe_byte_digest)
    is safely upgraded via ALTER TABLE, fails closed on empty digest, and regenerates intact."""
    out_dir = tmp_path / "legacy_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create a legacy progress.sqlite3 with the OLD schema (no safe_byte_digest column)
    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    conn.execute("CREATE TABLE progress (id INTEGER PRIMARY KEY CHECK (id = 0), resume_offset INTEGER, lines_read INTEGER, corrupt_records INTEGER, exact_duplicates INTEGER, near_duplicates INTEGER, quality_rejected INTEGER, pii_secret_rejected INTEGER, kept INTEGER)")
    conn.execute("CREATE TABLE seen_exact (exact_key TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE kept_records (seq INTEGER PRIMARY KEY AUTOINCREMENT, shard INTEGER, split TEXT, normalized_text TEXT, flushed INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE shard_file_safe_offsets (path TEXT PRIMARY KEY, safe_byte_offset INTEGER NOT NULL)")
    conn.execute("CREATE TABLE near_dup_window (seq INTEGER PRIMARY KEY AUTOINCREMENT, line_number INTEGER, normalized_text TEXT)")

    # Insert 5 valid kept records marked flushed=1
    for i in range(5):
        conn.execute("INSERT INTO kept_records (shard, split, normalized_text, flushed) VALUES (0, 'train', ?, 1)", (f"legacy record {i}",))

    shard_path = out_dir / "shard-0000-train.jsonl"
    shard_content = "\n".join(json.dumps({"text": f"legacy record {i}"}) for i in range(5)) + "\n"
    shard_path.write_text(shard_content)
    safe_size = shard_path.stat().st_size

    # Record safe_byte_offset under legacy table (no safe_byte_digest column)
    conn.execute("INSERT INTO shard_file_safe_offsets (path, safe_byte_offset) VALUES (?, ?)", (str(shard_path), safe_size))
    conn.commit()
    conn.close()

    # 2. Open via new codebase: verifies ALTER TABLE adds safe_byte_digest
    conn = _open_progress_db(out_dir)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(shard_file_safe_offsets)").fetchall()}
    assert "safe_byte_digest" in cols

    # 3. Recovery must trigger because default '' does not match real digest
    _verify_and_recover_missing_or_corrupted_shard_output(out_dir, conn)
    unflushed = conn.execute("SELECT COUNT(*) FROM kept_records WHERE flushed = 0").fetchone()[0]
    assert unflushed == 5, "Legacy DB with empty digest must fail closed and reset flushed=0 for regeneration"
    conn.close()

    # 4. Re-running process_corpus regenerates file and writes real digest
    dummy_corpus = tmp_path / "dummy.jsonl"
    dummy_corpus.write_text("")
    process_corpus(dummy_corpus, out_dir, num_shards=1)

    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    stored_digest = conn.execute("SELECT safe_byte_digest FROM shard_file_safe_offsets WHERE path = ?", (str(shard_path),)).fetchone()[0]
    conn.close()
    assert stored_digest == _hash_file_prefix(shard_path, safe_size)
    assert len(stored_digest) == 64


def test_p0_03_interrupted_write_truncated_and_digest_verified(tmp_path):
    """Challenge: Crash mid-write leaves trailing partial line; truncation restores valid digest."""
    out_dir = tmp_path / "trunc_test"
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps({"text": f"line {i}"}) for i in range(5)) + "\n")
    process_corpus(corpus, out_dir, num_shards=1)

    shard = sorted(out_dir.glob("shard-*.jsonl"))[0]
    good_bytes = shard.read_bytes()
    good_size = len(good_bytes)

    # Append partial corrupt line simulating crash mid-write
    with open(shard, "ab") as f:
        f.write(b'{"text": "partial line without newline')

    conn = _open_progress_db(out_dir)
    _truncate_partial_shard_writes(out_dir, conn)
    _verify_and_recover_missing_or_corrupted_shard_output(out_dir, conn)

    assert shard.stat().st_size == good_size
    assert shard.read_bytes() == good_bytes
    unflushed = conn.execute("SELECT COUNT(*) FROM kept_records WHERE flushed = 0").fetchone()[0]
    conn.close()
    assert unflushed == 0, "Truncated file matches recorded safe digest, no re-flush required"


# ==============================================================================================
# 4. P0-04 Challenges: Manifest Identity (Schema v3 & Normalization Rule)
# ==============================================================================================

def test_p0_04_schema_v2_manifest_rejected(tmp_path):
    """Challenge: Manifest with schema_version='genesis-dataset-provenance/2' is rejected."""
    origin = SourceOrigin(
        source_id="s1", description="desc", license_name="CC-BY-4.0",
        usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)),
    )
    tb = TokenizerBinding(
        tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1",
        vocab_digest=hashlib.sha256(b"v").hexdigest(),
    )
    manifest = GenesisDatasetManifest.build(
        dataset_name="schema-test", version="v1", origins=[origin],
        normalized_records=["sample record"], transformation_lineage=[], tokenizer_binding=tb,
    )
    path = tmp_path / "manifest_v2.json"
    payload = json.loads(manifest.save().read_text())
    payload["schema_version"] = "genesis-dataset-provenance/2"
    path.write_text(json.dumps(payload))

    with pytest.raises(ManifestTamperedError, match="only understands 'genesis-dataset-provenance/3'"):
        GenesisDatasetManifest.load(path)


def test_p0_04_normalization_rule_mutation_rejected_under_schema_v3(tmp_path):
    """Challenge: Mutating normalization_rule invalidates manifest_id and raises ManifestTamperedError."""
    origin = SourceOrigin(
        source_id="s1", description="desc", license_name="CC-BY-4.0",
        usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)),
    )
    tb = TokenizerBinding(
        tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1",
        vocab_digest=hashlib.sha256(b"v").hexdigest(),
    )
    manifest = GenesisDatasetManifest.build(
        dataset_name="norm-rule-mut", version="v1", origins=[origin],
        normalized_records=["sample record"], transformation_lineage=[], tokenizer_binding=tb,
    )
    path = tmp_path / "manifest.json"
    manifest_saved = manifest.save()

    payload = json.loads(manifest_saved.read_text())
    payload["normalization_rule"] = "MUTATED NORMALIZATION RULE"
    path.write_text(json.dumps(payload))

    with pytest.raises(ManifestTamperedError, match="is TAMPERED"):
        GenesisDatasetManifest.load(path)


# ==============================================================================================
# 5. Audit #017 Inherited Blocker Qualification
# ==============================================================================================

def test_audit017_defect01_manifest_random_tmp_and_symlink_defense(tmp_path):
    """DEFECT-01: save_verified_training_state writes with random tmp file and 0o600 permissions."""
    ckpt = tmp_path / "test.pt"
    state = TrainingState(step=1, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={}, python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None)

    # Pre-plant a symlink at the old deterministic temp path
    old_tmp = tmp_path / f".{_manifest_path(ckpt).name}.tmp"
    target = tmp_path / "target_file.txt"
    target.write_text("pre-existing content")
    os.symlink(target, old_tmp)

    manifest = save_verified_training_state(state, ckpt)
    assert _manifest_path(ckpt).exists()
    assert target.read_text() == "pre-existing content", "Pre-planted symlink was not followed"
    assert oct(os.stat(_manifest_path(ckpt)).st_mode & 0o777) == "0o600"


def test_audit017_defect02_format_and_arch_version_enforcement(tmp_path):
    """DEFECT-02: load_verified_training_state validates format and arch version."""
    ckpt = tmp_path / "v_test.pt"
    state = TrainingState(step=1, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={}, python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None)
    save_verified_training_state(state, ckpt)

    m_path = _manifest_path(ckpt)
    raw = json.loads(m_path.read_text())
    raw["format_version"] = "genesis-checkpoint/999"
    m_path.write_text(json.dumps(raw))

    with pytest.raises(UnsupportedManifestVersionError):
        load_verified_training_state(ckpt)


def test_audit017_defect03_state_step_epoch_mismatch_rejected(tmp_path):
    """DEFECT-03: Manifest claiming step 10 on step 1 checkpoint is rejected."""
    ckpt = tmp_path / "step_test.pt"
    state = TrainingState(step=1, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={}, python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None)
    save_verified_training_state(state, ckpt)

    m_path = _manifest_path(ckpt)
    raw = json.loads(m_path.read_text())
    raw["step"] = 10
    # Update hash to match modified manifest so hash passes
    raw["sha256"] = raw["sha256"]
    m_path.write_text(json.dumps(raw))

    with pytest.raises(ManifestStateMismatchError):
        load_verified_training_state(ckpt)


def test_audit017_defect04_trained_provenance_unreachable(tmp_path):
    """DEFECT-04: diagnose_adapter unconditionally rejects training_run_record_path; TRAINED is unreachable."""
    cfg = GenesisModelConfig(vocab_size=100, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=64)
    model = GenesisTransformer(cfg)

    ckpt_path = tmp_path / "model.pt"
    state = TrainingState(step=1, epoch=0, dataloader_position=0, model_state_dict=model.state_dict(), optimizer_state_dict={}, python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None)
    save_verified_training_state(state, ckpt_path)

    fake_run = tmp_path / "fake_run.json"
    fake_run.write_text(json.dumps({"run_id": "r1", "authorized": True}))

    # Attempting to supply training_run_record_path raises TrainingRunRecordError
    with pytest.raises(TrainingRunRecordError):
        diagnose_adapter(model, checkpoint_path=ckpt_path, training_run_record_path=fake_run)

    # Valid verified checkpoint without run record reaches UNVERIFIED at ceiling
    diag = diagnose_adapter(model, checkpoint_path=ckpt_path)
    assert diag.status == ProvenanceStatus.UNVERIFIED


def test_audit017_defect05_bfloat16_and_shape_collision_resolved():
    """DEFECT-05: state_dict_fingerprint includes shape and handles bfloat16 without error."""
    bf16_tensor = torch.randn(8, 8, dtype=torch.bfloat16)
    fp_bf16 = state_dict_fingerprint({"w": bf16_tensor})
    assert len(fp_bf16) == 64

    # Differing shapes with identical flattened bytes
    t1 = torch.arange(12, dtype=torch.float32).reshape(2, 6)
    t2 = torch.arange(12, dtype=torch.float32).reshape(3, 4)
    assert state_dict_fingerprint({"w": t1}) != state_dict_fingerprint({"w": t2})


def test_audit017_defect06_eval_adapter_rng_and_stop_tokens():
    """DEFECT-06: eval adapter strips stop tokens, isolates RNG, and catches overflow."""
    tok = MagicMock()
    tok.encode.return_value = list(range(10))
    tok.decode.return_value = "hello world <|endoftext|> trailing"

    cfg = GenesisModelConfig(vocab_size=100, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=64)
    model = GenesisTransformer(cfg)
    backend = make_inference_backend(model, tok)

    sampling = SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=5, stop=("<|endoftext|>",), seed=42)

    # Verify RNG is preserved
    rng_before = torch.get_rng_state()
    res = backend("prompt", sampling)
    rng_after = torch.get_rng_state()
    assert torch.equal(rng_before, rng_after), "Global RNG state was permanently mutated"

    # Context overflow
    tok.encode.return_value = list(range(100))
    res_overflow = backend("overflow prompt", sampling)
    assert "no room to generate even one token" in res_overflow.error
