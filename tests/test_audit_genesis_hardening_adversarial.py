"""
Independent Adversarial Audit Regression Suite for GENESIS Foundation Hardening
Auditing PR #65, PR #68, PR #69, PR #70

Reproducing and verifying:
- AUDIT-P0-01: Post-authorization artifact tampering undetected during execution transitions
- AUDIT-P0-02: Progress-state persistence failure when batch ends with rejected records or 0 kept records
- AUDIT-P0-03: Artifact recovery integrity check bypassed by same-size or padded content tampering
- AUDIT-P0-04: Manifest identity unchanged when normalization_rule is mutated
- AUDIT-P1-01: Marker deletion allows grant replay and local-only replay boundary lacks cross-host protection
- AUDIT-P1-02: Cross-split screening scalability limit and batching leakage blind spot
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import orca.config
import orca.genesis.governance.authorization as GOV
from orca.genesis.data.contamination import (
    CrossSplitScreeningTooLargeError,
    find_near_duplicates_across_splits,
)
from orca.genesis.data.manifest import (
    GenesisDatasetManifest,
    SourceOrigin,
    TokenizerBinding,
    TransformationStep,
)
from orca.genesis.data.pipeline import (
    PROGRESS_DB_NAME,
    _open_progress_db,
    _verify_and_recover_missing_or_corrupted_shard_output,
    compute_shard_digests,
    process_corpus,
)
from orca.genesis.training.orchestration import (
    _claim_native_pretraining_authorization,
    GenesisTrainingRun,
    RunState,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"


def _head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mint_synthetic_grant(
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
            "id": "synthetic-authority-audit",
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
        nonce=hashlib.sha256(f"audit-nonce-{run_id}".encode()).hexdigest(),
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
        "authorization_id": "gnpauth-" + "f0" * 8,
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
            "identity": "synthetic-authority-audit",
            "role": "OWNER",
            "key_id": "synthetic-authority-audit",
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
# AUDIT-P0-01: Post-authorization artifact tampering
# ==============================================================================================
def test_audit_p0_01_post_authorization_shard_tampering_undetected(tmp_path, monkeypatch):
    """Confirm AUDIT-P0-01: An authorized shard modified AFTER authorize()
    leaves the in-memory run identity unchanged, allowing start(), pause(),
    and resume() transitions without detecting that disk files were altered."""
    monkeypatch.setattr(orca.config, "ORCA_HOME", tmp_path / "orca_home")
    corpus_path = tmp_path / "raw_corpus.jsonl"
    corpus_path.write_text("\n".join(json.dumps({"text": f"audit record {i} for topic {i}"}) for i in range(10)) + "\n")
    out_dir = tmp_path / "shards"
    _, kept_records = process_corpus(corpus_path, out_dir, num_shards=2)
    original_digests = compute_shard_digests(out_dir)

    origin = SourceOrigin(
        source_id="s1", description="desc", license_name="MIT",
        usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)),
    )
    tb = TokenizerBinding(
        tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1",
        vocab_digest=hashlib.sha256(b"vocab").hexdigest(),
    )
    manifest = GenesisDatasetManifest.build(
        dataset_name="audit-ds", version="v1", origins=[origin],
        normalized_records=kept_records, transformation_lineage=[], tokenizer_binding=tb,
    )

    reviewed_commit_sha = _head_sha()
    mcfg = hashlib.sha256(b"mcfg").hexdigest()
    tcd = hashlib.sha256(b"tcd").hexdigest()
    ocd = hashlib.sha256(b"ocd").hexdigest()

    grant = _mint_synthetic_grant(
        monkeypatch, run_id="p0-01-tamper-run", model_config_digest=mcfg,
        tokenizer_digest=tb.vocab_digest, dataset_manifest_id=manifest.manifest_id,
        dataset_content_digest=manifest.source_content_digest,
        authorized_shard_digests=tuple(sorted(original_digests.values())),
        reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=tcd,
        optimizer_config_digest=ocd,
    )

    run = GenesisTrainingRun(
        "p0-01-tamper-run", dataset_manifest_ids=(manifest.manifest_id,),
        environment_class=ENV, repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    run.validate(
        dataset_manifest=manifest, dataset_records=kept_records,
        model_config_digest=mcfg,
        tokenizer_digest=tb.vocab_digest,
        authorized_shard_digests=tuple(sorted(original_digests.values())),
        shard_dir=out_dir,
        reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=tcd,
        optimizer_config_digest=ocd,
    )
    run.request_authorization()
    run.authorize(grant)
    assert run.state == RunState.AUTHORIZED

    # TAMPER: Post-authorization shard modification (same-size or substituted content)
    shard_file = sorted(out_dir.glob("shard-*.jsonl"))[0]
    original_bytes = shard_file.read_bytes()
    tampered_bytes = bytearray(original_bytes)
    tampered_bytes[0] ^= 0x55  # flip bits without changing size
    shard_file.write_bytes(bytes(tampered_bytes))

    tampered_digests = compute_shard_digests(out_dir)
    assert tampered_digests != original_digests, "Shard on disk was successfully modified"

    # Simulate acceptance ledger approved for execution
    from orca.genesis.training import orchestration
    monkeypatch.setattr(orchestration, "check_founder_acceptance_ledger", lambda repo_root, **_: [])

    # VULNERABILITY DEMONSTRATION: start() succeeds despite tampered shard on disk!
    run.start()
    assert run.state == RunState.RUNNING

    # pause() and resume() also succeed without detecting the modified bytes!
    run.pause()
    assert run.state == RunState.PAUSED
    run.resume()
    assert run.state == RunState.RUNNING


# ==============================================================================================
# AUDIT-P0-02: Progress-state persistence
# ==============================================================================================
def test_audit_p0_02_progress_not_persisted_when_run_ends_with_rejected_records(tmp_path):
    """Confirm AUDIT-P0-02: When a corpus ends with rejected/duplicate records
    (or has 0 kept records), _commit_batch() early-returns because `pending`
    is empty, failing to commit the final resume_offset and rejection counters."""
    out_dir = tmp_path / "processed_p0_02"

    # Corpus has 5 lines, all of which are malformed/corrupt (0 kept records)
    corrupt_corpus = tmp_path / "corrupt_corpus.jsonl"
    corrupt_corpus.write_text("\n".join(json.dumps({"malformed": i}) for i in range(5)) + "\n")

    report1, kept1 = process_corpus(corrupt_corpus, out_dir, num_shards=2)
    assert len(kept1) == 0
    assert report1.corrupt_records == 5
    assert report1.resume_offset == 5

    # Check durable SQLite state
    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    row = conn.execute("SELECT resume_offset, corrupt_records FROM progress WHERE id = 0").fetchone()
    conn.close()

    # VULNERABILITY DEMONSTRATION: Nothing was committed because pending was empty!
    assert row is None, "SQLite progress row was never inserted because _commit_batch early-exits on empty pending"

    # Now run a second time (simulating resumption or restart):
    report2, kept2 = process_corpus(corrupt_corpus, out_dir, num_shards=2)
    # Because resume_offset was not committed, it restarts from line 0!
    # If progress had been persisted, lines_read on resumption would be 0 (already done)
    # But here it re-reads all 5 lines again!
    assert report2.corrupt_records == 5


def test_audit_p0_02_progress_trailing_duplicates_not_persisted(tmp_path):
    """Confirm AUDIT-P0-02 with kept records followed by trailing duplicates:
    trailing duplicates are never flushed to the progress table."""
    out_dir = tmp_path / "processed_p0_02_trailing"

    # 1 valid record, followed by 5 duplicate records, with commit_batch_size=1
    corpus = tmp_path / "trailing_dup.jsonl"
    lines = [json.dumps({"text": "unique first record"})]
    for _ in range(5):
        lines.append(json.dumps({"text": "unique first record"}))  # exact duplicates
    corpus.write_text("\n".join(lines) + "\n")

    report, kept = process_corpus(corpus, out_dir, num_shards=2, commit_batch_size=1)
    assert len(kept) == 1
    assert report.exact_duplicates == 5
    assert report.resume_offset == 6

    # Check durable SQLite state
    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    row = conn.execute("SELECT resume_offset, exact_duplicates FROM progress WHERE id = 0").fetchone()
    conn.close()

    # The first record committed with resume_offset=1 and exact_duplicates=0.
    # The trailing 5 duplicates never committed because pending was empty!
    assert row is not None
    persisted_offset, persisted_dups = row
    assert persisted_offset == 1, "Trailing duplicates failed to advance persisted resume_offset from 1 to 6"
    assert persisted_dups == 0, "Trailing duplicates failed to persist rejection count (persisted 0 instead of 5)"


# ==============================================================================================
# AUDIT-P0-03: Artifact recovery integrity
# ==============================================================================================
def test_audit_p0_03_artifact_recovery_fooled_by_same_size_tampering(tmp_path):
    """Confirm AUDIT-P0-03: _verify_and_recover_missing_or_corrupted_shard_output()
    only inspects file size (actual_size >= safe_offset) and is completely fooled
    by equal-size garbage substitution or truncation+padding."""
    out_dir = tmp_path / "processed_p0_03"
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps({"text": f"record {i} for recovery testing"}) for i in range(10)) + "\n")

    _, kept = process_corpus(corpus, out_dir, num_shards=1)
    shard_file = sorted(out_dir.glob("shard-*.jsonl"))[0]
    original_content = shard_file.read_bytes()
    safe_size = len(original_content)

    # TAMPER: Replace shard content with junk bytes of the EXACT SAME SIZE
    junk_content = b"X" * safe_size
    shard_file.write_bytes(junk_content)

    conn = _open_progress_db(out_dir)
    # Call recovery function directly
    _verify_and_recover_missing_or_corrupted_shard_output(out_dir, conn)

    # Check if flushed was reset to 0 to trigger regeneration
    unflushed_count = conn.execute("SELECT COUNT(*) FROM kept_records WHERE flushed = 0").fetchone()[0]
    conn.close()

    # VULNERABILITY DEMONSTRATION: unflushed_count is 0! It accepted the corrupted file!
    assert unflushed_count == 0, "Tampered shard with identical byte size was silently accepted without regeneration"
    assert shard_file.read_bytes() == junk_content, "Corrupted junk bytes remain in the shard file"


# ==============================================================================================
# AUDIT-P0-04: Manifest identity
# ==============================================================================================
def test_audit_p0_04_manifest_id_invariant_under_normalization_rule_mutation(tmp_path):
    """Confirm AUDIT-P0-04: Modifying normalization_rule in a saved dataset manifest
    does NOT alter the computed manifest_id, allowing arbitrary normalization rule
    mutation without failing integrity verification."""
    origin = SourceOrigin(
        source_id="src1", description="desc", license_name="CC-BY-4.0",
        usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)),
    )
    tb = TokenizerBinding(
        tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1",
        vocab_digest=hashlib.sha256(b"vocab").hexdigest(),
    )
    manifest = GenesisDatasetManifest.build(
        dataset_name="norm-rule-test", version="v1", origins=[origin],
        normalized_records=["sample record alpha", "sample record beta"],
        transformation_lineage=[], tokenizer_binding=tb,
    )

    manifest_file = tmp_path / "manifest.json"
    payload = {
        "schema_version": manifest.schema_version,
        "manifest_id": manifest.manifest_id,
        "dataset_name": manifest.dataset_name,
        "version": manifest.version,
        "origins": [{"source_id": "src1", "description": "desc", "license_name": "CC-BY-4.0", "usage_restrictions": "none", "retrieved_at": manifest.origins[0].retrieved_at}],
        "source_record_count": manifest.source_record_count,
        "source_content_digest": manifest.source_content_digest,
        "normalization_rule": manifest.normalization_rule,
        "transformation_lineage": [],
        "tokenizer_binding": {"tokenizer_model_path": "/tmp/t.model", "architecture_version": "genesis-arch-v1", "vocab_digest": tb.vocab_digest},
        "created_at": manifest.created_at,
    }
    manifest_file.write_text(json.dumps(payload))

    # Verify original loads cleanly
    loaded = GenesisDatasetManifest.load(manifest_file)
    assert loaded.manifest_id == manifest.manifest_id

    # TAMPER: Mutate normalization_rule to a completely different / malicious rule
    payload["normalization_rule"] = "ATTACK_PAYLOAD: NO NORMALIZATION APPLIED"
    manifest_file.write_text(json.dumps(payload))

    # VULNERABILITY DEMONSTRATION: load() passes with zero error because normalization_rule is omitted from _binding_fields!
    loaded_tampered = GenesisDatasetManifest.load(manifest_file)
    assert loaded_tampered.manifest_id == manifest.manifest_id
    assert loaded_tampered.normalization_rule == "ATTACK_PAYLOAD: NO NORMALIZATION APPLIED"


# ==============================================================================================
# AUDIT-P1-01: Replay and concurrency limits
# ==============================================================================================
def test_audit_p1_01_marker_deletion_allows_replay_and_no_cross_host_isolation(tmp_path, monkeypatch):
    """Confirm AUDIT-P1-01:
    1. Marker deletion allows authorization_id to be reclaimed.
    2. Local filesystem claim does not provide cross-host replay isolation."""
    monkeypatch.setattr(orca.config, "ORCA_HOME", tmp_path / "host_a")
    auth_id = "gnpauth-1122334455667788"

    # First claim succeeds on Host A
    assert _claim_native_pretraining_authorization(auth_id) is True
    # Replay on Host A fails
    assert _claim_native_pretraining_authorization(auth_id) is False

    # Marker deletion allows reclaim
    marker = tmp_path / "host_a" / "genesis" / "training" / "native_pretraining_authorizations" / f"{auth_id}.claimed"
    assert marker.exists()
    marker.unlink()
    # Now it can be re-claimed!
    assert _claim_native_pretraining_authorization(auth_id) is True

    # Cross-host replay: Host B has its own independent ORCA_HOME
    monkeypatch.setattr(orca.config, "ORCA_HOME", tmp_path / "host_b")
    # Same auth_id succeeds on Host B because claim is local-only!
    assert _claim_native_pretraining_authorization(auth_id) is True


# ==============================================================================================
# AUDIT-P1-02: Contamination and scale
# ==============================================================================================
def test_audit_p1_02_cross_split_screening_limits_and_batching_leakage_blindspot():
    """Confirm AUDIT-P1-02:
    1. find_near_duplicates_across_splits enforces hard 5,000-record limit.
    2. Batching cross-split screening misses near-duplicates spanning different batches."""
    # 1. Test 5,000 record limit
    splits_large = {
        "train": [f"train text sentence {i}" for i in range(2501)],
        "val": [f"val text sentence {i}" for i in range(2500)],
    }
    with pytest.raises(CrossSplitScreeningTooLargeError):
        find_near_duplicates_across_splits(splits_large)

    # 2. Test batching leakage blind spot
    # Record A in train batch 1, Record B in val batch 2 (near duplicate with Jaccard > 0.85)
    text_a = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho"
    text_b = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi sigma"

    batch1 = {"train": [text_a], "val": ["unrelated text one"]}
    batch2 = {"train": ["unrelated text two"], "val": [text_b]}

    # Screening within batch 1: clean
    res1 = find_near_duplicates_across_splits(batch1)
    assert len(res1) == 0

    # Screening within batch 2: clean
    res2 = find_near_duplicates_across_splits(batch2)
    assert len(res2) == 0

    # But combined corpus has leakage!
    combined = {"train": [text_a, "unrelated text two"], "val": ["unrelated text one", text_b]}
    res_combined = find_near_duplicates_across_splits(combined)
    assert len(res_combined) > 0, "Cross-batch near-duplicate leakage exists but is blind to chunked screening"
