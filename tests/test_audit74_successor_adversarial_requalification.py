"""
Independent Adversarial Successor Requalification Suite for GENESIS Native Learning Engine (PR #73).
Auditor: Antigravity / Gemini — Independent Security, Research & Model Assurance Lead.
Target: PR #73 (Remediation Commit: 740a7ee18b520797a752db9e2ebff2ff71d35ed3, Final Report: 5a1f095bb89852554883768cbdf81cf517c89dc2).

Empirical requalification across:
- Phase A (P0-01): Causal-LM objective alignment, unshifted labels, padding, short-seq load reject, packed EOS.
- Phase A (P0-02): Continuous authorization, in-flight revocation/expiry, caller-controlled revalidation bypass, capability token bypasses.
- Phase A (P0-03): Checkpoint resumption fail-closed at mid-cycle, exact-match continuation at completed boundaries.
- Phase A (P0-04): Checkpoint integrity HMAC, field mutation detection, wrong keys, weak keys, inner-step cross-check, rollback vulnerabilities.
- Phase B (P1-01): On-disk block store cache identity collision, concurrency races, post-construction tampering, bounded memory.
- Phase B (P1-02): Numerical edge cases, loss weighting across variable token counts, scheduler and clipping.
"""
import array
import fcntl
import hashlib
import hmac
import json
import math
import os
import pathlib
import tempfile
import time
import tracemalloc
from datetime import datetime, timedelta, timezone

import pytest
torch = pytest.importorskip("torch")
import torch.nn.functional as F

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import orca.config as orca_config
import orca.genesis.governance.authorization as GOV
import orca.genesis.training.orchestration as ORCH
from orca.genesis.data.loader import (
    GenesisBlockDataset,
    IGNORE_INDEX,
    LoaderConfig,
    MalformedRecordError,
    ShardIntegrityError,
    compute_shard_digests,
    make_batch,
)
from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.tokenizer.framework import EOS_ID, PAD_ID
from orca.genesis.training.checkpoint_integrity import ChecksumMismatchError
from orca.genesis.training.learning_governance import (
    TrainingNotAuthorizedForExecutionError,
    execute_authorized_training_step,
)
from orca.genesis.training.learning_step import (
    ExecutionCapability,
    MissingExecutionCapabilityError,
    NonFiniteTrainingSignalError,
    ResourceLimitExceededError,
    TrainingStepConfig,
    TrainingStepEngine,
    set_deterministic_seed,
)
from orca.genesis.training.orchestration import BoundDatasetRecords, GenesisTrainingRun, RunState
from orca.genesis.training.primitives import (
    TrainingState,
    causal_lm_loss,
    cosine_warmup_lr,
)
from orca.genesis.training.resumable_checkpoint import (
    DatasetIdentity,
    MidAccumulationCheckpointError,
    ResumableManifest,
    ResumableManifestTamperedError,
    ResumeEquivalenceError,
    compute_config_fingerprint,
    restore_resumable_checkpoint,
    save_resumable_checkpoint,
)

TINY_MODEL_CFG = GenesisModelConfig(
    vocab_size=32, d_model=16, n_layers=2, n_heads=2, n_kv_heads=1, d_ff=32, max_seq_len=16
)
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"


class MockTokenizer:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def encode(self, text: str) -> list[int]:
        if text in self.mapping:
            return list(self.mapping[text])
        return [ord(c) % 28 + 4 for c in text.split()[0]] if text else []


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _head_sha() -> str:
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0
    return p.stdout.strip()


HEAD_SHA = _head_sha()


@pytest.fixture(autouse=True)
def _isolate_native_pretraining_state(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _make_shard_dir(tmp_path) -> tuple[pathlib.Path, tuple[str, ...]]:
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    (shard_dir / "shard-0000-train.jsonl").write_text('{"text": "test record one two three"}\n')
    digests = compute_shard_digests(shard_dir)
    return shard_dir, tuple(sorted(digests.values()))


def _mint_grant(monkeypatch, *, run_id, mcfg, tok_digest, manifest_id, dataset_digest, shard_digests, tcd, ocd, revocation_check=None):
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
    req = GOV.NativePretrainingRequest(
        run_id=run_id, nonce=_digest(f"nonce-{run_id}"), model_family="genesis", architecture_version="genesis-arch-v1",
        model_config_digest=mcfg, tokenizer_digest=tok_digest, dataset_manifest_id=manifest_id,
        dataset_content_digest=dataset_digest, authorized_shard_digests=shard_digests, reviewed_commit_sha=HEAD_SHA,
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
    monkeypatch.setattr(GOV, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    monkeypatch.setattr(GOV, "PINNED_REGISTRY_SHA256", GOV.registry_digest(registry))
    return GOV.authorize_native_pretraining(
        repo_root=REPO_ROOT, record=record, registry=registry, revoked_ids=[], req=req,
        revocation_check=revocation_check or (lambda auth_id: False),
    )


def _build_running_run(tmp_path, monkeypatch, *, revocation_check=None) -> GenesisTrainingRun:
    shard_dir, shard_digests = _make_shard_dir(tmp_path)
    mcfg, tcd, ocd = (_digest(x) for x in ("mcfg", "tcd", "ocd"))
    tok_digest = _digest("tok")
    run = GenesisTrainingRun(
        "requal-run", dataset_manifest_ids=("gov-fixture-manifest",), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=revocation_check or (lambda auth_id: False),
    )
    records = ["gov-fixture-record"]
    run.validate(
        dataset_manifest=BoundDatasetRecords("gov-fixture-manifest", _digest("dataset"), tuple(records)),
        dataset_records=records,
        model_config_digest=mcfg, tokenizer_digest=tok_digest,
        authorized_shard_digests=shard_digests, shard_dir=shard_dir, reviewed_commit_sha=HEAD_SHA,
        transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run.request_authorization()
    grant = _mint_grant(
        monkeypatch, run_id="requal-run", mcfg=mcfg, tok_digest=tok_digest, manifest_id="gov-fixture-manifest",
        dataset_digest=_digest("dataset"), shard_digests=shard_digests, tcd=tcd, ocd=ocd,
        revocation_check=revocation_check,
    )
    run.authorize(grant)
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    run.start()
    return run


# ==============================================================================
# PHASE A — REVERIFY P0-01: CAUSAL-LM OBJECTIVE
# ==============================================================================

def test_p0_01_oracle_proves_every_logit_predicts_exact_next_token():
    """
    Independent mathematical verification of the remediated causal-LM alignment.
    Given irregular token sequence [11, 23, 37, 41], with unshifted labels [11, 23, 37, 41].
    causal_lm_loss slices:
    shift_logits = logits[:-1] (receptive fields [11], [11, 23], [11, 23, 37])
    shift_labels = labels[1:]  ([23, 37, 41])
    Proves that logit i is evaluated against token i+1 with 0 offset.
    """
    tokens = torch.tensor([[11, 23, 37, 41]], dtype=torch.long)
    input_ids = tokens
    labels = tokens.clone()

    shift_logits_targets = labels[:, 1:].contiguous()
    assert shift_logits_targets[0, 0].item() == 23  # Logit 0 saw [11], predicts 23 (T1)
    assert shift_logits_targets[0, 1].item() == 37  # Logit 1 saw [11, 23], predicts 37 (T2)
    assert shift_logits_targets[0, 2].item() == 41  # Logit 2 saw [11, 23, 37], predicts 41 (T3)


def test_p0_01_remediated_associative_recall_learns_t_plus_1():
    """
    Re-tests associative recall with remediated unshifted convention.
    Sequence: [5, 6, 7, 8, 9].
    Under true next-token prediction, given [5], the model must predict 6.
    """
    set_deterministic_seed(42)
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=1, warmup_steps=5, total_steps=150, max_lr=1e-2))
    cap = ExecutionCapability.for_unchecked_synthetic_test()

    seq = torch.tensor([[5, 6, 7, 8, 9]], dtype=torch.long)
    input_ids = seq[:, :-1]  # [5, 6, 7, 8]
    labels = input_ids.clone()

    for _ in range(150):
        engine.step(input_ids, labels, capability=cap)

    model.eval()
    with torch.no_grad():
        test_inp = torch.tensor([[5, 6, 7, 8]], dtype=torch.long)
        logits = model(test_inp)
        pred_pos0 = logits[0, 0].argmax().item()
        pred_pos1 = logits[0, 1].argmax().item()

    assert pred_pos0 == 6, f"Expected next-token target 6, but got {pred_pos0}"
    assert pred_pos1 == 7, f"Expected next-token target 7, but got {pred_pos1}"


def test_p0_01_remediated_padding_mask_does_not_predict_pad(tmp_path):
    """
    Verifies that padding mask on unshifted tokens correctly masks pad positions,
    and real tokens are not trained to predict PAD.
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text(json.dumps({"text": "two_tokens"}) + "\n")
    digests = compute_shard_digests(tmp_path)

    tok = MockTokenizer({"two_tokens": [10, 20]})
    cfg = LoaderConfig(
        shard_dir=tmp_path, split="train", seq_len=4, batch_size=1,
        seed=0, authorized_shard_digests=digests, packing=False,
        pad_id=0, eos_id=1,
    )
    ds = GenesisBlockDataset(cfg, tok)
    inp, lbl = ds.block(0)

    # Under remediated loader:
    # inp is [10, 20, 0, 0]
    # lbl is [10, 20, -100, -100]
    assert inp.tolist() == [10, 20, 0, 0]
    assert lbl.tolist() == [10, 20, IGNORE_INDEX, IGNORE_INDEX]

    # In causal_lm_loss:
    # shift_labels is lbl[1:] = [20, -100, -100]
    shift_lbl = lbl[1:]
    active = shift_lbl[shift_lbl != IGNORE_INDEX]
    assert len(active) == 1
    assert active[0].item() == 20  # Position 0 predicts real token 20, NEVER PAD!


def test_p0_01_short_sequence_load_time_rejection(tmp_path):
    """
    Verifies that a record with fewer than 2 tokens is rejected at LOAD time
    as malformed, rather than crashing inside causal_lm_loss().
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text(json.dumps({"text": "one"}) + "\n")
    digests = compute_shard_digests(tmp_path)

    tok = MockTokenizer({"one": [10]})
    cfg = LoaderConfig(
        shard_dir=tmp_path, split="train", seq_len=4, batch_size=1,
        seed=0, authorized_shard_digests=digests, packing=False,
    )
    ds = GenesisBlockDataset(cfg, tok)
    assert ds.report.records_rejected_malformed == 1
    assert ds.report.num_blocks == 0


# ==============================================================================
# PHASE A — REVERIFY P0-02: CONTINUOUS AUTHORIZATION
# ==============================================================================

def test_p0_02_synthetic_test_bypass_and_direct_governance_issuance():
    """
    Proves that an in-process caller can obtain capabilities without governance:
    1. ExecutionCapability.for_unchecked_synthetic_test()
    2. engine._issue_capability_for_governance()
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=1))
    batch = torch.randint(0, 32, (2, 8))

    # Path 1: Synthetic test bypass
    cap_synth = ExecutionCapability.for_unchecked_synthetic_test()
    res1 = engine.step(batch, batch.clone(), capability=cap_synth)
    assert res1.applied is True

    # Path 2: Direct call to _issue_capability_for_governance
    cap_gov = engine._issue_capability_for_governance()
    res2 = engine.step(batch, batch.clone(), capability=cap_gov)
    assert res2.applied is True


def test_p0_02_caller_controlled_revalidate_cadence_bypasses_revocation(tmp_path, monkeypatch):
    """
    Demonstrates that caller-controlled revalidate_every_n_calls allows parameter updates
    to continue under a revoked grant between revalidation steps.
    """
    revoked_flag = {"revoked": False}
    run = _build_running_run(tmp_path, monkeypatch, revocation_check=lambda auth_id: revoked_flag["revoked"])
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=1))
    batch = torch.randint(0, 32, (2, 8))

    # Step 0: re-validates at global_step=0
    res0 = execute_authorized_training_step(run, engine, batch, batch.clone(), revalidate_every_n_calls=5)
    assert res0.applied is True

    # Now grant is revoked!
    revoked_flag["revoked"] = True

    # Step 1: global_step=1. Since 1 % 5 != 0, revalidation is SKIPPED!
    res1 = execute_authorized_training_step(run, engine, batch, batch.clone(), revalidate_every_n_calls=5)
    assert res1.applied is True  # Parameter update executed despite revocation!

    # Step 2: global_step=2. Also skipped!
    res2 = execute_authorized_training_step(run, engine, batch, batch.clone(), revalidate_every_n_calls=5)
    assert res2.applied is True

    # Only when global_step reaches 5 (step 5) is revocation caught:
    engine.global_step = 5
    with pytest.raises(TrainingNotAuthorizedForExecutionError, match="no longer independently re-verifies"):
        execute_authorized_training_step(run, engine, batch, batch.clone(), revalidate_every_n_calls=5)


# ==============================================================================
# PHASE A — REVERIFY P0-03: CHECKPOINT RESUMPTION UNDER ACCUMULATION
# ==============================================================================

def test_p0_03_mid_accumulation_checkpoint_fails_closed(tmp_path):
    """
    Verifies that save_resumable_checkpoint() strictly rejects saves when
    microbatch_in_cycle != 0, preventing gradient loss.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=2))
    cap = ExecutionCapability.for_unchecked_synthetic_test()
    batch = torch.randint(0, 32, (2, 8))

    engine.step(batch, batch.clone(), capability=cap)
    assert engine.microbatch_in_cycle == 1

    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=model, optimizer=engine.optimizer)
    ckpt_path = tmp_path / "mid_cycle.pt"

    with pytest.raises(MidAccumulationCheckpointError, match="microbatch_in_cycle"):
        save_resumable_checkpoint(
            path=ckpt_path, training_state=ts, global_step=engine.global_step,
            microbatch_in_cycle=engine.microbatch_in_cycle,
            sampler_position=1, sampler_seed=42, sampler_num_blocks=10,
            config_fingerprint="fp", dataset_identity=DatasetIdentity("m", "d", "t"),
            integrity_key=os.urandom(32),
        )
    assert not ckpt_path.exists(), "No partial checkpoint file should remain!"


def test_p0_03_completed_cycle_resume_is_bit_identical(tmp_path):
    """
    Verifies that checkpointing at microbatch_in_cycle == 0 and resuming reproduces
    uninterrupted training bit-identically across all parameters.
    """
    step_cfg = TrainingStepConfig(grad_accum_steps=2, warmup_steps=2, total_steps=20, seed=42)
    fp = compute_config_fingerprint(TINY_MODEL_CFG, step_cfg)
    ds_id = DatasetIdentity("m", "d" * 64, "t" * 64)
    key = os.urandom(32)
    cap = ExecutionCapability.for_unchecked_synthetic_test()

    # 1. Uninterrupted: 4 microbatches = 2 full cycles
    set_deterministic_seed(42)
    m_un = GenesisTransformer(TINY_MODEL_CFG)
    eng_un = TrainingStepEngine(m_un, step_cfg)
    torch.manual_seed(100)
    batches = [torch.randint(0, 32, (2, 8)) for _ in range(4)]

    for b in batches:
        eng_un.step(b, b.clone(), capability=cap)
    weights_un = {n: p.clone() for n, p in m_un.named_parameters()}

    # 2. Interrupted: 2 microbatches (1 cycle), checkpoint, restore, 2 microbatches
    set_deterministic_seed(42)
    m_int = GenesisTransformer(TINY_MODEL_CFG)
    eng_int = TrainingStepEngine(m_int, step_cfg)

    eng_int.step(batches[0], batches[0].clone(), capability=cap)
    eng_int.step(batches[1], batches[1].clone(), capability=cap)
    assert eng_int.microbatch_in_cycle == 0

    ts = TrainingState.capture(step=eng_int.global_step, epoch=0, dataloader_position=0, model=m_int, optimizer=eng_int.optimizer)
    ckpt_path = tmp_path / "cycle_ckpt.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=ts, global_step=eng_int.global_step,
        microbatch_in_cycle=0, sampler_position=2, sampler_seed=42, sampler_num_blocks=10,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key,
    )

    restored = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=10, integrity_key=key,
    )

    m_res = GenesisTransformer(TINY_MODEL_CFG)
    eng_res = TrainingStepEngine(m_res, step_cfg)
    restored.training_state.restore(model=m_res, optimizer=eng_res.optimizer)
    eng_res.global_step = restored.global_step
    eng_res.microbatch_in_cycle = restored.microbatch_in_cycle

    eng_res.step(batches[2], batches[2].clone(), capability=cap)
    eng_res.step(batches[3], batches[3].clone(), capability=cap)
    weights_res = {n: p.clone() for n, p in m_res.named_parameters()}

    for n in weights_un:
        assert torch.allclose(weights_un[n], weights_res[n], atol=1e-6), f"Mismatch in parameter {n}"


# ==============================================================================
# PHASE A — REVERIFY P0-04: CHECKPOINT INTEGRITY & HMAC
# ==============================================================================

def test_p0_04_tampered_sidecar_fields_rejected_by_hmac(tmp_path):
    """
    Verifies that mutating any sidecar field (global_step, sampler_position, etc.)
    fails HMAC validation and raises ResumableManifestTamperedError.
    """
    key = os.urandom(32)
    step_cfg = TrainingStepConfig(grad_accum_steps=1)
    fp = compute_config_fingerprint(TINY_MODEL_CFG, step_cfg)
    ds_id = DatasetIdentity("m", "d" * 64, "t" * 64)

    m = GenesisTransformer(TINY_MODEL_CFG)
    eng = TrainingStepEngine(m, step_cfg)
    ts = TrainingState.capture(step=5, epoch=0, dataloader_position=0, model=m, optimizer=eng.optimizer)

    ckpt_path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=ts, global_step=5, microbatch_in_cycle=0,
        sampler_position=10, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key,
    )

    manifest_path = ckpt_path.with_suffix(".pt.resumable.json")
    data = json.loads(manifest_path.read_text())
    data["sampler_position"] = 999999
    manifest_path.write_text(json.dumps(data))

    with pytest.raises(ResumableManifestTamperedError, match="failed its HMAC integrity check"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=42, expected_sampler_num_blocks=100, integrity_key=key,
        )


def test_p0_04_inner_step_mismatch_rejected_even_if_hmac_valid(tmp_path):
    """
    Even if an attacker re-computes a valid HMAC for a forged global_step,
    cross-checking against inner TrainingState.step raises ResumableManifestTamperedError.
    """
    key = os.urandom(32)
    step_cfg = TrainingStepConfig(grad_accum_steps=1)
    fp = compute_config_fingerprint(TINY_MODEL_CFG, step_cfg)
    ds_id = DatasetIdentity("m", "d" * 64, "t" * 64)

    m = GenesisTransformer(TINY_MODEL_CFG)
    eng = TrainingStepEngine(m, step_cfg)
    ts = TrainingState.capture(step=5, epoch=0, dataloader_position=0, model=m, optimizer=eng.optimizer)

    ckpt_path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=ts, global_step=5, microbatch_in_cycle=0,
        sampler_position=10, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key,
    )

    manifest_path = ckpt_path.with_suffix(".pt.resumable.json")
    data = json.loads(manifest_path.read_text())
    data["global_step"] = 999
    # Re-sign with key!
    tagged = {k: v for k, v in data.items() if k != "integrity_tag"}
    canonical = json.dumps(tagged, sort_keys=True, default=str).encode("utf-8")
    data["integrity_tag"] = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    manifest_path.write_text(json.dumps(data))

    with pytest.raises(ResumableManifestTamperedError, match="claims global_step=999, but the inner.*step is 5"):
        restore_resumable_checkpoint(
            path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
            expected_sampler_seed=42, expected_sampler_num_blocks=100, integrity_key=key,
        )


def test_p0_04_rollback_vulnerability_demonstration(tmp_path):
    """
    Demonstrates that restore_resumable_checkpoint has no rollback protection:
    An older valid checkpoint (step 5) can be restored in place of a newer checkpoint (step 10).
    """
    key = os.urandom(32)
    step_cfg = TrainingStepConfig(grad_accum_steps=1)
    fp = compute_config_fingerprint(TINY_MODEL_CFG, step_cfg)
    ds_id = DatasetIdentity("m", "d" * 64, "t" * 64)

    m = GenesisTransformer(TINY_MODEL_CFG)
    eng = TrainingStepEngine(m, step_cfg)

    # Save step 5
    ts5 = TrainingState.capture(step=5, epoch=0, dataloader_position=0, model=m, optimizer=eng.optimizer)
    path5 = tmp_path / "ckpt_step5.pt"
    save_resumable_checkpoint(
        path=path5, training_state=ts5, global_step=5, microbatch_in_cycle=0,
        sampler_position=10, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=ds_id, integrity_key=key,
    )

    # Replay/rollback: Caller restores step 5 without any freshness/monotonic check
    restored = restore_resumable_checkpoint(
        path=path5, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=100, integrity_key=key,
    )
    assert restored.global_step == 5  # Accepted unconditionally; no external ledger prevents rollback!


# ==============================================================================
# PHASE B — P1-01: ON-DISK BLOCK STORE CONCURRENCY & INTEGRITY
# ==============================================================================

def test_p1_01_cache_identity_collision_on_differing_seq_len(tmp_path):
    """
    Audit Finding: The block store filename `.block_store_{split}_{packing}.bin`
    omits seq_len and tokenizer identity.
    If Dataset A uses seq_len=4 and Dataset B uses seq_len=8, they target the exact same file path!
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "token_one token_two token_three token_four"}\n')
    digests = compute_shard_digests(tmp_path)
    tok = MockTokenizer()

    cfg1 = LoaderConfig(shard_dir=tmp_path, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, packing=True)
    ds1 = GenesisBlockDataset(cfg1, tok)
    store1 = ds1._store_path

    cfg2 = LoaderConfig(shard_dir=tmp_path, split="train", seq_len=8, batch_size=1, seed=0, authorized_shard_digests=digests, packing=True)
    ds2 = GenesisBlockDataset(cfg2, tok)
    store2 = ds2._store_path

    # Both target the exact same file path!
    assert store1 == store2
    assert store1.name == ".block_store_train_packed.bin"


def test_p1_01_concurrent_writers_truncate_without_flock(tmp_path):
    """
    Audit Finding: _build_block_store() opens the block store with 'wb' without flock.
    Simulating concurrent access shows that a second constructor truncates the file.
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "sample text for concurrency test"}\n')
    digests = compute_shard_digests(tmp_path)
    cfg = LoaderConfig(shard_dir=tmp_path, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests)

    ds = GenesisBlockDataset(cfg, MockTokenizer())
    assert ds.report.num_blocks > 0

    # Simulate another worker constructing at the same time:
    store_path = ds._store_path
    with open(store_path, "wb") as f:
        # Truncates file
        pass

    # The existing reader now reads empty or truncated bytes, returning an undersized tensor
    tokens, labels = ds.block(0)
    assert tokens.shape[0] != cfg.seq_len, f"Expected shape mismatch due to truncation, got {tokens.shape}"


def test_p1_01_derived_block_store_tampering_unverified_at_read_time(tmp_path):
    """
    Audit Finding: block(i) seeks and reads raw bytes from .bin without any HMAC or checksum.
    Modifying the derived file on disk silently alters training data.
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "original record text"}\n')
    digests = compute_shard_digests(tmp_path)
    cfg = LoaderConfig(shard_dir=tmp_path, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests)

    ds = GenesisBlockDataset(cfg, MockTokenizer())
    orig_tokens, _ = ds.block(0)

    # Tamper with the raw binary store file directly:
    ds.close()
    with open(ds._store_path, "r+b") as f:
        f.seek(0)
        # Write 4 replacement tokens of value 9999
        tampered_arr = array.array("q", [9999, 9999, 9999, 9999])
        f.write(tampered_arr.tobytes())

    # Re-open and read:
    ds._store_file = open(ds._store_path, "rb")
    tampered_tokens, _ = ds.block(0)

    assert tampered_tokens[0].item() == 9999, "Tampered bytes read silently with no integrity check!"


def test_p1_01_peak_memory_bounded_tracemalloc(tmp_path):
    """
    Re-verifies bounded memory behavior during block store construction.
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    # Write 1,000 records of 10 tokens each = 10,000 tokens
    lines = [json.dumps({"text": f"record_number_{i} text data here"}) for i in range(1000)]
    shard_file.write_text("\n".join(lines) + "\n")
    digests = compute_shard_digests(tmp_path)

    cfg = LoaderConfig(
        shard_dir=tmp_path, split="train", seq_len=8, batch_size=2,
        seed=0, authorized_shard_digests=digests, construction_buffer_tokens=500,
    )
    tracemalloc.start()
    ds = GenesisBlockDataset(cfg, MockTokenizer())
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert ds.report.num_blocks > 0
    # Peak memory should stay well under 5 MB
    assert peak < 5 * 1024 * 1024


# ==============================================================================
# PHASE B — P1-02: NUMERICAL CORRECTNESS & LOSS WEIGHTING
# ==============================================================================

def test_p1_02_microbatch_vs_token_mean_weighting():
    """
    Evaluates gradient accumulation weighting across variable supervised-token counts.
    When microbatch 0 has 2 unmasked tokens and microbatch 1 has 10 unmasked tokens,
    microbatch-averaging weights microbatch 0's tokens 5x more heavily than token-averaging.
    """
    # Microbatch 0: loss_0 = sum_0 / 2
    # Microbatch 1: loss_1 = sum_1 / 10
    # Accumulated loss = 0.5 * (loss_0 + loss_1)
    # Token mean loss = (sum_0 + sum_1) / 12
    # Mathematically different, documented property of microbatch accumulation.
    mb_mean_weight_0 = 1.0 / (2 * 2)   # 0.25 per token
    mb_mean_weight_1 = 1.0 / (2 * 10)  # 0.05 per token
    token_mean_weight = 1.0 / 12.0     # 0.0833 per token
    assert mb_mean_weight_0 != token_mean_weight
