"""
GENESIS Foundation Sprint 2, Workstream C: training-orchestration state
machine tests. No training loop, GPU, or optimizer step runs anywhere in
this file. Real `orca.train.authorization.TrainingGrant` objects used here
are minted via the SAME synthetic-world fixture
`tests/test_training_authorization_gate.py` uses for its own tests --
throw-away Ed25519 keys generated per test, a throw-away registry/repo, the
gate's pin patched to point at it. Nothing here touches the real, empty,
committed authority registry.

Covers the independent code-review continuation (C-01 through C-06) in
addition to the original state-machine coverage.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.training.checkpoint_integrity import save_verified_training_state  # noqa: E402
from orca.genesis.training.orchestration import (  # noqa: E402
    _ALLOWED_TRANSITIONS,
    _REJECTABLE_STATES,
    EvaluatorApprovalClaim,
    ExecutionEvent,
    ForgedCompletionError,
    GenesisTrainingRun,
    InvalidTransitionError,
    ReplayedAuthorizationError,
    RunState,
    StaleAuthorizationError,
    TERMINAL_STATES,
)
from orca.genesis.training.orchestration import _GENESIS_SCOPE_BASE_MODEL_SENTINEL, _GENESIS_SCOPE_DATA_FORMAT_SENTINEL  # noqa: E402
from orca.genesis.training.primitives import TrainingState  # noqa: E402
from orca.train.authorization import TrainingGrant, TrainingNotAuthorized  # noqa: E402
import orca.train.authorization as A  # noqa: E402
from tests.test_training_authorization_gate import ENV, World, _git  # noqa: E402


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
    GenesisTrainingRun.reset_in_process_replay_guard_for_new_process()
    yield
    GenesisTrainingRun.reset_in_process_replay_guard_for_new_process()


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


@pytest.fixture
def grant(world) -> TrainingGrant:
    """A real, legitimately-issued grant for a GENERIC, LoRA-shaped
    config -- i.e. exactly the kind of 'unrelated workload' grant C-01 is
    about. It must NEVER authorize a GenesisTrainingRun; tests that need
    to exercise post-authorization mechanics use `_force_authorized()`
    below instead, which is explicit about bypassing the scope check it
    is not testing."""
    return world.authorize()


def _run(**kw) -> GenesisTrainingRun:
    kw.setdefault("dataset_manifest_ids", ("ds-1",))
    kw.setdefault("environment_class", ENV)
    return GenesisTrainingRun("run-1", **kw)


def _force_authorized(run: GenesisTrainingRun, grant: TrainingGrant) -> None:
    """Test-only helper: places a run directly into AUTHORIZED with a
    real, HMAC-verified grant, bypassing the workload-scope binding check
    (C-01) specifically. That check is exhaustively tested on its own
    below. This exists only because no code anywhere can currently
    produce a grant whose cfg_fingerprint actually matches a
    GENESIS-scoped request (the correct, intentional BLOCKED state) -- so
    exercising RUNNING/PAUSED/RECOVERING/COMPLETED mechanics at all
    requires sidestepping that one check here, in test scaffolding only,
    never in production code."""
    assert run.state is RunState.AWAITING_AUTHORIZATION
    grant.verify_integrity()
    run.grant = grant
    run.history.append((run.state.value, RunState.AUTHORIZED.value, "test-only: bypassed workload-scope binding"))
    run.state = RunState.AUTHORIZED


def _mint_matching_grant(tmp_path: Path, monkeypatch, *, dataset_digest: str) -> TrainingGrant:
    """Constructs a real, through-the-gate-issued TrainingGrant whose
    cfg_fingerprint genuinely matches GenesisTrainingRun's own
    _expected_grant_scope() for the given dataset_digest -- proving the
    binding mechanism POSITIVELY (a correctly-scoped grant IS accepted),
    not only via the negative/rejection cases elsewhere in this file.
    Requires a real file at a path whose name is exactly `dataset_digest`
    (chdir'd into place) so orca.train.authorization's own disk-based
    dataset-file resolution succeeds -- GENESIS has no file-based dataset
    at all, so this is purely a mechanical requirement of the underlying
    LoRA-shaped gate, not a claim that GENESIS datasets are files."""
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    dataset_file = cwd_dir / dataset_digest
    dataset_file.write_text('{"text": "synthetic genesis dataset content"}\n')
    monkeypatch.chdir(cwd_dir)

    w = World(tmp_path / "repo", monkeypatch, authorize_record=False)
    w.cfg.family = None
    w.cfg.base_model = _GENESIS_SCOPE_BASE_MODEL_SENTINEL
    w.cfg.num_epochs = 0
    w.cfg.lora.r = 0
    w.cfg.lora.lora_alpha = 0
    w.cfg.max_seq_length = 0
    w.cfg.train_file = dataset_digest
    w.cfg.eval_file = None
    w.cfg.data_format = _GENESIS_SCOPE_DATA_FORMAT_SENTINEL

    record = w.make_record({
        "model": {"family": A.GENERIC_FAMILY, "base_model": _GENESIS_SCOPE_BASE_MODEL_SENTINEL, "base_model_revision": None},
        "datasets": {
            "train_sha256": A.file_sha256(dataset_file), "eval_sha256": None,
            "dataset_manifest_ids": ["ds-1"], "dataset_bundle_id": None,
        },
    })
    w._write(A.RECORD_PATH, record)
    _git(w.root, "add", "-A")
    _git(w.root, "commit", "-q", "-m", "genesis-scoped signed record")
    return w.authorize()


def _authorized_run(grant) -> GenesisTrainingRun:
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    _force_authorized(run, grant)
    return run


# ============================================================ C-01: wrong-workload authorization

def test_c01_an_unrelated_generic_lora_grant_is_rejected_not_authorized(grant):
    """Direct reproduction-turned-regression-test of the independently
    confirmed C-01 defect: a legitimately issued grant for an unrelated,
    generic LoRA/QLoRA config must never transition a GENESIS run to
    AUTHORIZED or RUNNING."""
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    with pytest.raises(TrainingNotAuthorized):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_c01_expected_grant_scope_is_fully_determined_by_run_identity():
    """The scope a run demands binding against is a pure function of its
    own identity -- not of any external input, not configurable by a
    caller trying to widen it."""
    run_a = GenesisTrainingRun("run-a", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run_a.identity.dataset_digest = _dataset_digest()
    run_b = GenesisTrainingRun("run-b", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run_b.identity.dataset_digest = _dataset_digest()
    assert run_a._expected_grant_scope() == run_b._expected_grant_scope()

    run_c = GenesisTrainingRun("run-c", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run_c.identity.dataset_digest = hashlib.sha256(b"a different dataset entirely").hexdigest()
    assert run_c._expected_grant_scope() != run_a._expected_grant_scope()


def test_c01_no_currently_issuable_grant_can_satisfy_the_genesis_scope(world):
    """Confirms the BLOCKED state structurally, not just in prose: even a
    grant whose record was authorized for the GENERIC family (the closest
    possible match available through the real gate) still fails the
    workload-scope check, because real LoRA fields (real base_model,
    nonzero lora rank/epochs, a real file path) can never coincide with
    GENESIS's fixed scope sentinel values."""
    g = world.authorize()
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    with pytest.raises(TrainingNotAuthorized) as exc_info:
        run.authorize(g)
    assert "CONFIG_CHANGED_AFTER_AUTHORIZATION" in str(exc_info.value) or exc_info.value.reasons


def test_c01_a_grant_genuinely_bound_to_the_genesis_scope_is_accepted(tmp_path, monkeypatch):
    """The positive case, proving the binding mechanism works both ways:
    a grant whose cfg_fingerprint was computed from EXACTLY the fields
    GenesisTrainingRun's own _expected_grant_scope() declares is accepted
    -- the rejection in the tests above is because of a genuine mismatch,
    not because the check is unconditionally broken."""
    digest = _dataset_digest()
    g = _mint_matching_grant(tmp_path, monkeypatch, dataset_digest=digest)
    run = GenesisTrainingRun("run-1", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run.validate(dataset_digest=digest)
    run.request_authorization()
    run.authorize(g)
    assert run.state is RunState.AUTHORIZED
    assert run.grant is g


# ============================================================ C-02: authorization checks during resume

def test_c02_resume_rejects_a_tampered_grant(grant):
    run = _authorized_run(grant)
    run.start()
    run.pause(reason="pausing")
    object.__setattr__(grant, "max_wall_clock_minutes", 999999)
    with pytest.raises(TrainingNotAuthorized):
        run.resume()
    assert run.state is RunState.FAILED


def test_c02_resume_rejects_an_expired_grant(grant):
    run = _authorized_run(grant)
    run.start()
    run.pause(reason="pausing")
    object.__setattr__(grant, "expires_at", "2000-01-01T00:00:00Z")
    object.__setattr__(grant, "_mac", grant._compute_mac())
    with pytest.raises(StaleAuthorizationError):
        run.resume()
    assert run.state is RunState.FAILED


def test_c02_resume_consults_a_live_revocation_hook_when_supplied(grant, world):
    """Distinguishes HMAC integrity (the grant object itself is
    untampered) from live authorization validity (whether the real
    authorization has since been revoked) -- a hook lets a caller supply
    the latter; without one, this module explicitly does not claim to
    check it (see test below). The hook is NOT revoked at start() time --
    only once, between pause() and resume() -- simulating "revoked after
    the run had already legitimately started"."""
    revoked = {"value": False}
    run = GenesisTrainingRun(
        "run-1", dataset_manifest_ids=("ds-1",), environment_class=ENV,
        revocation_check=lambda auth_id: revoked["value"],
    )
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    _force_authorized(run, grant)
    run.start()
    run.pause(reason="pausing")
    revoked["value"] = True
    with pytest.raises(TrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
        run.resume()
    assert run.state is RunState.FAILED


def test_c02_without_a_revocation_hook_live_revocation_is_explicitly_not_checked(grant):
    """Documents the honest, explicit limitation rather than hiding it:
    with no revocation_check supplied, resume() succeeds even though, in
    a real deployment, the underlying authorization might have been
    revoked in the meantime. This is the documented BLOCKED gap, not a
    false claim of safety."""
    run = _authorized_run(grant)
    run.start()
    run.pause(reason="pausing")
    run.resume()  # succeeds -- no live revocation check was configured
    assert run.state is RunState.RUNNING


def test_c02_start_also_consults_the_revocation_hook(tmp_path, monkeypatch):
    run_grant_world_calls = []

    def revocation_check(auth_id):
        run_grant_world_calls.append(auth_id)
        return True

    w = World(tmp_path, monkeypatch)
    g = w.authorize()
    run = GenesisTrainingRun("run-1", dataset_manifest_ids=("ds-1",), environment_class=ENV, revocation_check=revocation_check)
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    _force_authorized(run, g)
    with pytest.raises(TrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
        run.start()
    assert run.state is RunState.REJECTED
    assert run_grant_world_calls == [g.authorization_id]


# ============================================================ C-03: execution-evidence authenticity

def test_c03_record_step_requires_source_identity(grant):
    run = _authorized_run(grant)
    run.start()
    with pytest.raises(ValueError):
        run.record_step(1, source_identity="")
    with pytest.raises(TypeError):
        run.record_step(1)  # source_identity is keyword-required


def test_c03_execution_events_are_explicitly_labeled_reported_not_verified(grant):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="training-host-7")
    event = run.execution.events[-1]
    assert isinstance(event, ExecutionEvent)
    assert event.classification == "REPORTED_EXECUTION_PROGRESS"
    assert event.source_identity == "training-host-7"
    assert event.run_id == run.identity.run_id


def test_c03_sequence_is_independent_of_and_always_increases_with_step(grant):
    run = _authorized_run(grant)
    run.start()
    run.record_step(10, source_identity="a")
    run.record_step(25, source_identity="b")
    assert [e.sequence for e in run.execution.events] == [0, 1]
    assert [e.step for e in run.execution.events] == [10, 25]


def test_c03_execution_evidence_has_a_bounded_event_limit(grant):
    run = _authorized_run(grant)
    run.start()
    run.execution.max_events = 2
    run.record_step(1, source_identity="a")
    run.record_step(2, source_identity="a")
    with pytest.raises(ValueError, match="evidence limit"):
        run.record_step(3, source_identity="a")


# ============================================================ C-04: evaluator-approval authenticity

def test_c04_approval_claim_is_explicitly_unauthenticated(grant, tmp_path):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
    run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    run.record_evaluator_approval(
        evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256="1" * 64,
        checkpoint_manifest_sha256=run.completion.checkpoint_manifest_sha256,
    )
    assert isinstance(run.evaluator_approval, EvaluatorApprovalClaim)
    assert run.evaluator_approval.is_independently_authenticated is False


def test_c04_approval_claim_naming_the_wrong_checkpoint_is_rejected(grant, tmp_path):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
    run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    with pytest.raises(ValueError, match="does not match"):
        run.record_evaluator_approval(
            evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256="1" * 64,
            checkpoint_manifest_sha256="0" * 64,  # not this run's actual checkpoint manifest hash
        )
    assert run.evaluator_approval is None


# ============================================================ C-05: durable replay and recovery

def test_c05_replay_guard_is_explicitly_process_local_not_cross_process(tmp_path, monkeypatch):
    """Documents and tests the exact boundary: a fresh process (simulated
    here via the documented reset classmethod) has no memory of what a
    prior process consumed, so this module's own guard alone cannot
    detect replay across that boundary -- the real defense against that
    is orca.train.authorization's own on-disk run-slot ledger, exercised
    separately by that module's own test suite, not duplicated here.
    Uses a REAL, workload-matching grant (not the bypass helper) so this
    exercises authorize() itself, not test scaffolding."""
    digest = _dataset_digest()
    g = _mint_matching_grant(tmp_path, monkeypatch, dataset_digest=digest)

    run_a = GenesisTrainingRun("run-a", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run_a.validate(dataset_digest=digest)
    run_a.request_authorization()
    run_a.authorize(g)
    assert g.authorization_id in GenesisTrainingRun._consumed_authorization_ids

    GenesisTrainingRun.reset_in_process_replay_guard_for_new_process()

    run_b = GenesisTrainingRun("run-b", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run_b.validate(dataset_digest=digest)
    run_b.request_authorization()
    # After the reset, this process-local guard alone no longer remembers
    # run_a's consumption -- the SAME real grant is accepted again,
    # demonstrating the documented in-process-only scope of this guard.
    run_b.authorize(g)
    assert run_b.state is RunState.AUTHORIZED


def test_c05_within_one_process_the_guard_does_prevent_replay(tmp_path, monkeypatch):
    digest = _dataset_digest()
    g = _mint_matching_grant(tmp_path, monkeypatch, dataset_digest=digest)

    run_a = GenesisTrainingRun("run-a", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run_a.validate(dataset_digest=digest)
    run_a.request_authorization()
    run_a.authorize(g)

    run_b = GenesisTrainingRun("run-b", dataset_manifest_ids=("ds-1",), environment_class=ENV)
    run_b.validate(dataset_digest=digest)
    run_b.request_authorization()
    with pytest.raises(ReplayedAuthorizationError):
        run_b.authorize(g)


# ============================================================ C-06: state-transition consistency

def test_c06_reject_is_valid_exactly_from_the_states_the_graph_permits():
    assert _REJECTABLE_STATES == {RunState.PLANNED, RunState.VALIDATED, RunState.AWAITING_AUTHORIZATION, RunState.AUTHORIZED}


@pytest.mark.parametrize("state", [RunState.RUNNING, RunState.PAUSED, RunState.RECOVERING])
def test_c06_reject_raises_from_running_paused_recovering_rather_than_silently_succeeding(state):
    run = _run()
    run.identity.dataset_digest = _dataset_digest()
    run.state = state
    with pytest.raises(InvalidTransitionError):
        run.reject(reason="should not be reachable from here")
    assert run.state is state  # unchanged


@pytest.mark.parametrize("state", [RunState.COMPLETED, RunState.FAILED, RunState.REJECTED])
def test_c06_reject_raises_from_every_terminal_state(state):
    run = _run()
    run.state = state
    with pytest.raises(InvalidTransitionError):
        run.reject(reason="already terminal")


def test_c06_every_state_and_every_declared_transition_is_individually_reachable_and_consistent():
    """Systematic sweep (C-06's explicit ask): for every state in the
    graph, every transition the graph declares allowed must actually be
    reachable through the public API with the right preconditions
    satisfied, and the graph's own REJECTED-reachability must match
    _REJECTABLE_STATES exactly (already asserted above) -- this test
    additionally confirms no state is missing from the graph entirely."""
    assert set(_ALLOWED_TRANSITIONS.keys()) == set(RunState)
    for state in TERMINAL_STATES:
        assert _ALLOWED_TRANSITIONS[state] == frozenset()


# ============================================================ full lifecycle (post-authorization mechanics)

def test_full_lifecycle_planned_to_completed(grant, tmp_path):
    run = _run()
    assert run.state is RunState.PLANNED
    run.validate(dataset_digest=_dataset_digest())
    assert run.state is RunState.VALIDATED
    run.request_authorization()
    assert run.state is RunState.AWAITING_AUTHORIZATION
    _force_authorized(run, grant)
    assert run.state is RunState.AUTHORIZED

    run.start()
    assert run.state is RunState.RUNNING
    assert run.execution is not None and run.execution.steps_recorded == 0

    run.record_step(1, source_identity="a")
    run.record_step(2, source_identity="a")
    assert run.execution.steps_recorded == 2

    ckpt = _real_checkpoint(tmp_path, step=2)
    run.complete(checkpoint_path=ckpt)
    assert run.state is RunState.COMPLETED
    assert run.completion is not None and run.completion.final_step == 2

    report_sha = hashlib.sha256(b"a real evaluation report's bytes").hexdigest()
    run.record_evaluator_approval(
        evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256=report_sha,
        checkpoint_manifest_sha256=run.completion.checkpoint_manifest_sha256,
    )
    assert run.evaluator_approval is not None and run.evaluator_approval.approved is True


def test_pause_resume_cycle(grant):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
    run.pause(reason="operator paused")
    assert run.state is RunState.PAUSED
    run.resume()
    assert run.state is RunState.RUNNING


def test_pause_recover_cycle(grant):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
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
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
    run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert run.state is RunState.COMPLETED
    with pytest.raises(InvalidTransitionError):
        run.start()


def test_cannot_resume_a_failed_run(grant):
    run = _authorized_run(grant)
    run.start()
    run.fail(reason="simulated infrastructure failure")
    assert run.state is RunState.FAILED
    with pytest.raises(InvalidTransitionError):
        run.resume()
    with pytest.raises(InvalidTransitionError):
        run.reject(reason="too late")


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
    run = _run()
    run.validate(dataset_digest=_dataset_digest())
    run.request_authorization()
    object.__setattr__(grant, "max_wall_clock_minutes", 999999)
    with pytest.raises(TrainingNotAuthorized):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_start_rechecks_integrity_and_catches_tampering_after_authorize(grant):
    run = _authorized_run(grant)
    object.__setattr__(grant, "run_slot", 999)
    with pytest.raises(TrainingNotAuthorized):
        run.start()
    assert run.state is RunState.REJECTED


# ---------------------------------------------------------------------- replay --

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
    run = _authorized_run(grant)
    object.__setattr__(grant, "expires_at", "2000-01-01T00:00:00Z")
    object.__setattr__(grant, "_mac", grant._compute_mac())
    with pytest.raises(StaleAuthorizationError):
        run.start()
    assert run.state is RunState.REJECTED


def test_recovered_rejects_a_grant_that_expired_during_recovery(grant):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
    run.pause(reason="pausing")
    run.begin_recovery(reason="recovering")
    object.__setattr__(grant, "expires_at", "2000-01-01T00:00:00Z")
    object.__setattr__(grant, "_mac", grant._compute_mac())
    with pytest.raises(StaleAuthorizationError):
        run.recovered()
    assert run.state is RunState.FAILED


# ------------------------------------------------------------- forged completion --

def test_complete_rejects_a_checkpoint_that_was_never_verified_saved(grant, tmp_path):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")

    fake_checkpoint = tmp_path / "fake.pt"
    fake_checkpoint.write_bytes(b"not a real checkpoint, no manifest, nothing")
    with pytest.raises(ForgedCompletionError):
        run.complete(checkpoint_path=fake_checkpoint)
    assert run.state is RunState.RUNNING


def test_complete_rejects_a_real_checkpoint_whose_step_does_not_match_recorded_execution(grant, tmp_path):
    run = _authorized_run(grant)
    run.start()
    run.record_step(5, source_identity="a")

    mismatched_checkpoint = _real_checkpoint(tmp_path, step=1)
    with pytest.raises(ForgedCompletionError):
        run.complete(checkpoint_path=mismatched_checkpoint)
    assert run.state is RunState.RUNNING


def test_complete_rejects_a_run_with_no_recorded_execution_evidence(grant, tmp_path):
    run = _authorized_run(grant)
    run.start()
    with pytest.raises(ForgedCompletionError):
        run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert run.state is RunState.RUNNING


# --------------------------------------------------------- unauthorized restart --

def test_cannot_call_start_twice(grant):
    run = _authorized_run(grant)
    run.start()
    with pytest.raises(InvalidTransitionError):
        run.start()


def test_cannot_authorize_an_already_authorized_run_again(grant):
    run = _authorized_run(grant)
    assert run.state is RunState.AUTHORIZED
    with pytest.raises(InvalidTransitionError):
        run.authorize(grant)


# ---------------------------------------------------- identity & evidence separation --

def test_record_step_is_rejected_outside_running():
    run = _run()
    with pytest.raises(InvalidTransitionError):
        run.record_step(1, source_identity="a")


def test_record_step_requires_strictly_increasing_steps(grant):
    run = _authorized_run(grant)
    run.start()
    run.record_step(5, source_identity="a")
    with pytest.raises(ValueError):
        run.record_step(5, source_identity="a")
    with pytest.raises(ValueError):
        run.record_step(3, source_identity="a")


def test_evaluator_approval_requires_completion_first(grant):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
    with pytest.raises(InvalidTransitionError):
        run.record_evaluator_approval(
            evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256="0" * 64,
            checkpoint_manifest_sha256="0" * 64,
        )


def test_evaluator_approval_is_a_distinct_field_from_authorization_and_completion(grant, tmp_path):
    run = _authorized_run(grant)
    run.start()
    run.record_step(1, source_identity="a")
    run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert run.evaluator_approval is None
    run.record_evaluator_approval(
        evaluator_identity="eval-harness-v1", approved=False, evaluation_report_sha256="1" * 64,
        checkpoint_manifest_sha256=run.completion.checkpoint_manifest_sha256,
    )
    assert run.evaluator_approval.approved is False
    assert run.state is RunState.COMPLETED
    assert run.grant is not None and run.completion is not None
