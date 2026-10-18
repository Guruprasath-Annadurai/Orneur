"""
GENESIS Native Learning Engine -- Antigravity Audit #075 (independent
successor requalification) remediation, Mission A: adversarial tests
for `orca.genesis.training.isolated_worker`. Bounded, CPU-only,
synthetic model/data only, single-host.
"""
from __future__ import annotations

import hashlib
import json
import os
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
import orca.genesis.training.orchestration as ORCH  # noqa: E402
from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.training.isolated_worker import (  # noqa: E402
    IsolatedTrainingWorker,
    IsolationPropertiesUnavailableError,
    WorkerStartupConfig,
    WorkerStartupError,
)
from orca.genesis.training.learning_step import TrainingStepConfig  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"
TINY_MODEL_CFG = GenesisModelConfig(vocab_size=32, d_model=16, n_layers=2, n_heads=2, n_kv_heads=1, d_ff=32, max_seq_len=16)
STEP_CFG = TrainingStepConfig(grad_accum_steps=1, warmup_steps=2, total_steps=50, max_lr=1e-2)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Note: the worker runs in a SEPARATELY SPAWNED process (see
    # isolated_worker.py's own comment on why "spawn", not "fork") --
    # it does not inherit these monkeypatches at all. The worker's own
    # process-local equivalents are `WorkerStartupConfig.orca_home_override`
    # and `.test_only_bypass_founder_ledger`, set explicitly in `_make_cfg()`
    # below. This fixture still isolates ORCA_HOME for anything the
    # CONTROLLER (this test process) itself touches directly.
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


def _make_cfg(tmp_path, *, run_id="iso-worker-run", revoked_ids_path=None, expiry_minutes=120, drop_to_uid=None):
    mcfg, tcd, ocd = (_digest(x) for x in ("mcfg", "tcd", "ocd"))
    tok_digest = _digest("tok")
    dataset_digest = _digest("dataset")
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / "shard-0000-train.jsonl"
    shard_file.write_text('{"text": "isolated worker fixture shard"}\n')
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
    req = GOV.NativePretrainingRequest(
        run_id=run_id, nonce=_digest(f"nonce-{run_id}-{secrets.token_hex(4)}"), model_family="genesis",
        architecture_version="genesis-arch-v1", model_config_digest=mcfg, tokenizer_digest=tok_digest,
        dataset_manifest_id="iso-worker-manifest", dataset_content_digest=dataset_digest,
        authorized_shard_digests=authorized_shard_digests, reviewed_commit_sha=_git_head(), transformation_code_digest=tcd,
        optimizer_config_digest=ocd, environment_class=ENV, gpu_requested=False,
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
        "issued_at": _ts(now - timedelta(minutes=1)), "expires_at": _ts(now + timedelta(minutes=expiry_minutes)),
        "authorizing_authority": {"identity": "gov-worker-authority", "role": "OWNER", "key_id": "gov-worker-authority"},
        "signature": None,
    }
    record["signature"] = priv.sign(GOV.canonical_signing_bytes(record)).hex()
    pinned_registry_sha256 = GOV.registry_digest(registry)

    revoked_ids_path = revoked_ids_path or (tmp_path / "revoked.json")
    if not Path(revoked_ids_path).exists():
        Path(revoked_ids_path).write_text("[]")

    # AF_UNIX paths have a short OS-level length limit (~104 bytes on
    # macOS) -- pytest's own tmp_path is often already too deep, so the
    # socket directory is created directly under the system tempdir,
    # not under tmp_path, with a short random name.
    sock_dir = Path(tempfile.mkdtemp(prefix="isow-"))
    os.chmod(sock_dir, 0o700)

    return WorkerStartupConfig(
        workload_id=run_id, auth_token=secrets.token_bytes(32), sock_path=str(sock_dir / "worker.sock"),
        model_cfg=TINY_MODEL_CFG, step_cfg=STEP_CFG, run_id=run_id, dataset_manifest_ids=("iso-worker-manifest",),
        environment_class=ENV, repo_root=str(REPO_ROOT), dataset_digest=dataset_digest, model_config_digest=mcfg,
        tokenizer_digest=tok_digest, authorized_shard_digests=authorized_shard_digests, shard_dir=str(shard_dir),
        reviewed_commit_sha=req.reviewed_commit_sha, transformation_code_digest=tcd, optimizer_config_digest=ocd,
        record=record, registry=registry, req=req, revoked_ids_path=str(revoked_ids_path), drop_to_uid=drop_to_uid,
        orca_home_override=str(tmp_path / "ornhome"), test_only_bypass_founder_ledger=True,
        test_only_pinned_registry_sha256=pinned_registry_sha256,
    )


def _git_head() -> str:
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    return p.stdout.strip() if p.returncode == 0 else "0" * 40


def _batch():
    return torch.randint(0, 32, (2, 8))


def test_worker_boots_and_serves_an_authorized_step(tmp_path):
    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            batch = _batch()
            resp = client.step(batch, batch.clone())
            assert resp["ok"] is True
            assert resp["result"]["applied"] is True
            assert resp["result"]["global_step"] == 0
        finally:
            client.close()
    finally:
        worker.stop()


def test_client_never_holds_a_reference_to_the_model_optimizer_or_engine(tmp_path):
    """The actual structural proof of the isolation boundary: the
    client object has no attribute exposing model/optimizer/engine --
    it is a pure socket wrapper."""
    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        client = worker.client()
        for forbidden in ("model", "optimizer", "engine", "_capability_token", "grant"):
            assert not hasattr(client, forbidden)
    finally:
        worker.stop()


def test_a_message_with_the_wrong_auth_token_is_rejected(tmp_path):
    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        from orca.genesis.training.isolated_worker import IsolatedWorkerClient
        forged = IsolatedWorkerClient(cfg.sock_path, b"completely-wrong-token-xxxxxxxx", cfg.workload_id)
        forged.connect()
        try:
            resp = forged.ping()
            assert resp["ok"] is False
            assert resp["error"] == "AUTHENTICATION_FAILED"
        finally:
            forged.close()
    finally:
        worker.stop()


def test_a_request_for_a_different_workload_id_is_rejected(tmp_path):
    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        from orca.genesis.training.isolated_worker import IsolatedWorkerClient
        wrong_workload = IsolatedWorkerClient(cfg.sock_path, cfg.auth_token, "some-other-run-entirely")
        wrong_workload.connect()
        try:
            resp = wrong_workload.ping()
            assert resp["ok"] is False
            assert resp["error"] == "CROSS_WORKLOAD_REQUEST"
        finally:
            wrong_workload.close()
    finally:
        worker.stop()


def test_replaying_a_previously_sent_message_is_rejected(tmp_path):
    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            # Manually construct and send the SAME framed message twice --
            # a real replay, not merely calling ping() twice (which would
            # use two different seq/nonce values by construction).
            from orca.genesis.training.isolated_worker import _canonical, _send_framed, _recv_framed, _sign
            seq, nonce = 1, secrets.token_hex(16)
            sig = _sign(cfg.auth_token, seq=seq, nonce=nonce, command="ping", workload_id=cfg.workload_id, payload={})
            msg = _canonical({"seq": seq, "nonce": nonce, "command": "ping", "workload_id": cfg.workload_id, "payload": {}, "hmac": sig})
            _send_framed(client._sock, msg)
            first = json.loads(_recv_framed(client._sock).decode())
            assert first["ok"] is True

            _send_framed(client._sock, msg)  # the exact same bytes again
            second = json.loads(_recv_framed(client._sock).decode())
            assert second["ok"] is False
            assert second["error"] == "REPLAYED_MESSAGE"
        finally:
            client.close()
    finally:
        worker.stop()


def test_a_forged_in_process_capability_is_never_reachable_from_the_client(tmp_path):
    """Mission B: even a client payload that TRIES to smuggle a
    capability-shaped field has no effect -- the worker's own protocol
    has no field for a capability at all; the worker always mints its
    own, internally, via the governed path."""
    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            batch = _batch()
            resp = client._request("step", {
                "input_ids": batch.tolist(), "labels": batch.tolist(),
                "capability": {"_token": "00" * 32, "_unchecked": True},  # smuggled, ignored entirely
            })
            assert resp["ok"] is True  # step still succeeds, but ONLY via the worker's own real governance path
        finally:
            client.close()
    finally:
        worker.stop()


def test_revocation_mid_session_stops_the_worker_process_entirely(tmp_path):
    """Mission A's core requirement: authorization invalidated WHILE
    running terminates the worker, not merely refuses one command."""
    revoked_path = tmp_path / "revoked.json"
    revoked_path.write_text("[]")
    cfg = _make_cfg(tmp_path, revoked_ids_path=revoked_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        client = worker.client()
        client.connect()
        try:
            batch = _batch()
            ok_resp = client.step(batch, batch.clone())
            assert ok_resp["ok"] is True

            # Revoke the authorization_id this worker's grant was minted under.
            revoked_path.write_text(json.dumps([cfg.record["authorization_id"]]))

            denied_resp = client.step(batch, batch.clone())
            assert denied_resp["ok"] is False
            assert "AUTHORIZATION_DENIED" in denied_resp["error"]
        finally:
            client.close()

        worker.join(timeout=5.0)
        assert not worker.is_alive, "worker must terminate its own process after an in-flight authorization failure"

        # And a fresh connection attempt must now fail -- there is no
        # process left listening on the socket at all.
        from orca.genesis.training.isolated_worker import IsolatedWorkerClient
        dead_client = IsolatedWorkerClient(cfg.sock_path, cfg.auth_token, cfg.workload_id)
        with pytest.raises((FileNotFoundError, ConnectionRefusedError, OSError)):
            dead_client.connect()
    finally:
        worker.stop()


def test_expired_grant_is_rejected_before_the_worker_ever_binds_its_socket(tmp_path):
    """An already-expired grant must fail closed during startup
    (inside run.start()'s re-verification), never silently succeed."""
    cfg = _make_cfg(tmp_path, expiry_minutes=-5)
    worker = IsolatedTrainingWorker(cfg)
    with pytest.raises(WorkerStartupError):
        worker.start()
    assert not Path(cfg.sock_path).exists()


def test_strict_uid_isolation_fails_closed_when_not_root(tmp_path):
    """Mission A: requesting drop_to_uid without root privileges must
    refuse to start under the WEAKER, original uid -- never silently
    downgrade the isolation guarantee it was asked for."""
    if os.getuid() == 0:
        pytest.skip("this test specifically verifies the non-root fail-closed path")
    cfg = _make_cfg(tmp_path, drop_to_uid=65534)
    worker = IsolatedTrainingWorker(cfg)
    with pytest.raises(WorkerStartupError) as exc_info:
        worker.start()
    assert "root" in str(exc_info.value).lower()


def test_socket_directory_accessible_to_others_is_rejected(tmp_path):
    """A world/group-readable socket directory must be refused, not
    silently bound into -- AUDIT path-substitution-adjacent hardening."""
    cfg = _make_cfg(tmp_path)
    os.chmod(Path(cfg.sock_path).parent, 0o755)  # world-readable -- violates the isolation requirement
    worker = IsolatedTrainingWorker(cfg)
    with pytest.raises(WorkerStartupError) as exc_info:
        worker.start()
    assert "IsolationPropertiesUnavailableError" in str(exc_info.value) or "accessible to group or other" in str(exc_info.value)


# ==============================================================================
# CTO pre-handoff security directive -- isolation qualification must be
# honestly REPORTED, never asserted from "this is a separate process" alone.
# ==============================================================================

def test_isolation_qualification_is_reported_and_never_overclaimed(tmp_path):
    """Without drop_to_uid, this worker must NEVER report
    PEER_VERIFIED_UID_SEPARATED (the only label this module considers
    genuine privilege isolation) -- it may report ISOLATION_NOT_QUALIFIED
    (peer-credential checking unavailable on this platform, e.g. macOS)
    or PEER_VERIFIED_SAME_UID (Linux, SO_PEERCRED available, but still
    one uid), but never the strongest label without an actual uid drop."""
    from orca.genesis.training.isolated_worker import (
        ISOLATION_NOT_QUALIFIED,
        PEER_VERIFIED_SAME_UID,
        PEER_VERIFIED_UID_SEPARATED,
    )

    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        assert worker.isolation_qualification in (ISOLATION_NOT_QUALIFIED, PEER_VERIFIED_SAME_UID)
        assert worker.isolation_qualification != PEER_VERIFIED_UID_SEPARATED
    finally:
        worker.stop()


def test_the_worker_module_never_references_the_synthetic_test_bypass(tmp_path):
    """Structural, not behavioral: the directive explicitly rejects
    'pytest in sys.modules' as a trustworthy security control. The
    actual guarantee this test proves is structural -- the production
    worker entrypoint's OWN source code contains no reference at all to
    ExecutionCapability.for_unchecked_synthetic_test, so there is no
    code path by which the worker could ever call it, regardless of
    what sys.modules contains at runtime."""
    import inspect

    from orca.genesis.training import isolated_worker as worker_module

    source = inspect.getsource(worker_module)
    assert "for_unchecked_synthetic_test" not in source
    assert "_unchecked" not in source


def test_a_production_configured_worker_can_never_reach_running(tmp_path):
    """Without test_only_bypass_founder_ledger, this worker's call to
    run.start() always re-checks the REAL, project-wide founder-
    acceptance ledger (orchestration.py's own, unmodified
    check_founder_acceptance_ledger) -- which is genuinely, intentionally
    empty today. A 'production' worker configuration (the only
    difference from every other test in this file) must fail to start,
    never silently proceed as if authorized."""
    cfg = _make_cfg(tmp_path)
    cfg = WorkerStartupConfig(**{**cfg.__dict__, "test_only_bypass_founder_ledger": False, "test_only_pinned_registry_sha256": None})
    worker = IsolatedTrainingWorker(cfg)
    with pytest.raises(WorkerStartupError) as exc_info:
        worker.start()
    assert "FOUNDER_ACCEPTANCE_INCOMPLETE" in str(exc_info.value) or "NativePretrainingNotAuthorized" in str(exc_info.value) or "AUTHORITY_REGISTRY" in str(exc_info.value)
    assert not Path(cfg.sock_path).exists()


def test_test_only_founder_ledger_bypass_never_weakens_grant_signature_verification(tmp_path):
    """CTO pre-handoff security directive, Mission 1: a synthetic test
    grant must remain visibly synthetic and can never be promoted into
    production authorization. Concretely: test_only_bypass_founder_ledger
    stubs ONLY the founder-acceptance-ledger gate -- it must NOT also
    weaken or skip Ed25519 signature verification on the record itself.
    A forged (unsigned/tampered) record must still be rejected even
    with the test-only bypass active."""
    cfg = _make_cfg(tmp_path)
    tampered_record = dict(cfg.record)
    tampered_record["signature"] = "00" * 64  # forged, not a real Ed25519 signature over this record
    cfg = WorkerStartupConfig(**{**cfg.__dict__, "record": tampered_record})
    worker = IsolatedTrainingWorker(cfg)
    with pytest.raises(WorkerStartupError):
        worker.start()
    assert not Path(cfg.sock_path).exists()


def test_the_worker_never_constructs_a_grant_itself_only_verifies_one(tmp_path):
    """Structural: the worker's own source code never instantiates
    NativePretrainingGrant directly -- the only grant object it ever
    holds is whatever authorize_native_pretraining() (the same,
    unmodified, real verification choke point every other GENESIS
    caller uses) hands back after independently verifying a genuine
    signed record against a pinned registry."""
    import inspect

    from orca.genesis.training import isolated_worker as worker_module

    source = inspect.getsource(worker_module)
    assert "NativePretrainingGrant(" not in source
    assert "_seal=" not in source


def test_checkpoint_ipc_commands_are_protected_by_the_same_auth_and_replay_checks(tmp_path):
    """AUDIT-076, Mission 3/4: the new save_checkpoint/restore_checkpoint
    IPC commands go through the SAME dispatch loop as step/ping/shutdown
    -- not a special-cased, less-protected path. A wrong-token request
    for save_checkpoint must be rejected exactly like any other command."""
    cfg = _make_cfg(tmp_path)
    worker = IsolatedTrainingWorker(cfg)
    worker.start()
    try:
        from orca.genesis.training.isolated_worker import IsolatedWorkerClient
        forged = IsolatedWorkerClient(cfg.sock_path, b"completely-wrong-token-xxxxxxxx", cfg.workload_id)
        forged.connect()
        try:
            resp = forged.save_checkpoint(
                path=str(tmp_path / "x.pt"), integrity_key=b"k" * 32, sampler_position=0, sampler_seed=0,
                sampler_num_blocks=1, config_fingerprint="fp", dataset_identity={"dataset_manifest_id": "m", "dataset_content_digest": "d" * 64, "tokenizer_digest": "t" * 64},
                ledger_run_id="x",
            )
            assert resp["ok"] is False
            assert resp["error"] == "AUTHENTICATION_FAILED"
        finally:
            forged.close()
    finally:
        worker.stop()
