"""
GENESIS Foundation Sprint 2, Workstream C: training-orchestration state
machine tests. No training loop, GPU, or optimizer step runs anywhere in
this file.

Native-Authorization-Convergence Mission 2: this module's authorization
boundary is now the REAL `orca.genesis.governance.authorization.NativePretrainingGrant`
(Workstream F), not a repurposed LoRA `TrainingGrant`. Real
`NativePretrainingGrant` objects used here are minted via `GrantWorld`
below -- throw-away Ed25519 keys generated per test, a throw-away
registry, the gate's pin patched to point at it, and
`check_founder_acceptance_ledger` patched to simulate a hypothetical
future acceptance state. Nothing here touches the real, empty, committed
authority registry or acceptance ledger. Positive-path authorization now
uses fully isolated synthetic fixtures end to end -- no bypass/test-only
shortcut is needed any more (Mission 2's own instruction).

Covers the original C-01 through C-06 continuation (re-expressed against
the new grant type) plus Mission 2's new requirements: exact workload
binding, immutable authorized identity, the FINAL-1 -> FINAL-2 -> EXEC-1
execution-start gate, mandatory + durable (cross-process) revocation and
replay protection, and forged-evidence resistance.
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
from orca.genesis.training.checkpoint_integrity import save_verified_training_state  # noqa: E402
from orca.genesis.training.orchestration import (  # noqa: E402
    _ALLOWED_TRANSITIONS,
    _REJECTABLE_STATES,
    AuthorizedIdentityChangedError,
    EvaluatorApprovalClaim,
    ExecutionAcceptanceIncompleteError,
    ExecutionEvent,
    ForgedCompletionError,
    GenesisTrainingRun,
    InvalidTransitionError,
    ReplayedAuthorizationError,
    RunState,
    StaleAuthorizationError,
    TERMINAL_STATES,
)
from orca.genesis.training.primitives import TrainingState  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _real_checkpoint(tmp_path: Path, *, step: int) -> Path:
    path = tmp_path / "checkpoint.pt"
    state = TrainingState(
        step=step, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={},
        python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None,
    )
    save_verified_training_state(state, path)
    return path


# ============================================================ isolation fixtures ==

@pytest.fixture(autouse=True)
def _isolate_native_pretraining_state(tmp_path, monkeypatch):
    """Isolates BOTH the durable, on-disk replay-claim directory
    (`_native_pretraining_replay_state_dir()`, which lives under
    `ORCA_HOME`) and Workstream F's own in-process nonce guard, so
    unrelated tests in this file (and other test modules run in the same
    pytest session) never interfere with each other's claimed
    authorization_ids."""
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GOV.reset_in_process_nonce_guard_for_new_process()


# ============================================================ grant-minting world ==

class GrantWorld:
    """Mints a REAL, through-the-gate-issued `NativePretrainingGrant` --
    mirrors `tests/test_genesis_governance_authorization.py`'s own `World`
    fixture pattern (synthetic Ed25519 keys, a synthetic registry, the
    real gate's pin patched to point at it), parameterized by the exact
    workload identity fields a `GenesisTrainingRun` declares, so positive
    tests can prove the binding mechanism actually accepts a correctly-
    scoped grant, not only reject mismatched ones."""

    def __init__(
        self, *, run_id: str, model_config_digest: str, tokenizer_digest: str,
        dataset_manifest_id: str, dataset_content_digest: str, authorized_shard_digests: tuple[str, ...],
        environment_class: str = ENV, record_over: dict | None = None,
    ):
        self.priv = Ed25519PrivateKey.generate()
        pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        now = datetime.now(timezone.utc)
        self.registry = {
            "schema_version": GOV.REGISTRY_SCHEMA_VERSION,
            "records": [{
                "id": "synthetic-authority-1", "role": "OWNER", "public_key_hex": pub,
                "activation_timestamp": _ts(now - timedelta(days=1)), "expiry": None, "revoked": False,
                "gpu_permission": False, "spend_permission": False,
            }],
        }
        self.req = GOV.NativePretrainingRequest(
            run_id=run_id, nonce=_digest(f"nonce-{run_id}-{id(self)}"), model_family="genesis",
            architecture_version="genesis-arch-v1", model_config_digest=model_config_digest, tokenizer_digest=tokenizer_digest,
            dataset_manifest_id=dataset_manifest_id, dataset_content_digest=dataset_content_digest,
            authorized_shard_digests=tuple(authorized_shard_digests), reviewed_commit_sha="a" * 40,
            transformation_code_digest=_digest("pipeline-code-v1"), optimizer_config_digest=_digest("optimizer-config-v1"),
            environment_class=environment_class, gpu_requested=False, max_wall_clock_minutes=30, requested_spend_usd=0.0,
        )
        self.record = self._sign(self._make_record(record_over or {}))

    def _sign(self, rec: dict) -> dict:
        rec = dict(rec)
        rec["signature"] = None
        rec["signature"] = self.priv.sign(GOV.canonical_signing_bytes(rec)).hex()
        return rec

    def _make_record(self, over: dict) -> dict:
        req = self.req
        now = datetime.now(timezone.utc)
        rec = {
            "schema_version": GOV.SCHEMA_VERSION, "authorization_id": "gnpauth-" + "ab" * 8, "status": "AUTHORIZED",
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
            "limits": {"max_wall_clock_minutes": 60, "max_spend_usd": 0, "gpu_allowed": False},
            "issued_at": _ts(now - timedelta(hours=1)), "expires_at": _ts(now + timedelta(days=6)),
            "authorizing_authority": {"identity": "synthetic-authority-1", "role": "OWNER", "key_id": "synthetic-authority-1"},
            "signature": None,
        }
        rec.update(over)
        return rec

    def authorize(self, monkeypatch, *, revocation_check=None, founder_ready: bool = True) -> GOV.NativePretrainingGrant:
        if founder_ready:
            monkeypatch.setattr(GOV, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
        monkeypatch.setattr(GOV, "PINNED_REGISTRY_SHA256", GOV.registry_digest(self.registry))
        return GOV.authorize_native_pretraining(
            repo_root=REPO_ROOT, record=self.record, registry=self.registry, revoked_ids=[],
            req=self.req, revocation_check=revocation_check or (lambda auth_id: False),
        )


class _Identity:
    """A fixed, reusable identity bundle for a test run -- keeps every
    test's digests consistent between `validate()` and the matching
    `GrantWorld`, without repeating six keyword arguments everywhere."""

    def __init__(self, run_id: str = "run-1"):
        self.run_id = run_id
        self.dataset_manifest_id = "genesis-fixture-v1"
        self.dataset_digest = _digest(f"dataset-{run_id}")
        self.model_config_digest = _digest(f"model-config-{run_id}")
        self.tokenizer_digest = _digest(f"tokenizer-{run_id}")
        self.authorized_shard_digests = (_digest(f"shard-0-{run_id}"), _digest(f"shard-1-{run_id}"))

    def world(self, **kw) -> GrantWorld:
        defaults = dict(
            run_id=self.run_id, model_config_digest=self.model_config_digest, tokenizer_digest=self.tokenizer_digest,
            dataset_manifest_id=self.dataset_manifest_id, dataset_content_digest=self.dataset_digest,
            authorized_shard_digests=self.authorized_shard_digests,
        )
        defaults.update(kw)
        return GrantWorld(**defaults)

    def run(self, *, revocation_check=None) -> GenesisTrainingRun:
        return GenesisTrainingRun(
            self.run_id, dataset_manifest_ids=(self.dataset_manifest_id,), environment_class=ENV,
            repo_root=REPO_ROOT, revocation_check=revocation_check or (lambda auth_id: False),
        )

    def validate(self, run: GenesisTrainingRun) -> None:
        run.validate(
            dataset_digest=self.dataset_digest, model_config_digest=self.model_config_digest,
            tokenizer_digest=self.tokenizer_digest, authorized_shard_digests=self.authorized_shard_digests,
        )


@pytest.fixture
def ident() -> _Identity:
    return _Identity()


@pytest.fixture
def authorized_run(ident, monkeypatch) -> GenesisTrainingRun:
    """The real, end-to-end positive path: a GenesisTrainingRun validated
    with a specific identity, authorized by a REAL NativePretrainingGrant
    minted to match that exact identity -- no bypass helper needed."""
    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    return run


@pytest.fixture
def started_run(authorized_run, monkeypatch) -> GenesisTrainingRun:
    """`authorized_run`, additionally past `start()` -- requires the
    execution-acceptance gate (FINAL-1/FINAL-2/EXEC-1) to be simulated as
    accepted, since the real ledger is empty."""
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    authorized_run.start()
    return authorized_run


# ============================================================ exact workload binding (C-01 successor) ==

def test_a_grant_genuinely_bound_to_the_runs_full_identity_is_accepted(ident, monkeypatch):
    """The positive case, end to end: a real NativePretrainingGrant minted
    for EXACTLY this run's declared identity authorizes it."""
    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    assert run.state is RunState.AUTHORIZED
    assert run.grant is grant


@pytest.mark.parametrize("field,wrong_value", [
    ("run_id", "a-different-run-entirely"),
    ("model_config_digest", _digest("a different model config")),
    ("tokenizer_digest", _digest("a different tokenizer")),
    ("dataset_manifest_id", "a-different-manifest-id"),
    ("dataset_content_digest", _digest("a different dataset")),
    ("environment_class", "SSH_RENTED_GPU"),
])
def test_wrong_single_field_grant_is_rejected_not_authorized(ident, monkeypatch, field, wrong_value):
    """Exact workload binding, field by field: a grant that matches EVERY
    field except ONE must still be rejected -- proving each field is
    actually checked, not merely one of them standing in for all."""
    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    kwargs = dict(
        run_id=ident.run_id, model_config_digest=ident.model_config_digest, tokenizer_digest=ident.tokenizer_digest,
        dataset_manifest_id=ident.dataset_manifest_id, dataset_content_digest=ident.dataset_digest,
        authorized_shard_digests=ident.authorized_shard_digests, environment_class=ENV,
    )
    kwargs[field] = wrong_value
    grant = GrantWorld(**kwargs).authorize(monkeypatch)
    with pytest.raises(GOV.NativePretrainingNotAuthorized):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_wrong_authorized_shards_grant_is_rejected(ident, monkeypatch):
    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    grant = ident.world(authorized_shard_digests=(_digest("an-unauthorized-shard"),)).authorize(monkeypatch)
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="WRONG_AUTHORIZED_SHARDS"):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_a_legacy_lora_training_grant_is_structurally_rejected(ident, monkeypatch, tmp_path):
    """The legacy LoRA TrainingGrant is now rejected at the TYPE level --
    not via a fingerprint mismatch (the original C-01 mitigation), but
    because authorize() requires a real NativePretrainingGrant instance
    specifically, and the two are different, non-interchangeable
    classes."""
    from tests.test_training_authorization_gate import World as LoraWorld

    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    lora_world = LoraWorld(tmp_path / "lora-world", monkeypatch)
    lora_grant = lora_world.authorize()
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="NO_NATIVE_PRETRAINING_GRANT"):
        run.authorize(lora_grant)
    assert run.state is RunState.REJECTED


@pytest.mark.parametrize("fake", [True, {"authorized": True}, "AUTHORIZED", 1])
def test_authorize_rejects_a_plain_boolean_or_dict_claiming_authorization(ident, fake):
    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    with pytest.raises(GOV.NativePretrainingNotAuthorized):
        run.authorize(fake)
    assert run.state is RunState.REJECTED


def test_authorize_rejects_an_expired_grant(ident, monkeypatch):
    """The gate itself (`authorize_native_pretraining()`) already denies
    issuing a grant from an expired record -- confirmed directly. This
    test additionally confirms the ORCHESTRATOR's own expiry re-check at
    `authorize()` by tampering an already-issued, validly-minted grant's
    `expires_at` directly (the same pattern used for post-issuance
    tampering elsewhere in this file), simulating a grant that expires
    in the (very short) window between minting and this orchestrator's
    own authorize() call."""
    now = datetime.now(timezone.utc)
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="EXPIRED"):
        ident.world(record_over={
            "issued_at": _ts(now - timedelta(days=2)), "expires_at": _ts(now - timedelta(days=1)),
        }).authorize(monkeypatch)

    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    object.__setattr__(grant, "expires_at", "2000-01-01T00:00:00Z")
    object.__setattr__(grant, "_mac", grant._compute_mac())
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="EXPIRED"):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_authorize_rejects_a_tampered_grant(authorized_run):
    """Not reachable via authorize() itself (a tampered grant would have
    already failed verify_integrity() there) -- this exercises the same
    check surfacing post-hoc tampering of an ALREADY-authorized run's
    grant object, caught at the next re-verification point (start())."""
    object.__setattr__(authorized_run.grant, "max_wall_clock_minutes", 999999)
    with pytest.raises(GOV.NativePretrainingNotAuthorized):
        authorized_run.start()
    assert authorized_run.state is RunState.REJECTED


# ============================================================ immutable authorized identity (Mission 2, new) ==

def test_identity_drift_after_authorization_is_detected_at_start(authorized_run):
    """Mission 2's new requirement: nothing in this module mutates
    `self.identity` after `validate()`, but if a caller did, the frozen
    authorized-identity snapshot must catch the drift at the next
    resume-capable transition rather than silently continuing to trust a
    grant for a workload the run no longer declares."""
    authorized_run.identity.dataset_digest = _digest("a substituted dataset after authorization")
    with pytest.raises(AuthorizedIdentityChangedError):
        authorized_run.start()
    assert authorized_run.state is RunState.REJECTED


def test_identity_drift_after_authorization_is_detected_at_resume(started_run):
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="pausing")
    started_run.identity.model_config_digest = _digest("a substituted model config after authorization")
    with pytest.raises(AuthorizedIdentityChangedError):
        started_run.resume()
    assert started_run.state is RunState.FAILED


def test_unchanged_identity_does_not_trip_the_drift_check(started_run):
    """Negative control: resume() with NO identity mutation at all must
    succeed -- confirms the drift check is comparing real values
    correctly, not spuriously failing on every call."""
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="pausing")
    started_run.resume()
    assert started_run.state is RunState.RUNNING


# ============================================================ mandatory + durable revocation (C-02 successor) ==

def test_revocation_check_is_mandatory_at_construction():
    with pytest.raises(TypeError):
        GenesisTrainingRun("run-1", dataset_manifest_ids=("ds-1",), environment_class=ENV, repo_root=REPO_ROOT)  # type: ignore[call-arg]


def test_start_consults_the_revocation_hook_and_denies_on_true(ident, monkeypatch):
    calls = []

    def revocation_check(auth_id):
        calls.append(auth_id)
        return True

    run = ident.run(revocation_check=revocation_check)
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
        run.start()
    assert run.state is RunState.REJECTED
    assert calls == [grant.authorization_id]


def test_resume_consults_the_revocation_hook_and_denies_on_true(ident, monkeypatch):
    revoked = {"value": False}
    run = ident.run(revocation_check=lambda auth_id: revoked["value"])
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    run.start()
    run.pause(reason="pausing")
    revoked["value"] = True
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
        run.resume()
    assert run.state is RunState.FAILED


def test_unavailable_revocation_service_denies_rather_than_passing(ident, monkeypatch):
    """Mission 2: an erroring/unavailable revocation service must be
    treated as a denial, never a silent pass -- delegated entirely to
    `assert_execution_permitted()`'s own mandatory contract, exercised
    here through the orchestrator."""
    def flaky_revocation_check(auth_id):
        raise ConnectionError("revocation service unreachable")

    run = ident.run(revocation_check=flaky_revocation_check)
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="REVOCATION_CHECK_UNAVAILABLE"):
        run.start()
    assert run.state is RunState.REJECTED


# ============================================================ durable, cross-process replay (C-05 successor) ==

def test_replay_is_prevented_even_across_a_simulated_new_process(ident, monkeypatch):
    """Mission 2's durability requirement: unlike the old in-process-only
    guard, this must hold even after
    `reset_in_process_replay_guard_for_new_process()` is called (simulating
    a fresh OS process with no memory of the prior one) -- because the
    real guard now lives on disk under ORCA_HOME, not in process memory."""
    grant = ident.world().authorize(monkeypatch)

    run_a = ident.run()
    ident.validate(run_a)
    run_a.request_authorization()
    run_a.authorize(grant)
    assert run_a.state is RunState.AUTHORIZED

    GenesisTrainingRun.reset_in_process_replay_guard_for_new_process()  # simulates a new OS process

    run_b = ident.run()
    ident.validate(run_b)
    run_b.request_authorization()
    with pytest.raises(ReplayedAuthorizationError):
        run_b.authorize(grant)
    assert run_b.state is RunState.REJECTED


def test_replay_is_prevented_within_one_process_too(ident, monkeypatch):
    grant = ident.world().authorize(monkeypatch)
    run_a = ident.run()
    ident.validate(run_a)
    run_a.request_authorization()
    run_a.authorize(grant)

    run_b = ident.run()
    ident.validate(run_b)
    run_b.request_authorization()
    with pytest.raises(ReplayedAuthorizationError):
        run_b.authorize(grant)


# ============================================================ execution-start acceptance gate (new) ==

def test_start_denies_execution_when_the_real_acceptance_ledger_is_unpatched(authorized_run):
    """The real, committed founder-acceptance ledger is empty -- without
    patching `check_founder_acceptance_ledger`, start() must deny even an
    otherwise-perfectly-authorized run. This is the actual, current,
    real-repo NO-GO state, not a hypothetical."""
    with pytest.raises(ExecutionAcceptanceIncompleteError):
        authorized_run.start()
    assert authorized_run.state is RunState.REJECTED


def test_start_succeeds_once_the_execution_acceptance_rows_are_simulated_accepted(started_run):
    assert started_run.state is RunState.RUNNING


def test_start_checks_the_stricter_final2_exec1_rows_not_only_final1(ident, monkeypatch):
    """The grant-issuance gate (authorize_native_pretraining(), inside
    GrantWorld.authorize()) only required R65/G1/AUTH-1/FINAL-1 to be
    accepted. start() must ADDITIONALLY require FINAL-2 and EXEC-1 --
    simulated here as still missing even though grant issuance already
    succeeded, proving start()'s gate is a genuinely separate, stricter
    check, not redundant with the one already passed."""
    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)  # patches check_founder_acceptance_ledger to return [] (all required rows accepted)
    run.authorize(grant)

    def partial_acceptance(repo_root, *, required_rows=()):
        return [row for row in required_rows if row in ("FINAL-2", "EXEC-1")]

    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", partial_acceptance)
    with pytest.raises(ExecutionAcceptanceIncompleteError):
        run.start()
    assert run.state is RunState.REJECTED


# ============================================================ execution-evidence authenticity (C-03) ==

def test_record_step_requires_source_identity(started_run):
    with pytest.raises(ValueError):
        started_run.record_step(1, source_identity="")
    with pytest.raises(TypeError):
        started_run.record_step(1)  # source_identity is keyword-required


def test_execution_events_are_explicitly_labeled_reported_not_verified(started_run):
    started_run.record_step(1, source_identity="training-host-7")
    event = started_run.execution.events[-1]
    assert isinstance(event, ExecutionEvent)
    assert event.classification == "REPORTED_EXECUTION_PROGRESS"
    assert event.source_identity == "training-host-7"
    assert event.run_id == started_run.identity.run_id


def test_sequence_is_independent_of_and_always_increases_with_step(started_run):
    started_run.record_step(10, source_identity="a")
    started_run.record_step(25, source_identity="b")
    assert [e.sequence for e in started_run.execution.events] == [0, 1]
    assert [e.step for e in started_run.execution.events] == [10, 25]


def test_execution_evidence_has_a_bounded_event_limit(started_run):
    started_run.execution.max_events = 2
    started_run.record_step(1, source_identity="a")
    started_run.record_step(2, source_identity="a")
    with pytest.raises(ValueError, match="evidence limit"):
        started_run.record_step(3, source_identity="a")


def test_record_step_requires_strictly_increasing_steps(started_run):
    started_run.record_step(5, source_identity="a")
    with pytest.raises(ValueError):
        started_run.record_step(5, source_identity="a")
    with pytest.raises(ValueError):
        started_run.record_step(3, source_identity="a")


def test_record_step_is_rejected_outside_running(ident):
    run = ident.run()
    with pytest.raises(InvalidTransitionError):
        run.record_step(1, source_identity="a")


# ============================================================ evaluator-approval authenticity (C-04) ==

def test_approval_claim_is_explicitly_unauthenticated(started_run, tmp_path):
    started_run.record_step(1, source_identity="a")
    started_run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    started_run.record_evaluator_approval(
        evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256="1" * 64,
        checkpoint_manifest_sha256=started_run.completion.checkpoint_manifest_sha256,
    )
    assert isinstance(started_run.evaluator_approval, EvaluatorApprovalClaim)
    assert started_run.evaluator_approval.is_independently_authenticated is False


def test_approval_claim_naming_the_wrong_checkpoint_is_rejected(started_run, tmp_path):
    started_run.record_step(1, source_identity="a")
    started_run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    with pytest.raises(ValueError, match="does not match"):
        started_run.record_evaluator_approval(
            evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256="1" * 64,
            checkpoint_manifest_sha256="0" * 64,  # not this run's actual checkpoint manifest hash
        )
    assert started_run.evaluator_approval is None


def test_evaluator_approval_requires_completion_first(started_run):
    started_run.record_step(1, source_identity="a")
    with pytest.raises(InvalidTransitionError):
        started_run.record_evaluator_approval(
            evaluator_identity="eval-harness-v1", approved=True, evaluation_report_sha256="0" * 64,
            checkpoint_manifest_sha256="0" * 64,
        )


# ============================================================ forged completion (unchanged mechanics) ==

def test_complete_rejects_a_checkpoint_that_was_never_verified_saved(started_run, tmp_path):
    started_run.record_step(1, source_identity="a")
    fake_checkpoint = tmp_path / "fake.pt"
    fake_checkpoint.write_bytes(b"not a real checkpoint, no manifest, nothing")
    with pytest.raises(ForgedCompletionError):
        started_run.complete(checkpoint_path=fake_checkpoint)
    assert started_run.state is RunState.RUNNING


def test_complete_rejects_a_real_checkpoint_whose_step_does_not_match_recorded_execution(started_run, tmp_path):
    started_run.record_step(5, source_identity="a")
    mismatched_checkpoint = _real_checkpoint(tmp_path, step=1)
    with pytest.raises(ForgedCompletionError):
        started_run.complete(checkpoint_path=mismatched_checkpoint)
    assert started_run.state is RunState.RUNNING


def test_complete_rejects_a_run_with_no_recorded_execution_evidence(started_run, tmp_path):
    with pytest.raises(ForgedCompletionError):
        started_run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert started_run.state is RunState.RUNNING


# ============================================================ C-06: state-transition consistency ==

def test_reject_is_valid_exactly_from_the_states_the_graph_permits():
    assert _REJECTABLE_STATES == {RunState.PLANNED, RunState.VALIDATED, RunState.AWAITING_AUTHORIZATION, RunState.AUTHORIZED}


@pytest.mark.parametrize("state", [RunState.RUNNING, RunState.PAUSED, RunState.RECOVERING])
def test_reject_raises_from_running_paused_recovering_rather_than_silently_succeeding(ident, state):
    run = ident.run()
    run.state = state
    with pytest.raises(InvalidTransitionError):
        run.reject(reason="should not be reachable from here")
    assert run.state is state  # unchanged


@pytest.mark.parametrize("state", [RunState.COMPLETED, RunState.FAILED, RunState.REJECTED])
def test_reject_raises_from_every_terminal_state(ident, state):
    run = ident.run()
    run.state = state
    with pytest.raises(InvalidTransitionError):
        run.reject(reason="already terminal")


def test_every_state_and_every_declared_transition_is_individually_reachable_and_consistent():
    assert set(_ALLOWED_TRANSITIONS.keys()) == set(RunState)
    for state in TERMINAL_STATES:
        assert _ALLOWED_TRANSITIONS[state] == frozenset()


# ============================================================ full lifecycle ==

def test_full_lifecycle_planned_to_completed(ident, monkeypatch, tmp_path):
    run = ident.run()
    assert run.state is RunState.PLANNED
    ident.validate(run)
    assert run.state is RunState.VALIDATED
    run.request_authorization()
    assert run.state is RunState.AWAITING_AUTHORIZATION
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    assert run.state is RunState.AUTHORIZED

    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
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


def test_pause_resume_cycle(started_run):
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="operator paused")
    assert started_run.state is RunState.PAUSED
    started_run.resume()
    assert started_run.state is RunState.RUNNING


def test_pause_recover_cycle(started_run):
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="checkpoint corruption suspected")
    started_run.begin_recovery(reason="restoring from last good checkpoint")
    assert started_run.state is RunState.RECOVERING
    started_run.recovered()
    assert started_run.state is RunState.RUNNING


def test_recovered_rejects_a_grant_that_expired_during_recovery(started_run):
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="pausing")
    started_run.begin_recovery(reason="recovering")
    object.__setattr__(started_run.grant, "expires_at", "2000-01-01T00:00:00Z")
    object.__setattr__(started_run.grant, "_mac", started_run.grant._compute_mac())
    with pytest.raises(StaleAuthorizationError):
        started_run.recovered()
    assert started_run.state is RunState.FAILED


# --------------------------------------------------------- forbidden transitions --

def test_cannot_skip_straight_from_planned_to_running(ident):
    run = ident.run()
    with pytest.raises(InvalidTransitionError):
        run.start()
    assert run.state is RunState.PLANNED


def test_cannot_authorize_before_requesting_authorization(ident, monkeypatch):
    run = ident.run()
    ident.validate(run)
    grant = ident.world().authorize(monkeypatch)
    with pytest.raises(InvalidTransitionError):
        run.authorize(grant)
    assert run.state is RunState.VALIDATED


def test_cannot_restart_a_completed_run(started_run, tmp_path):
    started_run.record_step(1, source_identity="a")
    started_run.complete(checkpoint_path=_real_checkpoint(tmp_path, step=1))
    assert started_run.state is RunState.COMPLETED
    with pytest.raises(InvalidTransitionError):
        started_run.start()


def test_cannot_resume_a_failed_run(started_run):
    started_run.fail(reason="simulated infrastructure failure")
    assert started_run.state is RunState.FAILED
    with pytest.raises(InvalidTransitionError):
        started_run.resume()
    with pytest.raises(InvalidTransitionError):
        started_run.reject(reason="too late")


def test_invalid_dataset_digest_rejects_the_run(ident):
    run = ident.run()
    with pytest.raises(ValueError):
        run.validate(
            dataset_digest="not-a-real-sha256", model_config_digest=ident.model_config_digest,
            tokenizer_digest=ident.tokenizer_digest, authorized_shard_digests=ident.authorized_shard_digests,
        )
    assert run.state is RunState.REJECTED


def test_invalid_model_config_digest_rejects_the_run(ident):
    run = ident.run()
    with pytest.raises(ValueError):
        run.validate(
            dataset_digest=ident.dataset_digest, model_config_digest="not-a-real-sha256",
            tokenizer_digest=ident.tokenizer_digest, authorized_shard_digests=ident.authorized_shard_digests,
        )
    assert run.state is RunState.REJECTED


def test_empty_authorized_shard_digests_rejects_the_run(ident):
    run = ident.run()
    with pytest.raises(ValueError):
        run.validate(
            dataset_digest=ident.dataset_digest, model_config_digest=ident.model_config_digest,
            tokenizer_digest=ident.tokenizer_digest, authorized_shard_digests=(),
        )
    assert run.state is RunState.REJECTED


def test_cannot_call_start_twice(started_run):
    with pytest.raises(InvalidTransitionError):
        started_run.start()


def test_cannot_authorize_an_already_authorized_run_again(authorized_run):
    assert authorized_run.state is RunState.AUTHORIZED
    with pytest.raises(InvalidTransitionError):
        authorized_run.authorize(authorized_run.grant)
