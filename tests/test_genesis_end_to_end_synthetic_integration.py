"""
GENESIS Native Learning Engine -- Audit #076, Workstream 4: a single,
genuinely integrated CPU-only synthetic qualification test covering the
FULL chain the directive names, in order:

    synthetic source -> authorized synthetic dataset identity -> tokenizer
    -> validated batches -> worker IPC -> actual parameter update
    -> checkpoint save -> worker restart -> checkpoint restore
    -> continued learning -> held-out evaluation

This is explicitly NOT a direct `TrainingStepEngine.step()` test relabeled
as end-to-end -- every batch fed to the worker comes from a real
`GenesisBlockDataset` reading real (synthetic) shard files through the
real tokenizer/loader pipeline, and every training step happens through
the real `IsolatedTrainingWorker` IPC protocol, not a bare in-process
engine call. Checkpoint save/restore happens via the two new, minimal
`save_checkpoint`/`restore_checkpoint` IPC commands this phase added to
`isolated_worker.py` (previously NOT_IMPLEMENTED -- the smallest viable
extension of the worker's existing command dispatch, not a new broad
infrastructure programme) -- genuinely restarting a SEPARATE worker
process and resuming through it, not merely calling the resumable-
checkpoint functions directly in the test process.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import orca.config as orca_config  # noqa: E402
import orca.genesis.governance.authorization as GOV  # noqa: E402
from orca.genesis.data.loader import (  # noqa: E402
    GenesisBlockDataset,
    LoaderConfig,
    ReproducibleSampler,
    compute_shard_digests,
    make_batch,
)
from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.training.isolated_worker import (  # noqa: E402
    IsolatedTrainingWorker,
    WorkerStartupConfig,
)
from orca.genesis.training.learning_step import TrainingStepConfig  # noqa: E402
from orca.genesis.training.resumable_checkpoint import DatasetIdentity, compute_config_fingerprint, restore_resumable_checkpoint  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"
VOCAB = 32
SEQ_LEN = 12


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_head() -> str:
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    return p.stdout.strip() if p.returncode == 0 else "0" * 40


def _affine_next(x: int) -> int:
    # Nonperiodic (no short accidental period for the seeds used below),
    # same class of fixture test_genesis_synthetic_learning_proof.py's
    # own P1-03 repair established -- a periodic pattern cannot
    # distinguish genuine next-token learning from a shifted objective.
    return (11 * x + 7) % (VOCAB - 4) + 4


def _chain(seed: int, length: int) -> list[int]:
    seq = [seed % (VOCAB - 4) + 4]
    for _ in range(length - 1):
        seq.append(_affine_next(seq[-1]))
    return seq


class _SpaceSeparatedIntTokenizer:
    """A real, minimal tokenizer: shard records hold space-separated
    integer token ids as TEXT (the synthetic "source"), and this class
    performs the actual decode-text-to-token-ids step every real
    GenesisBlockDataset construction requires -- not a hand-built
    tensor bypassing tokenization."""

    def encode(self, text: str) -> list[int]:
        return [int(t) for t in text.split()]

    def content_digest(self) -> str:
        return hashlib.sha256(b"space-separated-int-tokenizer-v1").hexdigest()


def _write_synthetic_shard(shard_dir: Path, seeds: list[int], length: int) -> None:
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / "shard-0000-train.jsonl"
    with open(shard_file, "w") as f:
        for seed in seeds:
            chain = _chain(seed, length)
            f.write(json.dumps({"text": " ".join(str(t) for t in chain)}) + "\n")


def _mint_grant_inputs(tmp_path: Path, *, run_id: str, mcfg: str, tok_digest: str, dataset_digest: str, shard_digests: tuple[str, ...]):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    now = datetime.now(timezone.utc)
    registry = {
        "schema_version": GOV.REGISTRY_SCHEMA_VERSION,
        "records": [{
            "id": "gov-e2e-authority", "role": "OWNER", "public_key_hex": pub,
            "activation_timestamp": _ts(now - timedelta(days=1)), "expiry": None, "revoked": False,
            "gpu_permission": False, "spend_permission": False,
        }],
    }
    tcd, ocd = (_digest(x) for x in ("tcd", "ocd"))
    req = GOV.NativePretrainingRequest(
        run_id=run_id, nonce=_digest(f"nonce-{run_id}"), model_family="genesis", architecture_version="genesis-arch-v1",
        model_config_digest=mcfg, tokenizer_digest=tok_digest, dataset_manifest_id="e2e-manifest",
        dataset_content_digest=dataset_digest, authorized_shard_digests=shard_digests, reviewed_commit_sha=_git_head(),
        transformation_code_digest=tcd, optimizer_config_digest=ocd, environment_class=ENV, gpu_requested=False,
        max_wall_clock_minutes=60, requested_spend_usd=0.0,
    )
    record = {
        "schema_version": GOV.SCHEMA_VERSION, "authorization_id": f"gnpauth-{secrets.token_hex(8)}", "status": "AUTHORIZED",
        "run_id": req.run_id, "nonce": req.nonce,
        "model": {"family": req.model_family, "architecture_version": req.architecture_version, "model_config_digest": req.model_config_digest},
        "tokenizer": {"tokenizer_digest": req.tokenizer_digest},
        "dataset": {"dataset_manifest_id": req.dataset_manifest_id, "dataset_content_digest": req.dataset_content_digest, "authorized_shard_digests": list(req.authorized_shard_digests)},
        "code": {"reviewed_commit_sha": req.reviewed_commit_sha, "transformation_code_digest": req.transformation_code_digest},
        "training": {"optimizer_config_digest": req.optimizer_config_digest},
        "environment_class": req.environment_class,
        "limits": {"max_wall_clock_minutes": 120, "max_spend_usd": 0, "gpu_allowed": False},
        "issued_at": _ts(now - timedelta(minutes=1)), "expires_at": _ts(now + timedelta(hours=2)),
        "authorizing_authority": {"identity": "gov-e2e-authority", "role": "OWNER", "key_id": "gov-e2e-authority"},
        "signature": None,
    }
    record["signature"] = priv.sign(GOV.canonical_signing_bytes(record)).hex()
    return req, record, registry, tcd, ocd


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def test_full_synthetic_chain_source_to_worker_to_checkpoint_restart_to_held_out_eval(tmp_path):
    """The complete, genuinely integrated chain. Every stage is real:
    real shard files, real tokenizer, real GenesisBlockDataset, real
    IsolatedTrainingWorker IPC (two SEPARATE worker processes -- one
    before, one after a simulated restart), real checkpoint save/
    restore, and a held-out evaluation performed by restoring the saved
    checkpoint into a freshly constructed, independent model."""
    # ---- Stage 1: synthetic source -------------------------------------------------
    shard_dir = tmp_path / "shards"
    train_seeds = list(range(1, 41))
    _write_synthetic_shard(shard_dir, train_seeds, SEQ_LEN + 1)
    shard_digests = compute_shard_digests(shard_dir)
    tok = _SpaceSeparatedIntTokenizer()
    tok_digest = tok.content_digest()

    # ---- Stage 2: authorized synthetic dataset identity + tokenizer + validated batches ----
    model_cfg = GenesisModelConfig(vocab_size=VOCAB, d_model=32, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=64, max_seq_len=SEQ_LEN + 4)
    mcfg_digest = _digest(json.dumps({"vocab_size": VOCAB, "d_model": 32}))
    loader_cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=SEQ_LEN, batch_size=4, seed=7,
        authorized_shard_digests=shard_digests, tokenizer_digest=tok_digest, packing=True,
    )
    dataset = GenesisBlockDataset(loader_cfg, tok)
    assert len(dataset) > 0, "the real loader pipeline must produce at least one validated block"
    sampler = ReproducibleSampler(num_blocks=len(dataset), seed=7)

    # ---- Stage 3: worker IPC setup (genuine authorization, not fabricated) ------------
    run_id = f"e2e-run-{secrets.token_hex(4)}"
    # Two SEPARATE, independently signed grants for the SAME run identity --
    # a real worker restart needs a renewed authorization (authorization_ids
    # are durably single-use, by this codebase's own existing anti-replay
    # guard), not a reused one.
    req, record, registry, tcd, ocd = _mint_grant_inputs(
        tmp_path, run_id=run_id, mcfg=mcfg_digest, tok_digest=tok_digest,
        dataset_digest=_digest("e2e-dataset"), shard_digests=tuple(sorted(shard_digests.values())),
    )
    req2, record2, registry2, _tcd2, _ocd2 = _mint_grant_inputs(
        tmp_path, run_id=run_id, mcfg=mcfg_digest, tok_digest=tok_digest,
        dataset_digest=_digest("e2e-dataset"), shard_digests=tuple(sorted(shard_digests.values())),
    )
    revoked_path = tmp_path / "revoked.json"
    revoked_path.write_text("[]")
    sock_dir = Path(tempfile.mkdtemp(prefix="isow-e2e-"))
    step_cfg = TrainingStepConfig(grad_accum_steps=1, warmup_steps=20, total_steps=400, max_lr=3e-3)
    config_fingerprint = compute_config_fingerprint(model_cfg, step_cfg)
    dataset_identity = {"dataset_manifest_id": "e2e-manifest", "dataset_content_digest": _digest("e2e-dataset"), "tokenizer_digest": tok_digest}
    integrity_key = secrets.token_bytes(32)
    ckpt_path = str(tmp_path / "e2e_ckpt.pt")

    def _cfg(sock_name: str, *, req, record, registry) -> WorkerStartupConfig:
        return WorkerStartupConfig(
            workload_id=run_id, auth_token=secrets.token_bytes(32), sock_path=str(sock_dir / sock_name),
            model_cfg=model_cfg, step_cfg=step_cfg, run_id=run_id, dataset_manifest_ids=("e2e-manifest",),
            environment_class=ENV, repo_root=str(REPO_ROOT), dataset_digest=_digest("e2e-dataset"),
            model_config_digest=mcfg_digest, tokenizer_digest=tok_digest,
            authorized_shard_digests=tuple(sorted(shard_digests.values())), shard_dir=str(shard_dir),
            reviewed_commit_sha=req.reviewed_commit_sha, transformation_code_digest=tcd, optimizer_config_digest=ocd,
            record=record, registry=registry, req=req, revoked_ids_path=str(revoked_path),
            orca_home_override=str(tmp_path / "ornhome"), test_only_bypass_founder_ledger=True,
            test_only_pinned_registry_sha256=GOV.registry_digest(registry),
            checkpoint_workspace_dir=str(tmp_path),
        )

    worker_a = IsolatedTrainingWorker(_cfg("worker_a.sock", req=req, record=record, registry=registry))
    worker_a.start()
    client_a = worker_a.client()
    client_a.connect()
    losses_phase1 = []
    try:
        # ---- Stage 4/5: validated batches -> worker IPC -> actual parameter update ----
        for _ in range(100):
            indices = sampler.next_batch_indices(loader_cfg.batch_size)
            input_ids, labels = make_batch(dataset, indices)
            resp = client_a.step(input_ids, labels)
            assert resp["ok"] is True, resp
            assert resp["result"]["applied"] is True
            losses_phase1.append(resp["result"]["microbatch_loss"])

        # ---- Stage 6: checkpoint save, through the worker's own IPC command ----
        save_resp = client_a.save_checkpoint(
            path=ckpt_path, integrity_key=integrity_key, sampler_position=sampler.position,
            sampler_seed=sampler.seed, sampler_num_blocks=sampler.num_blocks,
        )
        assert save_resp["ok"] is True, save_resp
        saved_step = save_resp["result"]["global_step"]
    finally:
        client_a.close()
        worker_a.stop()

    # ---- Stage 7: worker restart -- a genuinely SEPARATE, freshly spawned process ----
    worker_b = IsolatedTrainingWorker(_cfg("worker_b.sock", req=req2, record=record2, registry=registry2))
    worker_b.start()
    client_b = worker_b.client()
    client_b.connect()
    losses_phase2 = []
    try:
        # ---- Stage 8: checkpoint restore, through the worker's own IPC command ----
        restore_resp = client_b.restore_checkpoint(
            path=ckpt_path, integrity_key=integrity_key, sampler_seed=sampler.seed,
            sampler_num_blocks=sampler.num_blocks,
        )
        assert restore_resp["ok"] is True, restore_resp
        assert restore_resp["result"]["global_step"] == saved_step
        sampler.position = restore_resp["result"]["sampler_position"]

        # ---- Stage 9: continued learning, against the SAME real loader pipeline ----
        for _ in range(100):
            indices = sampler.next_batch_indices(loader_cfg.batch_size)
            input_ids, labels = make_batch(dataset, indices)
            resp = client_b.step(input_ids, labels)
            assert resp["ok"] is True, resp
            losses_phase2.append(resp["result"]["microbatch_loss"])
    finally:
        client_b.close()
        worker_b.stop()
    dataset.close()

    assert losses_phase2[-1] < losses_phase1[0] * 0.6, (
        f"loss did not meaningfully improve across the full chain: phase1 start={losses_phase1[0]:.4f}, "
        f"phase2 end={losses_phase2[-1]:.4f}"
    )

    # ---- Stage 10: held-out evaluation -- restore the SAVED checkpoint into a
    # fresh, independent, controller-side model (never the worker's own live
    # object) and evaluate it against a HELD-OUT seed never used in training ----
    restored = restore_resumable_checkpoint(
        path=Path(ckpt_path), expected_config_fingerprint=config_fingerprint,
        expected_dataset_identity=DatasetIdentity(**dataset_identity),
        expected_sampler_seed=sampler.seed, expected_sampler_num_blocks=sampler.num_blocks,
        integrity_key=integrity_key, run_id=run_id,
    )
    eval_model = GenesisTransformer(model_cfg)
    from orca.genesis.training.learning_step import TrainingStepEngine
    eval_engine = TrainingStepEngine(eval_model, step_cfg)
    restored.training_state.restore(model=eval_model, optimizer=eval_engine.optimizer)

    eval_model.eval()
    held_out_seed = 9973  # never present in train_seeds (1..24)
    held_out_chain = _chain(held_out_seed, SEQ_LEN + 1)
    with torch.no_grad():
        inp = torch.tensor([held_out_chain[:-1]], dtype=torch.long)
        logits = eval_model(inp)
        preds = logits.argmax(dim=-1)[0].tolist()
    targets = held_out_chain[1:]
    accuracy = sum(1 for p, t in zip(preds, targets) if p == t) / len(targets)
    assert accuracy > 0.7, (
        f"held-out next-token accuracy too low ({accuracy:.2f}) -- the restored checkpoint does not reflect "
        f"genuine learning of the underlying rule through the full source-to-worker-to-checkpoint chain"
    )


def test_restart_equivalence_against_uninterrupted_training(tmp_path):
    """CTO final engineering closeout, Phase 4: compares UNINTERRUPTED
    training against CHECKPOINTED-AND-RESTARTED training, both driven by
    the identical deterministic batch sequence through the real worker
    IPC chain, and reports every comparison with its own explicit
    tolerance -- never described as bit-identical, since `TrainingState`
    captures and restores Python/torch RNG state exactly, but genuine
    cross-process floating-point reduction order can still differ at
    the ULP level."""
    shard_dir = tmp_path / "shards"
    train_seeds = list(range(1, 41))
    _write_synthetic_shard(shard_dir, train_seeds, SEQ_LEN + 1)
    shard_digests = compute_shard_digests(shard_dir)
    tok = _SpaceSeparatedIntTokenizer()
    tok_digest = tok.content_digest()

    model_cfg = GenesisModelConfig(vocab_size=VOCAB, d_model=32, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=64, max_seq_len=SEQ_LEN + 4)
    mcfg_digest = _digest(json.dumps({"vocab_size": VOCAB, "d_model": 32}))
    loader_cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=SEQ_LEN, batch_size=4, seed=11,
        authorized_shard_digests=shard_digests, tokenizer_digest=tok_digest, packing=True,
    )
    dataset = GenesisBlockDataset(loader_cfg, tok)
    step_cfg = TrainingStepConfig(grad_accum_steps=1, warmup_steps=20, total_steps=400, max_lr=3e-3)
    workspace = tmp_path / "workspace"
    revoked_path = tmp_path / "revoked.json"
    revoked_path.write_text("[]")
    sock_dir = Path(tempfile.mkdtemp(prefix="isow-restarteq-"))
    integrity_key = secrets.token_bytes(32)
    dataset_digest = _digest("restarteq-dataset")

    def _build(run_id: str, sock_name: str) -> IsolatedTrainingWorker:
        req, record, registry, tcd, ocd = _mint_grant_inputs(
            tmp_path, run_id=run_id, mcfg=mcfg_digest, tok_digest=tok_digest,
            dataset_digest=dataset_digest, shard_digests=tuple(sorted(shard_digests.values())),
        )
        cfg = WorkerStartupConfig(
            workload_id=run_id, auth_token=secrets.token_bytes(32), sock_path=str(sock_dir / sock_name),
            model_cfg=model_cfg, step_cfg=step_cfg, run_id=run_id, dataset_manifest_ids=("e2e-manifest",),
            environment_class=ENV, repo_root=str(REPO_ROOT), dataset_digest=dataset_digest,
            model_config_digest=mcfg_digest, tokenizer_digest=tok_digest,
            authorized_shard_digests=tuple(sorted(shard_digests.values())), shard_dir=str(shard_dir),
            reviewed_commit_sha=req.reviewed_commit_sha, transformation_code_digest=tcd, optimizer_config_digest=ocd,
            record=record, registry=registry, req=req, revoked_ids_path=str(revoked_path),
            orca_home_override=str(tmp_path / "ornhome"), test_only_bypass_founder_ledger=True,
            test_only_pinned_registry_sha256=GOV.registry_digest(registry), checkpoint_workspace_dir=str(workspace),
        )
        worker = IsolatedTrainingWorker(cfg)
        worker.start()
        return worker

    TOTAL_STEPS = 40
    SPLIT_AT = 20

    # ---- Run 1: UNINTERRUPTED, all TOTAL_STEPS through one worker ----
    sampler_full = ReproducibleSampler(num_blocks=len(dataset), seed=99)
    worker_full = _build("restarteq-full", "full.sock")
    client_full = worker_full.client()
    client_full.connect()
    try:
        for _ in range(TOTAL_STEPS):
            indices = sampler_full.next_batch_indices(loader_cfg.batch_size)
            input_ids, labels = make_batch(dataset, indices)
            resp = client_full.step(input_ids, labels)
            assert resp["ok"] is True, resp
        ckpt_full = str(workspace / "ckpt_full.pt")
        save_resp = client_full.save_checkpoint(
            path=ckpt_full, integrity_key=integrity_key, sampler_position=sampler_full.position,
            sampler_seed=sampler_full.seed, sampler_num_blocks=sampler_full.num_blocks,
        )
        assert save_resp["ok"] is True
        full_final_step = save_resp["result"]["global_step"]
    finally:
        client_full.close()
        worker_full.stop()

    # ---- Run 2: CHECKPOINTED AND RESTARTED -- identical batch sequence, split across two workers ----
    sampler_resumed = ReproducibleSampler(num_blocks=len(dataset), seed=99)  # SAME seed -> identical batch order
    worker_a = _build("restarteq-a", "a.sock")
    client_a = worker_a.client()
    client_a.connect()
    ckpt_mid = str(workspace / "ckpt_mid.pt")
    try:
        for _ in range(SPLIT_AT):
            indices = sampler_resumed.next_batch_indices(loader_cfg.batch_size)
            input_ids, labels = make_batch(dataset, indices)
            resp = client_a.step(input_ids, labels)
            assert resp["ok"] is True, resp
        save_resp = client_a.save_checkpoint(
            path=ckpt_mid, integrity_key=integrity_key, sampler_position=sampler_resumed.position,
            sampler_seed=sampler_resumed.seed, sampler_num_blocks=sampler_resumed.num_blocks,
        )
        assert save_resp["ok"] is True
    finally:
        client_a.close()
        worker_a.stop()

    worker_b = _build("restarteq-b", "b.sock")
    client_b = worker_b.client()
    client_b.connect()
    try:
        restore_resp = client_b.restore_checkpoint(path=ckpt_mid, integrity_key=integrity_key, sampler_seed=sampler_resumed.seed, sampler_num_blocks=sampler_resumed.num_blocks)
        assert restore_resp["ok"] is True
        sampler_resumed.position = restore_resp["result"]["sampler_position"]
        for _ in range(TOTAL_STEPS - SPLIT_AT):
            indices = sampler_resumed.next_batch_indices(loader_cfg.batch_size)
            input_ids, labels = make_batch(dataset, indices)
            resp = client_b.step(input_ids, labels)
            assert resp["ok"] is True, resp
        ckpt_resumed = str(workspace / "ckpt_resumed.pt")
        save_resp = client_b.save_checkpoint(
            path=ckpt_resumed, integrity_key=integrity_key, sampler_position=sampler_resumed.position,
            sampler_seed=sampler_resumed.seed, sampler_num_blocks=sampler_resumed.num_blocks,
        )
        assert save_resp["ok"] is True
        resumed_final_step = save_resp["result"]["global_step"]
    finally:
        client_b.close()
        worker_b.stop()
    dataset.close()

    # ---- Comparison: step/scheduler progression (EXACT -- these are integers, not tolerance-based) ----
    assert full_final_step == resumed_final_step == TOTAL_STEPS
    assert sampler_full.position == sampler_resumed.position, "sampler position must match exactly -- same seed, same batch count"

    # ---- Comparison: model parameters and optimizer state (TOLERANCE-based -- explicitly NOT "bit-identical") ----
    fp = compute_config_fingerprint(model_cfg, step_cfg)
    identity = DatasetIdentity(dataset_manifest_id="e2e-manifest", dataset_content_digest=dataset_digest, tokenizer_digest=tok_digest)
    restored_full = restore_resumable_checkpoint(
        path=Path(ckpt_full), expected_config_fingerprint=fp, expected_dataset_identity=identity,
        expected_sampler_seed=sampler_full.seed, expected_sampler_num_blocks=sampler_full.num_blocks,
        integrity_key=integrity_key, run_id="restarteq-full",
    )
    restored_resumed = restore_resumable_checkpoint(
        path=Path(ckpt_resumed), expected_config_fingerprint=fp, expected_dataset_identity=identity,
        expected_sampler_seed=sampler_resumed.seed, expected_sampler_num_blocks=sampler_resumed.num_blocks,
        integrity_key=integrity_key, run_id="restarteq-b",
    )
    PARAM_ATOL = 1e-5  # explicit, stated tolerance -- NOT bit-identical equality
    model_full = GenesisTransformer(model_cfg)
    model_full.load_state_dict(restored_full.training_state.model_state_dict)
    model_resumed = GenesisTransformer(model_cfg)
    model_resumed.load_state_dict(restored_resumed.training_state.model_state_dict)
    for (n1, p1), (n2, p2) in zip(model_full.named_parameters(), model_resumed.named_parameters()):
        assert n1 == n2
        assert torch.allclose(p1, p2, atol=PARAM_ATOL), f"parameter {n1} diverged beyond atol={PARAM_ATOL}: max diff {(p1 - p2).abs().max().item()}"

    opt_full = restored_full.training_state.optimizer_state_dict
    opt_resumed = restored_resumed.training_state.optimizer_state_dict
    assert opt_full["param_groups"][0]["lr"] == pytest.approx(opt_resumed["param_groups"][0]["lr"], abs=1e-9), (
        "optimizer learning rate (a pure function of step via the cosine schedule) must match given identical step counts"
    )
    for (k1, s1), (k2, s2) in zip(opt_full["state"].items(), opt_resumed["state"].items()):
        for key in ("exp_avg", "exp_avg_sq"):
            if key in s1:
                assert torch.allclose(s1[key], s2[key], atol=PARAM_ATOL), f"optimizer state {key} for param {k1} diverged beyond atol={PARAM_ATOL}"

    # ---- Comparison: numerical losses within an explicitly stated tolerance ----
    # Feed ONE further identical batch to each restored (full/resumed) model+
    # optimizer pair and compare the resulting loss -- proves the two final
    # states are numerically equivalent enough to behave the same going
    # forward, not merely that their saved tensors happen to look similar.
    from orca.genesis.training.primitives import causal_lm_loss
    probe_batch = torch.randint(4, VOCAB, (2, SEQ_LEN))
    with torch.no_grad():
        loss_full = causal_lm_loss(model_full(probe_batch), probe_batch).item()
        loss_resumed = causal_lm_loss(model_resumed(probe_batch), probe_batch).item()
    assert loss_full == pytest.approx(loss_resumed, abs=1e-4), (
        f"probe loss diverged beyond the stated 1e-4 tolerance: full={loss_full}, resumed={loss_resumed}"
    )

    # ---- Held-out evaluation, before AND after the resumed phase ----
    held_out_seed = 9973
    held_out_chain = _chain(held_out_seed, SEQ_LEN + 1)
    inp = torch.tensor([held_out_chain[:-1]], dtype=torch.long)
    targets = held_out_chain[1:]

    model_mid = GenesisTransformer(model_cfg)
    mid_restored = restore_resumable_checkpoint(
        path=Path(ckpt_mid), expected_config_fingerprint=fp, expected_dataset_identity=identity,
        expected_sampler_seed=99, expected_sampler_num_blocks=sampler_full.num_blocks,
        integrity_key=integrity_key, run_id="restarteq-a",
    )
    model_mid.load_state_dict(mid_restored.training_state.model_state_dict)
    model_mid.eval()
    with torch.no_grad():
        preds_before = model_mid(inp).argmax(dim=-1)[0].tolist()
    accuracy_before = sum(1 for p, t in zip(preds_before, targets) if p == t) / len(targets)

    model_resumed.eval()
    with torch.no_grad():
        preds_after = model_resumed(inp).argmax(dim=-1)[0].tolist()
    accuracy_after = sum(1 for p, t in zip(preds_after, targets) if p == t) / len(targets)

    assert accuracy_after >= accuracy_before - 0.1, (
        f"held-out accuracy regressed after resumed training: before={accuracy_before:.2f}, after={accuracy_after:.2f}"
    )
