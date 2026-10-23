"""
GENESIS Native Learning Engine, Phase 1, Workstream 5 tests:
`orca.genesis.training.learning_governance`. Confirms the fail-closed
gate in front of a real optimizer step -- no training occurs here
except where the run's own, already-audited authorization state machine
has independently reached RUNNING via a synthetic, isolated grant (the
same `GrantWorld` pattern `tests/test_genesis_training_orchestration.py`
already established); the REAL founder ledger/authority registry are
never touched.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

import orca.config as orca_config  # noqa: E402
import orca.genesis.governance.authorization as GOV  # noqa: E402
import orca.genesis.training.orchestration as ORCH  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.training.learning_governance import (  # noqa: E402
    TrainingNotAuthorizedForExecutionError,
    execute_authorized_training_step,
)
from orca.genesis.training.learning_step import TrainingStepConfig, TrainingStepEngine, set_deterministic_seed  # noqa: E402
from orca.genesis.training.orchestration import BoundDatasetRecords, GenesisTrainingRun, RunState  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"
MODEL_CFG = GenesisModelConfig(vocab_size=32, d_model=8, n_layers=1, n_heads=2, n_kv_heads=1, d_ff=16, max_seq_len=8)


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


def _make_shard_dir(tmp_path) -> tuple[Path, tuple[str, ...]]:
    from orca.genesis.data.pipeline import compute_shard_digests
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    (shard_dir / "shard-0000-train.jsonl").write_text('{"text": "governance test fixture record"}\n')
    digests = compute_shard_digests(shard_dir)
    return shard_dir, tuple(sorted(digests.values()))


def _mint_grant(monkeypatch, *, run_id, mcfg, tok_digest, manifest_id, dataset_digest, shard_digests, tcd, ocd, revocation_check=None, founder_ready=True):
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
        "schema_version": GOV.SCHEMA_VERSION, "authorization_id": "gnpauth-" + "aa" * 8, "status": "AUTHORIZED",
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
    if founder_ready:
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
        "gov-test-run", dataset_manifest_ids=("gov-fixture-manifest",), environment_class=ENV,
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
        monkeypatch, run_id="gov-test-run", mcfg=mcfg, tok_digest=tok_digest, manifest_id="gov-fixture-manifest",
        dataset_digest=_digest("dataset"), shard_digests=shard_digests, tcd=tcd, ocd=ocd,
        revocation_check=revocation_check,
    )
    run.authorize(grant)
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    run.start()
    return run


def _make_engine():
    set_deterministic_seed(0)
    model = GenesisTransformer(MODEL_CFG)
    return TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=1, warmup_steps=1, total_steps=10))


def _batch():
    ids = torch.randint(0, MODEL_CFG.vocab_size, (1, 4))
    return ids, ids.clone()


def test_a_non_genesis_training_run_object_is_rejected():
    engine = _make_engine()
    input_ids, labels = _batch()

    class FakeRun:
        state = RunState.RUNNING

    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(FakeRun(), engine, input_ids, labels)  # type: ignore[arg-type]


def test_a_real_run_not_in_running_state_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    run = GenesisTrainingRun(
        "not-running-run", dataset_manifest_ids=("m",), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    assert run.state is RunState.PLANNED
    engine = _make_engine()
    input_ids, labels = _batch()
    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(run, engine, input_ids, labels)


def test_a_genuinely_running_authorized_run_may_execute_a_real_step(tmp_path, monkeypatch):
    run = _build_running_run(tmp_path, monkeypatch)
    assert run.state is RunState.RUNNING
    engine = _make_engine()
    input_ids, labels = _batch()
    before = {n: p.clone() for n, p in engine.model.named_parameters()}
    result = execute_authorized_training_step(run, engine, input_ids, labels)
    assert result.applied is True
    changed = any(not torch.equal(before[n], p) for n, p in engine.model.named_parameters())
    assert changed


def test_revocation_blocks_resume_and_therefore_blocks_further_execution(tmp_path, monkeypatch):
    """Workstream 4 item 8: revocation must block execution. Revocation
    is checked at resume-capable transitions (the run's own existing,
    audited design, Mission 2) -- demonstrated here by pausing then
    showing resume (required before any further step through this
    run) is denied once the revocation hook starts returning True."""
    revoked_flag = {"revoked": False}
    run = _build_running_run(tmp_path, monkeypatch, revocation_check=lambda auth_id: revoked_flag["revoked"])
    engine = _make_engine()
    input_ids, labels = _batch()
    execute_authorized_training_step(run, engine, input_ids, labels)

    run.pause()
    revoked_flag["revoked"] = True
    with pytest.raises(GOV.NativePretrainingNotAuthorized):
        run.resume()
    assert run.state is RunState.FAILED
    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(run, engine, input_ids, labels)


def test_a_rejected_run_can_never_execute_even_with_a_valid_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    run = GenesisTrainingRun(
        "reject-run", dataset_manifest_ids=("m",), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    run.reject(reason="test")
    assert run.state is RunState.REJECTED
    engine = _make_engine()
    input_ids, labels = _batch()
    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(run, engine, input_ids, labels)


def test_the_real_unauthorized_production_ledger_still_denies_start(tmp_path, monkeypatch):
    """Confirms the thing that actually keeps production disabled: WITHOUT
    monkeypatching check_founder_acceptance_ledger (i.e. against the
    real, committed, empty ledger), start() must still deny -- this is
    not something learning_governance.py enforces itself, it is a
    structural consequence of this repository's real NOT_AUTHORIZED
    state, re-confirmed here as a regression guard."""
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    shard_dir, shard_digests = _make_shard_dir(tmp_path)
    mcfg, tcd, ocd = (_digest(x) for x in ("mcfg2", "tcd2", "ocd2"))
    tok_digest = _digest("tok2")
    run = GenesisTrainingRun(
        "real-ledger-run", dataset_manifest_ids=("gov-fixture-manifest-2",), environment_class=ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    records = ["gov-fixture-record-2"]
    run.validate(
        dataset_manifest=BoundDatasetRecords("gov-fixture-manifest-2", _digest("dataset2"), tuple(records)),
        dataset_records=records,
        model_config_digest=mcfg, tokenizer_digest=tok_digest,
        authorized_shard_digests=shard_digests, shard_dir=shard_dir, reviewed_commit_sha=HEAD_SHA,
        transformation_code_digest=tcd, optimizer_config_digest=ocd,
    )
    run.request_authorization()
    grant = _mint_grant(
        monkeypatch, run_id="real-ledger-run", mcfg=mcfg, tok_digest=tok_digest, manifest_id="gov-fixture-manifest-2",
        dataset_digest=_digest("dataset2"), shard_digests=shard_digests, tcd=tcd, ocd=ocd,
    )
    run.authorize(grant)
    # Deliberately NOT monkeypatching ORCH.check_founder_acceptance_ledger here.
    with pytest.raises(ORCH.ExecutionAcceptanceIncompleteError):
        run.start()
    assert run.state is RunState.REJECTED


# ==================================================================================
# Antigravity Audit #074 remediation: AUDIT-P0-02 (in-flight re-validation)
# ==================================================================================

def test_p0_02_revocation_is_caught_in_flight_without_any_pause_resume_cycle(tmp_path, monkeypatch):
    """The audit's own exact reproduction, corrected: a grant revoked
    WHILE a run stays continuously RUNNING (no pause()/resume() at all)
    must be caught on the very next call through
    execute_authorized_training_step() -- not merely at the next state
    transition, which this specific scenario never performs."""
    revoked_flag = {"revoked": False}
    run = _build_running_run(tmp_path, monkeypatch, revocation_check=lambda auth_id: revoked_flag["revoked"])
    engine = _make_engine()
    input_ids, labels = _batch()

    r1 = execute_authorized_training_step(run, engine, input_ids, labels)
    assert r1.applied is True
    assert run.state is RunState.RUNNING  # still RUNNING -- no transition occurred

    revoked_flag["revoked"] = True
    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(run, engine, input_ids, labels)
    # The run's in-memory .state is untouched by this in-flight check (only
    # transitions change .state) -- but every further call is still denied.
    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(run, engine, input_ids, labels)


def test_p0_02_dataset_identity_drift_is_caught_in_flight(tmp_path, monkeypatch):
    """A shard file tampered WHILE a run stays continuously RUNNING (no
    pause()/resume()) is caught on the next call through
    execute_authorized_training_step() -- reusing the run's own identity
    snapshot comparison, re-derived fresh each call."""
    run = _build_running_run(tmp_path, monkeypatch)
    engine = _make_engine()
    input_ids, labels = _batch()
    execute_authorized_training_step(run, engine, input_ids, labels)
    assert run.state is RunState.RUNNING

    shard_dir = run.identity.shard_dir
    shard_file = sorted(shard_dir.glob("shard-*.jsonl"))[0]
    shard_file.write_bytes(b'{"text": "tampered mid-flight, no transition occurred"}\n')

    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(run, engine, input_ids, labels)


def test_p0_02_a_hollow_run_object_forging_running_state_is_rejected(tmp_path, monkeypatch):
    """A subclass or stand-in that sets `.state = RunState.RUNNING`
    directly, bypassing validate()/authorize()/start() entirely (exactly
    the audit's own `DummyRun` reproduction), must be rejected with a
    clear, intentional exception -- not silently accepted, and not an
    opaque AttributeError that looks like a bug rather than a boundary."""
    class HollowRun(GenesisTrainingRun):
        def __init__(self):
            self.state = RunState.RUNNING
            self.identity = type("Identity", (), {"run_id": "hollow-run"})()

    run = HollowRun()
    engine = _make_engine()
    input_ids, labels = _batch()
    with pytest.raises(TrainingNotAuthorizedForExecutionError):
        execute_authorized_training_step(run, engine, input_ids, labels)
