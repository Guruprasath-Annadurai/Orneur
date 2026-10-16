"""
GENESIS Foundation Sprint 2, Workstream C: training-orchestration state
machine tests. No training loop, GPU, or optimizer step runs anywhere in
this file. Real `orca.train.authorization.TrainingGrant` objects used here
are minted via the SAME synthetic-world fixture
`tests/test_training_authorization_gate.py` uses for its own tests --
throw-away Ed25519 keys generated per test, a throw-away registry/repo, the
gate's pin patched to point at it. Nothing here touches the real, empty,
committed authority registry.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.training.checkpoint_integrity import save_verified_training_state  # noqa: E402
from orca.genesis.training.orchestration import (  # noqa: E402
    ForgedCompletionError,
    GenesisTrainingRun,
    InvalidTransitionError,
    ReplayedAuthorizationError,
    RunState,
    StaleAuthorizationError,
)
from orca.genesis.training.primitives import TrainingState  # noqa: E402
from orca.train.authorization import TrainingGrant, TrainingNotAuthorized  # noqa: E402
from tests.test_training_authorization_gate import ENV, World  # noqa: E402


def _dataset_digest() -> str:
    return hashlib.sha256(b"synthetic-genesis-dataset-bytes").hexdigest()


def _real_checkpoint(tmp_path: Path, *, step: int) -> Path:
    path = tmp_path / "checkpoint.pt"
    state = TrainingState(
        step=step, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={},
        python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None,
    )
    save_verified_training_state(state, path)
    return path


@pytest.fixture(autouse=True)
def _reset_replay_guard():
    """GenesisTrainingRun's replay guard is process-wide by design (it
    protects across runs within one process, not just within one run
    object) -- reset it between tests so World's fixed default
    authorization_id doesn't spuriously trip the replay guard across
    unrelated test functions."""
    GenesisTrainingRun._consumed_authorization_ids.clear()
    yield
    GenesisTrainingRun._consumed_authorization_ids.clear()


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


@pytest.fixture
def grant(world) -> TrainingGrant:
    return world.authorize()


def _run() -> GenesisTrainingRun:
    return GenesisTrainingRun("run-1", dataset_manifest_ids=("ds-1",))


# ------------------------------------------------------ happy path, full lifecycle --

def test_full_lifecycle_planned_to_completed(grant, tmp_path):
    run = _run()
    assert run.state is RunState.PLANNED

    run.validate(dataset_digest=_dataset_digest())
    assert run.state is RunState.VALIDATED

    run.request_authorization()
    assert run.state is RunState.AWAITING_AUTHORIZATION

    run.authorize(grant)
    assert run.state is RunState.AUTHORIZED
    assert run.grant is grant

    run.start()
    assert run.state is RunState.RUNNING
    assert run.execution is not None and run.execution.steps_recorded == 0

    run.record_step(1)
    run.record_step(2)
    assert run.execution.steps_recorded == 2

    ckpt = _real_checkpoint(tmp_path, step=2)
    run.complete(checkpoint_path=ckpt)
    assert run.state is RunState.COMPLETED
    assert run.completion is not None and run.completion.final_step == 2

    report_sha = hashlib.sha256(b"a real evaluation report's bytes").hexdigest()
    run.record_evaluator_approval(evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256=report_sha)
    assert run.evaluator_approval is not None and run.evaluator_approval.approved is True


def test_pause_resume_cycle(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(1)

    run.pause(reason="operator paused")
    assert run.state is RunState.PAUSED
    run.resume()
    assert run.state is RunState.RUNNING


def test_pause_recover_cycle(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(1)

    run.pause(reason="checkpoint corruption suspected")
    run.begin_recovery(reason="restoring from last good checkpoint")
    assert run.state is RunState.RECOVERING
    run.recovered()
    assert run.state is RunState.RUNNING


# --------------------------------------------------------- forbidden transitions --

def test_cannot_skip_straight_from_planned_to_running():
    run = _run()
    with pytest.raises(InvalidTransitionError):
        run.start()
    assert run.state is RunState.PLANNED


def test_cannot_authorize_before_requesting_authorization(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    with pytest.raises(InvalidTransitionError):
        run.authorize(grant)
    assert run.state is RunState.VALIDATED


def test_cannot_restart_a_completed_run(grant, tmp_path):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(1)
    run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert run.state is RunState.COMPLETED
    with pytest.raises(InvalidTransitionError):
        run.start()


def test_cannot_resume_a_failed_run(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.fail(reason="simulated infrastructure failure")
    assert run.state is RunState.FAILED
    with pytest.raises(InvalidTransitionError):
        run.resume()
    with pytest.raises(InvalidTransitionError):
        run.reject(reason="too late")


def test_cannot_reject_a_terminal_run(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.reject(reason="founder declined")
    assert run.state is RunState.REJECTED
    with pytest.raises(InvalidTransitionError):
        run.reject(reason="again")


def test_invalid_dataset_digest_rejects_the_run():
    run = _run()
    with pytest.raises(ValueError):
        run.validate(dataset_digest="not-a-real-sha256")
    assert run.state is RunState.REJECTED


# --------------------------------------------------------- spoofed authorization --

@pytest.mark.parametrize("fake", [True, {"authorized": True}, "AUTHORIZED", 1])
def test_authorize_rejects_a_plain_boolean_or_dict_claiming_authorization(fake):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    with pytest.raises(TrainingNotAuthorized):
        run.authorize(fake)
    assert run.state is RunState.REJECTED


def test_authorize_rejects_a_hand_constructed_training_grant_lookalike():
    """A caller cannot mint their own TrainingGrant by hand -- its own
    __post_init__ already refuses construction without the module-private
    seal, independently of this orchestrator's own checks."""
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    with pytest.raises(TrainingNotAuthorized):
        TrainingGrant(
            authorization_id="tauth-" + "ff" * 8, key_id="fake-key", record_sha256="0" * 64, run_slot=0,
            expires_at="2099-01-01T00:00:00Z", max_wall_clock_minutes=60, cfg_fingerprint="0" * 64,
            train_sha256="0" * 64, eval_sha256=None, environment_class=ENV,
        )
    assert run.state is RunState.AWAITING_AUTHORIZATION  # never reached authorize() at all


# ------------------------------------------------------------------- tampering --

def test_authorize_rejects_a_tampered_grant(grant):
    """A real, legitimately-issued grant whose field was edited after
    issuance (bypassing the frozen dataclass via object.__setattr__, as an
    attacker with process memory access might) must fail its own
    HMAC-tag check."""
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    object.__setattr__(grant, "max_wall_clock_minutes", 999999)
    with pytest.raises(TrainingNotAuthorized):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_start_rechecks_integrity_and_catches_tampering_after_authorize(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    object.__setattr__(grant, "run_slot", 999)
    with pytest.raises(TrainingNotAuthorized):
        run.start()
    assert run.state is RunState.REJECTED


# ---------------------------------------------------------------------- replay --

def test_the_same_authorization_id_cannot_authorize_two_different_runs(grant):
    run_a = GenesisTrainingRun("run-a", dataset_manifest_ids=("ds-1",))
    run_a.validate(dataset_digest=_dataset_digest())
    run_a.request_authorization()
    run_a.authorize(grant)
    assert run_a.state is RunState.AUTHORIZED

    run_b = GenesisTrainingRun("run-b", dataset_manifest_ids=("ds-1",))
    run_b.validate(dataset_digest=_dataset_digest())
    run_b.request_authorization()
    with pytest.raises(ReplayedAuthorizationError):
        run_b.authorize(grant)
    assert run_b.state is RunState.REJECTED


# -------------------------------------------------------------- stale records --

def test_the_authorization_gate_itself_denies_an_already_expired_record(tmp_path, monkeypatch):
    """Not this orchestrator's own check -- confirms the layer below
    (orca.train.authorization) already denies an expired record at the
    source, so no grant for an expired record ever reaches this module in
    the first place."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    rec_over = {
        "issued_at": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    w = World(tmp_path, monkeypatch, record_over=rec_over)
    with pytest.raises(TrainingNotAuthorized):
        w.authorize()


def test_start_rejects_a_grant_that_expires_between_authorize_and_start(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    # Simulate time passing past the grant's validity window without re-signing anything --
    # this models a long gap between authorize() and start() in a real deployment.
    object.__setattr__(grant, "expires_at", "2000-01-01T00:00:00Z")
    object.__setattr__(grant, "_mac", grant._compute_mac())  # keep the tamper-check itself honest about what we changed
    with pytest.raises(StaleAuthorizationError):
        run.start()
    assert run.state is RunState.REJECTED


def test_recovered_rejects_a_grant_that_expired_during_recovery(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(1)
    run.pause(reason="pausing")
    run.begin_recovery(reason="recovering")
    object.__setattr__(grant, "expires_at", "2000-01-01T00:00:00Z")
    object.__setattr__(grant, "_mac", grant._compute_mac())
    with pytest.raises(StaleAuthorizationError):
        run.recovered()
    assert run.state is RunState.FAILED


# ------------------------------------------------------------- forged completion --

def test_complete_rejects_a_checkpoint_that_was_never_verified_saved(grant, tmp_path):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(1)

    fake_checkpoint = tmp_path / "fake.pt"
    fake_checkpoint.write_bytes(b"not a real checkpoint, no manifest, nothing")
    with pytest.raises(ForgedCompletionError):
        run.complete(checkpoint_path=fake_checkpoint)
    assert run.state is RunState.RUNNING  # a forged completion attempt never transitions the run


def test_complete_rejects_a_real_checkpoint_whose_step_does_not_match_recorded_execution(grant, tmp_path):
    """A genuinely valid, hash-verified checkpoint -- just not the right
    one for THIS run's actual recorded progress."""
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(5)

    mismatched_checkpoint = _real_checkpoint(tmp_path, step=1)
    with pytest.raises(ForgedCompletionError):
        run.complete(checkpoint_path=mismatched_checkpoint)
    assert run.state is RunState.RUNNING


def test_complete_rejects_a_run_with_no_recorded_execution_evidence(grant, tmp_path):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    # No record_step() call at all -- nothing was ever actually run.
    with pytest.raises(ForgedCompletionError):
        run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert run.state is RunState.RUNNING


# --------------------------------------------------------- unauthorized restart --

def test_cannot_call_start_twice(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    with pytest.raises(InvalidTransitionError):
        run.start()


def test_cannot_authorize_an_already_authorized_run_again(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    assert run.state is RunState.AUTHORIZED

    with pytest.raises(InvalidTransitionError):
        run.authorize(grant)


# ---------------------------------------------------- identity & evidence separation --

def test_record_step_is_rejected_outside_running():
    run = _run()
    with pytest.raises(InvalidTransitionError):
        run.record_step(1)


def test_record_step_requires_strictly_increasing_steps(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(5)
    with pytest.raises(ValueError):
        run.record_step(5)
    with pytest.raises(ValueError):
        run.record_step(3)


def test_evaluator_approval_requires_completion_first(grant):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(1)
    with pytest.raises(InvalidTransitionError):
        run.record_evaluator_approval(
            evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256="0" * 64,
        )


def test_evaluator_approval_is_a_distinct_field_from_authorization_and_completion(grant, tmp_path):
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    run.authorize(grant)
    run.start()
    run.record_step(1)
    run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert run.evaluator_approval is None  # not recorded yet, despite being COMPLETED and AUTHORIZED
    run.record_evaluator_approval(evaluator_identity="eval-harness-v1", approved=False, evaluation_report_sha256="1" * 64)
    assert run.evaluator_approval.approved is False
    # Authorization and completion remain unaffected by an evaluator's negative verdict.
    assert run.state is RunState.COMPLETED
    assert run.grant is not None and run.completion is not None
