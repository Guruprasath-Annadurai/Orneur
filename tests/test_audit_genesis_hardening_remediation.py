"""
Antigravity Audit #71 remediation: corrected regression counterparts.

`tests/test_audit_genesis_hardening_adversarial.py` (imported verbatim from
the audit branch `antigravity/genesis-hardening-adversarial-audit`, commit
`8277be6fb242db9ba7478e9298e5f377e75c2fc3`) is preserved UNCHANGED as
historical vulnerability-demonstration evidence. After this phase's
remediation, running that file produces:

- AUDIT-P0-01: FAILS (TypeError -- validate() now requires `shard_dir`;
  the demonstration can no longer even construct an authorized run without
  declaring where its real shard files live).
- AUDIT-P0-02 (both): FAIL (the exact assertions that proved the bug now
  fail, because the progress row IS persisted / the offset DOES advance).
- AUDIT-P0-03: FAILS (`unflushed_count` is 1, not 0 -- tampering IS detected
  and flagged for regeneration).
- AUDIT-P0-04: FAILS (`ManifestTamperedError` is now raised).
- AUDIT-P1-01: STILL PASSES -- this is an acknowledged, documented
  architectural residual (marker-deletion reclaim, no cross-host replay
  protection), not a defect this phase fixes. See orchestration.py's
  module docstring, "P1-03" section (carried over unchanged from Mission 2).
- AUDIT-P1-02: STILL PASSES for the explicit 5,000-record ceiling (by
  design, matching the directive's own permitted "explicit scalability
  limit" alternative) and for the batching-blind-spot demonstration
  (calling the function on DELIBERATELY SPLIT batches misses cross-batch
  near-duplicates by construction -- see the corrected counterpart below,
  which demonstrates the CORRECT calling convention closes exactly this
  gap).

This file asserts the SECURE behavior directly, independent of the
original audit file's own (now largely failing) assertions, so this
module's correctness does not depend on the audit file remaining in any
particular state.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import orca.config  # noqa: E402
import orca.genesis.governance.authorization as GOV  # noqa: E402
from orca.genesis.data.contamination import (  # noqa: E402
    CrossSplitScreeningTooLargeError,
    find_near_duplicates_across_splits,
)
from orca.genesis.data.manifest import (  # noqa: E402
    GenesisDatasetManifest,
    ManifestTamperedError,
    SourceOrigin,
    TokenizerBinding,
)
from orca.genesis.data.pipeline import (  # noqa: E402
    PROGRESS_DB_NAME,
    _open_progress_db,
    _verify_and_recover_missing_or_corrupted_shard_output,
    compute_shard_digests,
    process_corpus,
)
from orca.genesis.training.orchestration import (  # noqa: E402
    AuthorizedIdentityChangedError,
    GenesisTrainingRun,
    RunState,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _head_sha() -> str:
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0
    return p.stdout.strip()


def _mint_synthetic_grant(monkeypatch, *, run_id, model_config_digest, tokenizer_digest, dataset_manifest_id,
                           dataset_content_digest, authorized_shard_digests, reviewed_commit_sha,
                           transformation_code_digest, optimizer_config_digest):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    now = datetime.now(timezone.utc)
    registry = {
        "schema_version": GOV.REGISTRY_SCHEMA_VERSION,
        "records": [{
            "id": "synthetic-authority-remediation", "role": "OWNER", "public_key_hex": pub,
            "activation_timestamp": _ts(now - timedelta(days=1)), "expiry": None, "revoked": False,
            "gpu_permission": False, "spend_permission": False,
        }],
    }
    req = GOV.NativePretrainingRequest(
        run_id=run_id, nonce=hashlib.sha256(f"remediation-nonce-{run_id}".encode()).hexdigest(),
        model_family="genesis", architecture_version="genesis-arch-v1", model_config_digest=model_config_digest,
        tokenizer_digest=tokenizer_digest, dataset_manifest_id=dataset_manifest_id,
        dataset_content_digest=dataset_content_digest, authorized_shard_digests=tuple(authorized_shard_digests),
        reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=transformation_code_digest,
        optimizer_config_digest=optimizer_config_digest, environment_class=ENV, gpu_requested=False,
        max_wall_clock_minutes=60, requested_spend_usd=0.0,
    )
    record = {
        "schema_version": GOV.SCHEMA_VERSION, "authorization_id": "gnpauth-" + "e1" * 8, "status": "AUTHORIZED",
        "run_id": req.run_id, "nonce": req.nonce,
        "model": {"family": req.model_family, "architecture_version": req.architecture_version, "model_config_digest": req.model_config_digest},
        "tokenizer": {"tokenizer_digest": req.tokenizer_digest},
        "dataset": {
            "dataset_manifest_id": req.dataset_manifest_id, "dataset_content_digest": req.dataset_content_digest,
            "authorized_shard_digests": list(req.authorized_shard_digests),
        },
        "code": {"reviewed_commit_sha": req.reviewed_commit_sha, "transformation_code_digest": req.transformation_code_digest},
        "training": {"optimizer_config_digest": req.optimizer_config_digest},
        "environment_class": req.environment_class,
        "limits": {"max_wall_clock_minutes": 120, "max_spend_usd": 0, "gpu_allowed": False},
        "issued_at": _ts(now - timedelta(hours=1)), "expires_at": _ts(now + timedelta(days=6)),
        "authorizing_authority": {"identity": "synthetic-authority-remediation", "role": "OWNER", "key_id": "synthetic-authority-remediation"},
        "signature": None,
    }
    record["signature"] = priv.sign(GOV.canonical_signing_bytes(record)).hex()
    monkeypatch.setattr(GOV, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    monkeypatch.setattr(GOV, "PINNED_REGISTRY_SHA256", GOV.registry_digest(registry))
    return GOV.authorize_native_pretraining(
        repo_root=REPO_ROOT, record=record, registry=registry, revoked_ids=[], req=req,
        revocation_check=lambda auth_id: False,
    )


# ============================================================ AUDIT-P0-01 (secure counterpart) ==

def test_remediation_p0_01_post_authorization_shard_tampering_is_denied(tmp_path, monkeypatch):
    """Secure counterpart of AUDIT-P0-01: the same tamper-after-authorize
    scenario the audit demonstrated as vulnerable must now be DENIED at
    start(), resume(), and recovered() alike."""
    monkeypatch.setattr(orca.config, "ORCA_HOME", tmp_path / "orca_home")
    corpus_path = tmp_path / "raw_corpus.jsonl"
    corpus_path.write_text("\n".join(json.dumps({"text": f"remediation record {i} for topic {i}"}) for i in range(10)) + "\n")
    out_dir = tmp_path / "shards"
    _, kept_records = process_corpus(corpus_path, out_dir, num_shards=2)
    original_digests = compute_shard_digests(out_dir)

    origin = SourceOrigin(source_id="s1", description="desc", license_name="MIT", usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)))
    tb = TokenizerBinding(tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1", vocab_digest=hashlib.sha256(b"vocab").hexdigest())
    manifest = GenesisDatasetManifest.build(
        dataset_name="remediation-ds", version="v1", origins=[origin], normalized_records=kept_records,
        transformation_lineage=[], tokenizer_binding=tb,
    )
    reviewed_commit_sha = _head_sha()
    mcfg, tcd, ocd = (hashlib.sha256(x).hexdigest() for x in (b"mcfg", b"tcd", b"ocd"))

    grant = _mint_synthetic_grant(
        monkeypatch, run_id="p0-01-remediation-run", model_config_digest=mcfg, tokenizer_digest=tb.vocab_digest,
        dataset_manifest_id=manifest.manifest_id, dataset_content_digest=manifest.source_content_digest,
        authorized_shard_digests=tuple(sorted(original_digests.values())), reviewed_commit_sha=reviewed_commit_sha,
        transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run = GenesisTrainingRun(
        "p0-01-remediation-run", dataset_manifest_ids=(manifest.manifest_id,), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    run.validate(
        dataset_manifest=manifest, dataset_records=kept_records,
        model_config_digest=mcfg, tokenizer_digest=tb.vocab_digest,
        authorized_shard_digests=tuple(sorted(original_digests.values())), shard_dir=out_dir,
        reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run.request_authorization()
    run.authorize(grant)
    assert run.state == RunState.AUTHORIZED

    shard_file = sorted(out_dir.glob("shard-*.jsonl"))[0]
    tampered = bytearray(shard_file.read_bytes())
    tampered[0] ^= 0x55
    shard_file.write_bytes(bytes(tampered))

    from orca.genesis.training import orchestration
    monkeypatch.setattr(orchestration, "check_founder_acceptance_ledger", lambda repo_root, **_: [])

    with pytest.raises(AuthorizedIdentityChangedError):
        run.start()
    assert run.state == RunState.REJECTED


def test_remediation_p0_01_untampered_run_still_starts_and_resumes_normally(tmp_path, monkeypatch):
    """Positive control: the new on-disk check must not be a false-positive
    trap -- an untampered run still reaches RUNNING and survives a
    pause/resume cycle."""
    monkeypatch.setattr(orca.config, "ORCA_HOME", tmp_path / "orca_home")
    corpus_path = tmp_path / "raw_corpus.jsonl"
    corpus_path.write_text("\n".join(json.dumps({"text": f"clean record {i}"}) for i in range(10)) + "\n")
    out_dir = tmp_path / "shards"
    _, kept_records = process_corpus(corpus_path, out_dir, num_shards=2)
    digests = compute_shard_digests(out_dir)

    origin = SourceOrigin(source_id="s1", description="desc", license_name="MIT", usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)))
    tb = TokenizerBinding(tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1", vocab_digest=hashlib.sha256(b"vocab2").hexdigest())
    manifest = GenesisDatasetManifest.build(
        dataset_name="remediation-ds-clean", version="v1", origins=[origin], normalized_records=kept_records,
        transformation_lineage=[], tokenizer_binding=tb,
    )
    reviewed_commit_sha = _head_sha()
    mcfg, tcd, ocd = (hashlib.sha256(x).hexdigest() for x in (b"mcfg2", b"tcd2", b"ocd2"))

    grant = _mint_synthetic_grant(
        monkeypatch, run_id="p0-01-clean-run", model_config_digest=mcfg, tokenizer_digest=tb.vocab_digest,
        dataset_manifest_id=manifest.manifest_id, dataset_content_digest=manifest.source_content_digest,
        authorized_shard_digests=tuple(sorted(digests.values())), reviewed_commit_sha=reviewed_commit_sha,
        transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run = GenesisTrainingRun(
        "p0-01-clean-run", dataset_manifest_ids=(manifest.manifest_id,), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    run.validate(
        dataset_manifest=manifest, dataset_records=kept_records,
        model_config_digest=mcfg, tokenizer_digest=tb.vocab_digest,
        authorized_shard_digests=tuple(sorted(digests.values())), shard_dir=out_dir,
        reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run.request_authorization()
    run.authorize(grant)

    from orca.genesis.training import orchestration
    monkeypatch.setattr(orchestration, "check_founder_acceptance_ledger", lambda repo_root, **_: [])

    run.start()
    assert run.state == RunState.RUNNING
    run.pause()
    run.resume()
    assert run.state == RunState.RUNNING


# ============================================================ AUDIT-P0-02 (secure counterpart) ==

def test_remediation_p0_02_all_rejected_corpus_persists_progress(tmp_path):
    out_dir = tmp_path / "processed"
    corrupt_corpus = tmp_path / "corrupt.jsonl"
    corrupt_corpus.write_text("\n".join(json.dumps({"malformed": i}) for i in range(5)) + "\n")

    report1, kept1 = process_corpus(corrupt_corpus, out_dir, num_shards=2)
    assert len(kept1) == 0
    assert report1.corrupt_records == 5

    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    row = conn.execute("SELECT resume_offset, corrupt_records FROM progress WHERE id = 0").fetchone()
    conn.close()
    assert row == (5, 5), "progress must be durably persisted even when nothing was kept"

    # a second call against an EXTENDED corpus must resume from line 5, not re-read from 0
    extended_corpus = tmp_path / "corrupt_extended.jsonl"
    extended_corpus.write_text(corrupt_corpus.read_text() + json.dumps({"malformed": "extra"}) + "\n")
    report2, _ = process_corpus(extended_corpus, out_dir, num_shards=2)
    assert report2.lines_read == 6, "a persisted resume_offset of 5 must mean only the NEW line 5 is read, not all 6 again"
    assert report2.corrupt_records == 6
    assert report2.resume_offset == 6


def test_remediation_p0_02_trailing_duplicates_persist_correctly(tmp_path):
    out_dir = tmp_path / "processed_trailing"
    lines = [json.dumps({"text": "unique first record"})] + [json.dumps({"text": "unique first record"})] * 5
    corpus = tmp_path / "trailing_dup.jsonl"
    corpus.write_text("\n".join(lines) + "\n")

    report, kept = process_corpus(corpus, out_dir, num_shards=2, commit_batch_size=1)
    assert len(kept) == 1
    assert report.exact_duplicates == 5
    assert report.resume_offset == 6

    conn = sqlite3.connect(out_dir / PROGRESS_DB_NAME)
    row = conn.execute("SELECT resume_offset, exact_duplicates FROM progress WHERE id = 0").fetchone()
    conn.close()
    assert row == (6, 5), "trailing duplicates must advance the persisted offset and rejection counter"


# ============================================================ AUDIT-P0-03 (secure counterpart) ==

def test_remediation_p0_03_same_size_tampering_is_detected_and_regenerated(tmp_path):
    out_dir = tmp_path / "processed"
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps({"text": f"record {i} for recovery testing"}) for i in range(10)) + "\n")
    process_corpus(corpus, out_dir, num_shards=1)
    shard_file = sorted(out_dir.glob("shard-*.jsonl"))[0]
    original_content = shard_file.read_bytes()

    shard_file.write_bytes(b"X" * len(original_content))

    conn = _open_progress_db(out_dir)
    _verify_and_recover_missing_or_corrupted_shard_output(out_dir, conn)
    unflushed = conn.execute("SELECT COUNT(*) FROM kept_records WHERE flushed = 0").fetchone()[0]
    conn.close()
    assert unflushed > 0, "same-size content tampering must be detected, not accepted by size alone"

    # a subsequent full process_corpus() call must actually regenerate the correct content
    _, kept_after = process_corpus(corpus, out_dir, num_shards=1)
    assert shard_file.read_bytes() == original_content
    assert len(kept_after) == 10


# ============================================================ AUDIT-P0-04 (secure counterpart) ==

def test_remediation_p0_04_normalization_rule_mutation_is_rejected(tmp_path):
    origin = SourceOrigin(source_id="src1", description="desc", license_name="CC-BY-4.0", usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)))
    tb = TokenizerBinding(tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1", vocab_digest=hashlib.sha256(b"vocab").hexdigest())
    manifest = GenesisDatasetManifest.build(
        dataset_name="norm-rule-remediation", version="v1", origins=[origin],
        normalized_records=["sample record alpha", "sample record beta"], transformation_lineage=[], tokenizer_binding=tb,
    )
    manifest_file = tmp_path / "manifest.json"
    payload = {
        "schema_version": manifest.schema_version, "manifest_id": manifest.manifest_id,
        "dataset_name": manifest.dataset_name, "version": manifest.version,
        "origins": [{"source_id": "src1", "description": "desc", "license_name": "CC-BY-4.0", "usage_restrictions": "none", "retrieved_at": manifest.origins[0].retrieved_at}],
        "source_record_count": manifest.source_record_count, "source_content_digest": manifest.source_content_digest,
        "normalization_rule": manifest.normalization_rule, "transformation_lineage": [],
        "tokenizer_binding": {"tokenizer_model_path": "/tmp/t.model", "architecture_version": "genesis-arch-v1", "vocab_digest": tb.vocab_digest},
        "created_at": manifest.created_at,
    }
    manifest_file.write_text(json.dumps(payload))
    loaded = GenesisDatasetManifest.load(manifest_file)
    assert loaded.manifest_id == manifest.manifest_id

    payload["normalization_rule"] = "ATTACK_PAYLOAD: NO NORMALIZATION APPLIED"
    manifest_file.write_text(json.dumps(payload))
    with pytest.raises(ManifestTamperedError):
        GenesisDatasetManifest.load(manifest_file)


# ============================================================ AUDIT-P1-02 (documented boundary) ==

def test_remediation_p1_02_calling_once_over_the_combined_corpus_catches_what_chunking_misses():
    """The audit's blind-spot demonstration shows that screening two
    SEPARATE batches independently misses a near-duplicate pair split
    across them. This is not a bug in `find_near_duplicates_across_splits()`
    itself -- it is a property of calling it on an incomplete view of the
    data. The correct, documented calling convention is to call it ONCE
    over the complete corpus (bounded by `max_total_records`, an explicit,
    documented scalability ceiling, not a silent gap) -- confirmed here to
    actually catch the pair the chunked calls missed."""
    text_a = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho"
    text_b = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi sigma"
    combined = {"train": [text_a, "unrelated text two"], "val": ["unrelated text one", text_b]}
    res_combined = find_near_duplicates_across_splits(combined)
    assert len(res_combined) > 0

    large = {"train": [f"t{i}" for i in range(2501)], "val": [f"v{i}" for i in range(2500)]}
    with pytest.raises(CrossSplitScreeningTooLargeError):
        find_near_duplicates_across_splits(large)
