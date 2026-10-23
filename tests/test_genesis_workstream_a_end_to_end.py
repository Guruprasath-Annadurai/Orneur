"""
GENESIS Native-Authorization-Convergence -- Workstream A end-to-end
workflow test (A-07 through A-11's mandatory integration requirement).

Lives on the cross-workstream integration branch (all four workstreams
merged) because it is the only place every module involved actually
coexists: Workstream A (PR #63 + this session's A-07..A-11 hardening),
Workstream C (PR #61 + Mission 2), and Workstream F (PR #64 + M2-01).

Demonstrates ONE complete, real, CPU-testable pipeline using actual
project modules and real filesystem artifacts -- no mocking of any
critical integrity check:

    raw synthetic corpus
    -> validated provenance (GenesisDatasetManifest.build(), real SourceOrigin)
    -> normalization + deduplication + bounded-memory incremental shards (process_corpus())
    -> restart recovery (an interrupted run resumed into the SAME output_dir)
    -> fail-closed contamination screening (run_contamination_checks(), all required checks)
    -> verified manifest (GenesisDatasetManifest built from the pipeline's own kept records,
       then independently re-loaded via the trusted load() boundary)
    -> bound tokenizer/shard/transformation identity (GenesisTrainingRun.validate()
       with REAL shard-file digests and a REAL dataset_manifest preflight object)
    -> native training preflight (a real, synthetic-fixture NativePretrainingGrant
       correctly authorizes the run -- AUTHORIZED is reached)
    -> and STOPS there: start() is denied by the real, empty founder-acceptance
       ledger, proving native training remains genuinely NO-GO end to end.

No training, GPU use, parameter update, or real signed grant occurs
anywhere in this file.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

import orca.config as orca_config  # noqa: E402
import orca.genesis.governance.authorization as GOV  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from orca.genesis.data.contamination import run_contamination_checks  # noqa: E402
from orca.genesis.data.manifest import (  # noqa: E402
    GenesisDatasetManifest,
    SourceOrigin,
    TokenizerBinding,
    TransformationStep,
)
from orca.genesis.data.pipeline import compute_shard_digests, process_corpus  # noqa: E402
from orca.genesis.training.orchestration import (  # noqa: E402
    ExecutionAcceptanceIncompleteError,
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


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _mint_matching_grant(monkeypatch, *, run_id, model_config_digest, tokenizer_digest, dataset_manifest_id,
                          dataset_content_digest, authorized_shard_digests, reviewed_commit_sha,
                          transformation_code_digest, optimizer_config_digest):
    """Synthetic-fixture authorization world, mirroring every other test
    file's own World/GrantWorld pattern -- a real Ed25519 key, a real
    signed record, the gate's pin patched to point at this throwaway
    registry. Never touches the real, committed, empty registry."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    now = datetime.now(timezone.utc)
    registry = {
        "schema_version": GOV.REGISTRY_SCHEMA_VERSION,
        "records": [{
            "id": "synthetic-authority-1", "role": "OWNER", "public_key_hex": pub,
            "activation_timestamp": _ts(now - timedelta(days=1)), "expiry": None, "revoked": False,
            "gpu_permission": False, "spend_permission": False,
        }],
    }
    req = GOV.NativePretrainingRequest(
        run_id=run_id, nonce=hashlib.sha256(f"e2e-nonce-{run_id}".encode()).hexdigest(), model_family="genesis",
        architecture_version="genesis-arch-v1", model_config_digest=model_config_digest, tokenizer_digest=tokenizer_digest,
        dataset_manifest_id=dataset_manifest_id, dataset_content_digest=dataset_content_digest,
        authorized_shard_digests=tuple(authorized_shard_digests), reviewed_commit_sha=reviewed_commit_sha,
        transformation_code_digest=transformation_code_digest, optimizer_config_digest=optimizer_config_digest,
        environment_class=ENV, gpu_requested=False, max_wall_clock_minutes=60, requested_spend_usd=0.0,
    )
    record = {
        "schema_version": GOV.SCHEMA_VERSION, "authorization_id": "gnpauth-" + "e2" * 8, "status": "AUTHORIZED",
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
        "authorizing_authority": {"identity": "synthetic-authority-1", "role": "OWNER", "key_id": "synthetic-authority-1"},
        "signature": None,
    }
    record["signature"] = priv.sign(GOV.canonical_signing_bytes(record)).hex()
    monkeypatch.setattr(GOV, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    monkeypatch.setattr(GOV, "PINNED_REGISTRY_SHA256", GOV.registry_digest(registry))
    return GOV.authorize_native_pretraining(
        repo_root=REPO_ROOT, record=record, registry=registry, revoked_ids=[], req=req,
        revocation_check=lambda auth_id: False,
    )


def test_full_workstream_a_pipeline_reaches_authorized_but_stays_no_go(tmp_path, monkeypatch):
    # ---- 1. raw synthetic corpus -----------------------------------------------------------
    raw_records = (
        [{"text": f"a genuinely distinct synthetic pretraining record number {i} about topic area {i}"} for i in range(60)]
        + [{"text": "a genuinely distinct synthetic pretraining record number 0 about topic area 0"}]  # exact duplicate
        + [{"not_text": "this record is malformed and must be rejected as corrupt"}]  # corrupt record
    )
    corpus_path = tmp_path / "raw_corpus.jsonl"
    corpus_path.write_text("\n".join(json.dumps(r) for r in raw_records) + "\n")

    # ---- 2. normalization + dedup + incremental, bounded-memory shards ---------------------
    out_dir = tmp_path / "processed"
    first_report, _ = process_corpus(corpus_path, out_dir, num_shards=2, commit_batch_size=16)
    assert first_report.corrupt_records == 1
    assert first_report.exact_duplicates == 1
    assert first_report.kept == 60

    # ---- 3. restart recovery: a SECOND call against the SAME output_dir with the SAME input
    #         must be a no-op (everything already committed), not a duplication or data loss.
    second_report, kept_records = process_corpus(corpus_path, out_dir, num_shards=2, commit_batch_size=16)
    assert second_report.kept == first_report.kept
    assert len(kept_records) == 60

    # ---- 4. fail-closed contamination screening --------------------------------------------
    splits: dict[str, list[str]] = {"train": [], "validation": [], "test": []}
    for shard_file in out_dir.glob("shard-*.jsonl"):
        split_name = shard_file.stem.split("-")[-1]
        for line in shard_file.read_text().splitlines():
            splits[split_name].append(json.loads(line)["text"])
    assert sum(len(v) for v in splits.values()) == 60

    contamination_report = run_contamination_checks(
        kept_records, protected_texts=["an entirely unrelated held-out benchmark question"],
        split_to_records=splits,
    )
    assert contamination_report.is_fully_verified_clean(
        required_checks=["exact_match", "normalized_substring_match", "cross_split_near_duplicate"]
    )

    # ---- 5. verified manifest ---------------------------------------------------------------
    origin = SourceOrigin(
        source_id="e2e-synthetic-fixture", description="end-to-end workflow test fixture",
        license_name="CC0-1.0", usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)),
    )
    tokenizer_binding = TokenizerBinding(
        tokenizer_model_path="/tmp/e2e-tokenizer.model", architecture_version="genesis-arch-v1",
        vocab_digest=hashlib.sha256(b"e2e-tokenizer-vocab-v1").hexdigest(),
    )
    manifest = GenesisDatasetManifest.build(
        dataset_name="e2e-workflow-fixture", version="v1", origins=[origin], normalized_records=kept_records,
        transformation_lineage=[TransformationStep(name="normalize_record_text", code_reference="orca.genesis.data.manifest.normalize_record_text")],
        tokenizer_binding=tokenizer_binding,
    )
    saved_path = manifest.save()
    reloaded = GenesisDatasetManifest.load(saved_path)  # trusted-load boundary (A-09) -- recomputes and verifies
    assert reloaded.manifest_id == manifest.manifest_id
    ok, msg = reloaded.verify_against_records(kept_records)
    assert ok, msg

    # ---- 6. bound tokenizer/shard/transformation identity (A-10) ---------------------------
    shard_digests = compute_shard_digests(out_dir)
    assert shard_digests
    model_config_digest = hashlib.sha256(b"e2e-model-config-v1").hexdigest()
    transformation_code_digest = hashlib.sha256(b"e2e-pipeline-transformation-code-v1").hexdigest()
    optimizer_config_digest = hashlib.sha256(b"e2e-optimizer-config-v1").hexdigest()
    reviewed_commit_sha = _head_sha()

    run = GenesisTrainingRun(
        "e2e-run-1", dataset_manifest_ids=(reloaded.manifest_id,), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    run.validate(
        dataset_manifest=reloaded, dataset_records=kept_records,  # M2-03: re-verified against real records, not a bare digest string
        model_config_digest=model_config_digest, tokenizer_digest=tokenizer_binding.vocab_digest,
        authorized_shard_digests=tuple(sorted(shard_digests.values())),  # REAL shard-file digests, not caller-chosen strings
        shard_dir=out_dir, reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=transformation_code_digest,
        optimizer_config_digest=optimizer_config_digest,
    )
    assert run.state is RunState.VALIDATED
    assert run.identity.dataset_digest == reloaded.source_content_digest

    # ---- 7. native training preflight: real synthetic grant, correctly bound ---------------
    run.request_authorization()
    grant = _mint_matching_grant(
        monkeypatch, run_id="e2e-run-1", model_config_digest=model_config_digest,
        tokenizer_digest=tokenizer_binding.vocab_digest, dataset_manifest_id=reloaded.manifest_id,
        dataset_content_digest=reloaded.source_content_digest, authorized_shard_digests=tuple(sorted(shard_digests.values())),
        reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=transformation_code_digest,
        optimizer_config_digest=optimizer_config_digest,
    )
    run.authorize(grant)
    assert run.state is RunState.AUTHORIZED

    # ---- 8. and STOPS there -- native training remains genuinely NO-GO ---------------------
    with pytest.raises(ExecutionAcceptanceIncompleteError):
        run.start()
    assert run.state is RunState.REJECTED


def test_tampering_a_shard_after_manifest_binding_invalidates_the_training_identity(tmp_path, monkeypatch):
    """A-10's explicit demonstration requirement: changing a shard
    invalidates the applicable pretraining authorization identity.
    Binds a run's identity to the REAL shard digests, then tampers one
    shard file's bytes on disk and shows that the SAME, previously-valid
    grant no longer authorizes the (now-different) declared identity."""
    corpus_path = tmp_path / "raw_corpus.jsonl"
    corpus_path.write_text("\n".join(json.dumps({"text": f"tamper-test record {i} about its own topic {i}"}) for i in range(20)) + "\n")
    out_dir = tmp_path / "processed"
    _, kept_records = process_corpus(corpus_path, out_dir, num_shards=2)
    shard_digests_before = compute_shard_digests(out_dir)

    origin = SourceOrigin(source_id="s", description="d", license_name="CC0-1.0", usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)))
    tb = TokenizerBinding(tokenizer_model_path="/tmp/t.model", architecture_version="genesis-arch-v1", vocab_digest=hashlib.sha256(b"v").hexdigest())
    manifest = GenesisDatasetManifest.build(
        dataset_name="tamper-fixture", version="v1", origins=[origin], normalized_records=kept_records,
        transformation_lineage=[], tokenizer_binding=tb,
    )

    reviewed_commit_sha = _head_sha()
    grant = _mint_matching_grant(
        monkeypatch, run_id="tamper-run", model_config_digest=hashlib.sha256(b"mcfg").hexdigest(),
        tokenizer_digest=tb.vocab_digest, dataset_manifest_id=manifest.manifest_id,
        dataset_content_digest=manifest.source_content_digest, authorized_shard_digests=tuple(sorted(shard_digests_before.values())),
        reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=hashlib.sha256(b"tcd").hexdigest(),
        optimizer_config_digest=hashlib.sha256(b"ocd").hexdigest(),
    )

    # Tamper ONE shard file's bytes after the grant was already minted against the ORIGINAL digests.
    target = sorted(out_dir.glob("shard-*.jsonl"))[0]
    data = bytearray(target.read_bytes())
    data[0] ^= 0xFF
    target.write_bytes(bytes(data))
    shard_digests_after = compute_shard_digests(out_dir)
    assert shard_digests_after != shard_digests_before

    run = GenesisTrainingRun(
        "tamper-run", dataset_manifest_ids=(manifest.manifest_id,), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    run.validate(
        dataset_manifest=manifest, dataset_records=kept_records,
        model_config_digest=hashlib.sha256(b"mcfg").hexdigest(),
        tokenizer_digest=tb.vocab_digest, authorized_shard_digests=tuple(sorted(shard_digests_after.values())),  # the NEW, tampered digests
        shard_dir=out_dir, reviewed_commit_sha=reviewed_commit_sha, transformation_code_digest=hashlib.sha256(b"tcd").hexdigest(),
        optimizer_config_digest=hashlib.sha256(b"ocd").hexdigest(),
    )
    run.request_authorization()
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="WRONG_AUTHORIZED_SHARDS"):
        run.authorize(grant)  # the grant still names the ORIGINAL (pre-tamper) shard digests
    assert run.state is RunState.REJECTED
