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


def _make_real_shard_dir(tmp_path: Path, run_id: str, *, num_shards: int = 2) -> tuple[Path, tuple[str, ...]]:
    """Antigravity Audit #71 (AUDIT-P0-01): `validate()` now independently
    re-verifies `authorized_shard_digests` against the REAL on-disk bytes
    of `shard_dir` -- a caller-chosen digest string no longer suffices.
    Writes real, deterministic `shard-*.jsonl` files and returns their
    genuinely computed digests (via the same SHA-256 streaming discipline
    `orca.genesis.training.orchestration._compute_authorized_shard_file_digests()`
    uses), so this fixture's digests always match real file content."""
    shard_dir = tmp_path / f"shards-{run_id}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    for i in range(num_shards):
        (shard_dir / f"shard-{i:04d}-train.jsonl").write_text(f'{{"text": "fixture record for {run_id} shard {i}"}}\n')
    digests = ORCH._compute_authorized_shard_file_digests(shard_dir)
    return shard_dir, tuple(sorted(d for _, d in digests))


def _real_head_sha() -> str:
    """A real commit SHA that is -- trivially -- its own ancestor, for
    `validate()`'s live `_is_live_ancestor_of_head()` check (M2-01).
    Using the actual current HEAD of this checkout, not a fabricated
    SHA-40-shaped string, is the point: `validate()` now independently
    verifies this against real git history, not a caller's claim alone."""
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0, "this test file requires running inside a real git checkout"
    return p.stdout.strip()


_HEAD_SHA = _real_head_sha()


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
        environment_class: str = ENV, reviewed_commit_sha: str = _HEAD_SHA,
        transformation_code_digest: str | None = None, optimizer_config_digest: str | None = None,
        architecture_version: str = "genesis-arch-v1",
        gpu_allowed: bool = False, max_spend_usd: float = 0.0, max_wall_clock_minutes: int = 60,
        record_over: dict | None = None,
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
        self.gpu_allowed = gpu_allowed
        self.max_spend_usd = max_spend_usd
        self.max_wall_clock_minutes = max_wall_clock_minutes
        self.req = GOV.NativePretrainingRequest(
            run_id=run_id, nonce=_digest(f"nonce-{run_id}-{id(self)}"), model_family="genesis",
            architecture_version=architecture_version, model_config_digest=model_config_digest, tokenizer_digest=tokenizer_digest,
            dataset_manifest_id=dataset_manifest_id, dataset_content_digest=dataset_content_digest,
            authorized_shard_digests=tuple(authorized_shard_digests), reviewed_commit_sha=reviewed_commit_sha,
            transformation_code_digest=transformation_code_digest or _digest(f"pipeline-{run_id}"),
            optimizer_config_digest=optimizer_config_digest or _digest(f"optimizer-{run_id}"),
            environment_class=environment_class, gpu_requested=False, max_wall_clock_minutes=max_wall_clock_minutes,
            requested_spend_usd=0.0,
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
            "limits": {
                "max_wall_clock_minutes": self.max_wall_clock_minutes, "max_spend_usd": self.max_spend_usd,
                "gpu_allowed": self.gpu_allowed,
            },
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

    def __init__(self, tmp_path: Path, run_id: str = "run-1"):
        self.run_id = run_id
        self.dataset_manifest_id = "genesis-fixture-v1"
        self.dataset_digest = _digest(f"dataset-{run_id}")
        self.model_config_digest = _digest(f"model-config-{run_id}")
        self.tokenizer_digest = _digest(f"tokenizer-{run_id}")
        self.shard_dir, self.authorized_shard_digests = _make_real_shard_dir(tmp_path, run_id)
        self.reviewed_commit_sha = _HEAD_SHA
        self.transformation_code_digest = _digest(f"pipeline-{run_id}")
        self.optimizer_config_digest = _digest(f"optimizer-{run_id}")
        self.gpu_requested = False
        self.requested_spend_usd = 0.0
        self.requested_wall_clock_minutes = 30

    def world(self, **kw) -> GrantWorld:
        defaults = dict(
            run_id=self.run_id, model_config_digest=self.model_config_digest, tokenizer_digest=self.tokenizer_digest,
            dataset_manifest_id=self.dataset_manifest_id, dataset_content_digest=self.dataset_digest,
            authorized_shard_digests=self.authorized_shard_digests, reviewed_commit_sha=self.reviewed_commit_sha,
            transformation_code_digest=self.transformation_code_digest, optimizer_config_digest=self.optimizer_config_digest,
            max_wall_clock_minutes=max(60, self.requested_wall_clock_minutes),
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
            shard_dir=self.shard_dir, reviewed_commit_sha=self.reviewed_commit_sha,
            transformation_code_digest=self.transformation_code_digest,
            optimizer_config_digest=self.optimizer_config_digest, gpu_requested=self.gpu_requested,
            requested_spend_usd=self.requested_spend_usd, requested_wall_clock_minutes=self.requested_wall_clock_minutes,
        )


@pytest.fixture
def ident(tmp_path) -> _Identity:
    return _Identity(tmp_path)


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
    ("architecture_version", "a-completely-different-architecture-v99"),
    ("transformation_code_digest", _digest("a different transformation pipeline")),
    ("optimizer_config_digest", _digest("a different optimizer config")),
])
def test_wrong_single_field_grant_is_rejected_not_authorized(ident, monkeypatch, field, wrong_value):
    """Exact workload binding, field by field (M2-01: now covers the full
    signed-authorization field set, not only the original six): a grant
    that matches EVERY field except ONE must still be rejected -- proving
    each field is actually checked, not merely one of them standing in
    for all."""
    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    kwargs = dict(
        run_id=ident.run_id, model_config_digest=ident.model_config_digest, tokenizer_digest=ident.tokenizer_digest,
        dataset_manifest_id=ident.dataset_manifest_id, dataset_content_digest=ident.dataset_digest,
        authorized_shard_digests=ident.authorized_shard_digests, environment_class=ENV,
        transformation_code_digest=ident.transformation_code_digest, optimizer_config_digest=ident.optimizer_config_digest,
    )
    kwargs[field] = wrong_value
    grant = GrantWorld(**kwargs).authorize(monkeypatch)
    with pytest.raises(GOV.NativePretrainingNotAuthorized):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_a_grant_that_disallows_gpu_rejects_a_run_that_requests_gpu(ident, monkeypatch):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["gpu_requested"] = True
    run.validate(**kwargs)
    run.request_authorization()
    grant = ident.world(gpu_allowed=False).authorize(monkeypatch)  # the grant does not permit GPU
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="GPU_NOT_AUTHORIZED"):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_a_grant_with_zero_spend_rejects_a_run_that_requests_spend(ident, monkeypatch):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["requested_spend_usd"] = 50.0
    run.validate(**kwargs)
    run.request_authorization()
    grant = ident.world(max_spend_usd=0.0).authorize(monkeypatch)
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="SPEND_NOT_AUTHORIZED"):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_a_grant_with_a_lower_wall_clock_limit_rejects_a_run_that_requests_more(ident, monkeypatch):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["requested_wall_clock_minutes"] = 120
    run.validate(**kwargs)
    run.request_authorization()
    grant = ident.world(max_wall_clock_minutes=60).authorize(monkeypatch)  # grant permits only 60 minutes
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="WALL_CLOCK_NOT_AUTHORIZED"):
        run.authorize(grant)
    assert run.state is RunState.REJECTED


def test_a_grant_with_a_higher_wall_clock_limit_than_requested_is_accepted(ident, monkeypatch):
    """Positive control: wall-clock is a LIMIT, not a value that must
    match exactly -- a grant permitting up to 60 minutes correctly
    authorizes a run that only needs 30. (Spend cannot be used for this
    same positive-direction proof: Workstream F's own gate enforces
    `max_spend_usd == 0` unconditionally while native training remains
    NO-GO, regardless of what any individual run requests -- see
    `orca.genesis.governance.authorization.verify()`'s
    `SPEND_MUST_BE_ZERO_WHILE_NOGO` check.)"""
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["gpu_requested"] = False
    kwargs["requested_spend_usd"] = 0.0
    kwargs["requested_wall_clock_minutes"] = 30
    run.validate(**kwargs)
    run.request_authorization()
    grant = ident.world(gpu_allowed=False, max_spend_usd=0.0, max_wall_clock_minutes=60).authorize(monkeypatch)
    run.authorize(grant)
    assert run.state is RunState.AUTHORIZED


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


def test_a_truthy_non_boolean_revocation_result_is_still_treated_as_revoked(ident, monkeypatch):
    """M2-04 adversarial qualification: the revocation-service boundary
    must not assume a well-behaved `bool` return -- any truthy value
    (a non-empty string, a non-zero count, a populated list) means
    revoked, matching ordinary Python truthiness, not a strict `is True`
    check that a loosely-typed real revocation service could accidentally
    bypass by returning e.g. `"revoked"` instead of `True`."""
    run = ident.run(revocation_check=lambda auth_id: "yes, revoked")  # truthy, not literally True
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
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


def test_concurrent_claims_of_the_same_authorization_id_have_exactly_one_winner(ident):
    """M2-04 adversarial qualification: the durable, on-disk replay claim
    must be atomic under genuine concurrency, not merely correct in a
    single-threaded call sequence -- many threads racing to claim the
    SAME authorization_id simultaneously must produce exactly one
    winner, proven directly rather than inferred from `O_EXCL`'s
    documented semantics alone."""
    import threading

    auth_id = "gnpauth-" + "33" * 8
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def _claim():
        barrier.wait(timeout=5)  # maximize actual concurrent contention
        won = ORCH._claim_native_pretraining_authorization(auth_id)
        with lock:
            results.append(won)

    threads = [threading.Thread(target=_claim) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(results) == 20
    assert sum(results) == 1, f"expected exactly one winner among 20 concurrent claimants, got {sum(results)}"


def test_crash_consistency_residual_is_documented_not_silently_fixed(ident, monkeypatch, tmp_path):
    """M2-04: documents a REAL, acknowledged residual rather than
    silently papering over it (per the directive's own instruction to
    document limitations that cannot be resolved within this
    workstream). If a process crashes AFTER
    `_claim_native_pretraining_authorization()` succeeds but BEFORE
    `authorize()` finishes transitioning the run to AUTHORIZED (e.g.
    killed between those two lines), the authorization_id is durably,
    permanently claimed -- yet no run ever actually reached AUTHORIZED
    with it. This mirrors `orca.train.authorization._claim_run_slot()`'s
    own documented trade-off exactly ('a failed or cancelled run still
    consumes its slot... a local operator who deletes this directory can
    re-run'): this module does not attempt to solve the general
    two-phase-commit problem of 'durably claim X and atomically also do
    Y,' which would require a transaction log this module does not have
    and was not asked to build. Demonstrated here by simulating the
    crash directly: claim the id, then attempt a legitimate authorize()
    with a freshly-matching grant for a DIFFERENT run -- it is correctly
    refused, with no automatic recovery path, exactly as documented."""
    ORCH._claim_native_pretraining_authorization("gnpauth-" + "44" * 8)  # simulates the claim half of a crashed authorize()

    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    grant = ident.world(record_over={"authorization_id": "gnpauth-" + "44" * 8}).authorize(monkeypatch)
    with pytest.raises(ReplayedAuthorizationError):
        run.authorize(grant)  # the crash's orphaned claim permanently burns this id -- no automatic recovery
    assert run.state is RunState.REJECTED


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


def test_execution_permission_becoming_invalid_after_a_pause_blocks_resume(started_run, monkeypatch):
    """M2-02: independently reproduced as a real gap before this fix --
    the founder-acceptance ledger's FINAL-1/FINAL-2/EXEC-1 rows were only
    ever checked at the original start() call; a run that reached
    RUNNING while the ledger showed those rows accepted, then paused,
    would previously resume() successfully even if that acceptance had
    since been WITHDRAWN. Execution permission must be re-established at
    EVERY resumption point, not assumed to persist from whenever
    start() last checked it."""
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="pausing")
    # Simulate acceptance being withdrawn while paused (e.g. a prior
    # acceptance later found invalid and reverted) -- the real ledger is
    # always empty; this directly exercises the "no longer accepted"
    # transition, not merely "was never accepted."
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: ["FINAL-2", "EXEC-1"])
    with pytest.raises(ExecutionAcceptanceIncompleteError):
        started_run.resume()
    assert started_run.state is RunState.FAILED


def test_execution_permission_becoming_invalid_during_recovery_blocks_recovered(started_run, monkeypatch):
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="pausing")
    started_run.begin_recovery(reason="recovering")
    monkeypatch.setattr(ORCH, "check_founder_acceptance_ledger", lambda repo_root, **_: ["EXEC-1"])
    with pytest.raises(ExecutionAcceptanceIncompleteError):
        started_run.recovered()
    assert started_run.state is RunState.FAILED


def test_resume_still_succeeds_when_acceptance_remains_accepted_throughout(started_run):
    """Negative control: resume() must still succeed when nothing has
    changed -- confirms M2-02's new re-check is not spuriously failing
    the ordinary, unchanged case (the `started_run` fixture already keeps
    `check_founder_acceptance_ledger` patched to return `[]`)."""
    started_run.record_step(1, source_identity="a")
    started_run.pause(reason="pausing")
    started_run.resume()
    assert started_run.state is RunState.RUNNING


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


def _valid_validate_kwargs(ident) -> dict:
    return dict(
        dataset_digest=ident.dataset_digest, model_config_digest=ident.model_config_digest,
        tokenizer_digest=ident.tokenizer_digest, authorized_shard_digests=ident.authorized_shard_digests,
        shard_dir=ident.shard_dir, reviewed_commit_sha=ident.reviewed_commit_sha,
        transformation_code_digest=ident.transformation_code_digest,
        optimizer_config_digest=ident.optimizer_config_digest,
    )


def test_invalid_dataset_digest_rejects_the_run(ident):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["dataset_digest"] = "not-a-real-sha256"
    with pytest.raises(ValueError):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_invalid_model_config_digest_rejects_the_run(ident):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["model_config_digest"] = "not-a-real-sha256"
    with pytest.raises(ValueError):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_empty_authorized_shard_digests_rejects_the_run(ident):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["authorized_shard_digests"] = ()
    with pytest.raises(ValueError):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_invalid_reviewed_commit_sha_rejects_the_run(ident):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["reviewed_commit_sha"] = "not-a-real-sha1"
    with pytest.raises(ValueError):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_a_reviewed_commit_sha_that_is_not_a_real_ancestor_of_head_is_rejected(ident):
    """M2-01: a caller-supplied SHA-40-SHAPED string that is well-formed
    but is NOT genuinely an ancestor of this repository's real HEAD must
    be rejected -- independently verified against live git state, not
    trusted merely because it looks like a commit hash."""
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["reviewed_commit_sha"] = "f" * 40  # well-formed, but not a real commit in this repo's history
    with pytest.raises(ValueError, match="not verifiably an ancestor"):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


# ============================================================ NaN / nonfinite / type-confusion hardening ==

def test_nan_spend_is_rejected_not_silently_accepted(ident):
    """Independently reproduced before this fix: `requested_spend_usd=
    float("nan")` passed the prior `isinstance(..., (int, float))` and
    `nan < 0` checks (every comparison against NaN is False), and would
    have ALSO silently passed authorize()'s later
    `current.requested_spend_usd > grant.max_spend_usd` limit check for
    the identical reason -- a NaN spend request would bypass spend-limit
    enforcement entirely, regardless of what any real grant authorizes."""
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["requested_spend_usd"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_infinite_spend_is_rejected_at_validation_not_only_caught_downstream(ident):
    """+inf technically fails authorize()'s later `>` check against any
    finite grant limit (`inf > 0` is True), but it is still not a
    meaningful resource value -- rejected here too, for defense in depth
    rather than relying solely on a downstream comparison happening to
    catch it."""
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["requested_spend_usd"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_boolean_spend_value_is_rejected_despite_bool_being_an_int_subtype(ident):
    """`bool` is a Python `int` subtype, so `isinstance(True, (int, float))`
    is True -- a stray `True`/`False` passed where a real spend amount
    was expected must still be rejected, not silently treated as 1 or 0
    dollars."""
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["requested_spend_usd"] = True
    with pytest.raises(ValueError):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_boolean_wall_clock_value_is_rejected_despite_bool_being_an_int_subtype(ident):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["requested_wall_clock_minutes"] = True  # == 1, would otherwise pass "< 1" silently
    with pytest.raises(ValueError):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_a_string_claiming_to_be_a_boolean_is_rejected_not_silently_coerced(ident):
    """Independently reproduced before this fix: `bool("False")` is
    `True` in Python (any non-empty string is truthy) -- a caller
    passing the STRING `"False"`, intending NOT to request GPU, would
    previously have silently gotten `gpu_requested=True`, the exact
    opposite of their intent. `gpu_requested` must now be a real `bool`,
    never coerced from an arbitrary truthy/falsy value."""
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["gpu_requested"] = "False"
    with pytest.raises(ValueError, match="never silently coerced"):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_a_real_boolean_gpu_requested_still_works_normally(ident, monkeypatch):
    """Negative control: real booleans must still work exactly as
    before -- confirms the new strict type check doesn't spuriously
    break the ordinary case."""
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    kwargs["gpu_requested"] = False
    run.validate(**kwargs)
    assert run.state is RunState.VALIDATED
    assert run.identity.gpu_requested is False


# ============================================================ dataset preflight integration (M2-03) ==

class _FakeDatasetManifest:
    """A minimal object satisfying Workstream F's `DatasetManifestLike`
    Protocol (duck-typed, not imported from Workstream A -- this module
    gains no hard dependency on `orca.genesis.data.manifest`). Mimics the
    real `GenesisDatasetManifest.verify_against_records()` contract:
    returns `(True, "")` only when `records` match what this fake
    manifest was constructed to expect."""

    def __init__(self, manifest_id: str, source_content_digest: str, expected_records: list[str]):
        self.manifest_id = manifest_id
        self.source_content_digest = source_content_digest
        self._expected_records = expected_records

    def verify_against_records(self, normalized_records: list[str]) -> tuple[bool, str]:
        if list(normalized_records) != self._expected_records:
            return False, "digest mismatch: records do not match this manifest's claimed content"
        return True, ""


def test_validate_with_a_real_manifest_object_derives_digest_from_verified_identity(ident):
    """M2-03: the positive path -- a manifest object that successfully
    re-verifies against the records passed alongside it is accepted, and
    `dataset_digest` is derived from the VERIFIED object's own
    `source_content_digest`, not from any separately-supplied string."""
    run = ident.run()
    records = ["record one", "record two"]
    manifest = _FakeDatasetManifest(ident.dataset_manifest_id, ident.dataset_digest, records)
    kwargs = _valid_validate_kwargs(ident)
    del kwargs["dataset_digest"]
    run.validate(dataset_manifest=manifest, dataset_records=records, **kwargs)
    assert run.state is RunState.VALIDATED
    assert run.identity.dataset_digest == ident.dataset_digest


def test_validate_rejects_a_manifest_that_fails_verify_against_records(ident):
    """M2-03: independently reproduced as the exact gap this fix closes
    -- before this fix, `validate()` only ever checked that a
    caller-supplied digest string was well-formed (64 hex characters),
    never that it corresponded to any real, re-verifiable content. A
    manifest object whose own `verify_against_records()` fails (e.g. the
    records were substituted) must be rejected here, not accepted merely
    because its `source_content_digest` string looks well-formed."""
    run = ident.run()
    real_records = ["record one", "record two"]
    tampered_records = ["record one", "a substituted record"]
    manifest = _FakeDatasetManifest(ident.dataset_manifest_id, ident.dataset_digest, real_records)
    kwargs = _valid_validate_kwargs(ident)
    del kwargs["dataset_digest"]
    with pytest.raises(ValueError, match="failed independent re-verification"):
        run.validate(dataset_manifest=manifest, dataset_records=tampered_records, **kwargs)
    assert run.state is RunState.REJECTED


def test_validate_rejects_a_manifest_whose_id_is_not_declared_by_this_run(ident):
    run = ident.run()
    records = ["record one"]
    manifest = _FakeDatasetManifest("a-manifest-id-this-run-never-declared", ident.dataset_digest, records)
    kwargs = _valid_validate_kwargs(ident)
    del kwargs["dataset_digest"]
    with pytest.raises(ValueError, match="not in this run's declared dataset_manifest_ids"):
        run.validate(dataset_manifest=manifest, dataset_records=records, **kwargs)
    assert run.state is RunState.REJECTED


def test_validate_requires_dataset_records_when_dataset_manifest_is_supplied(ident):
    run = ident.run()
    manifest = _FakeDatasetManifest(ident.dataset_manifest_id, ident.dataset_digest, ["x"])
    kwargs = _valid_validate_kwargs(ident)
    del kwargs["dataset_digest"]
    with pytest.raises(ValueError, match="dataset_records is required"):
        run.validate(dataset_manifest=manifest, **kwargs)
    assert run.state is RunState.REJECTED


def test_validate_requires_either_dataset_digest_or_dataset_manifest(ident):
    run = ident.run()
    kwargs = _valid_validate_kwargs(ident)
    del kwargs["dataset_digest"]
    with pytest.raises(ValueError, match="requires either dataset_digest or"):
        run.validate(**kwargs)
    assert run.state is RunState.REJECTED


def test_cannot_call_start_twice(started_run):
    with pytest.raises(InvalidTransitionError):
        started_run.start()


def test_cannot_authorize_an_already_authorized_run_again(authorized_run):
    assert authorized_run.state is RunState.AUTHORIZED
    with pytest.raises(InvalidTransitionError):
        authorized_run.authorize(authorized_run.grant)


def test_marker_files_are_owner_only_permissions(ident, monkeypatch):
    """P1-03: durable replay-claim marker files must be 0o600 (owner-only),
    consistent with every other sensitive artifact this codebase writes
    under ORCA_HOME."""
    import os
    import stat

    run = ident.run()
    ident.validate(run)
    run.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run.authorize(grant)
    marker = ORCH._native_pretraining_replay_state_dir() / f"{grant.authorization_id}.claimed"
    assert marker.exists()
    mode = stat.S_IMODE(os.stat(marker).st_mode)
    assert mode == 0o600


def test_deleting_the_marker_file_allows_the_authorization_id_to_be_reclaimed(ident, monkeypatch):
    """P1-03: documents the accepted residual explicitly, as a test, not
    merely prose -- a local operator with write access to ORCA_HOME can
    delete a .claimed marker and allow that authorization_id to be
    consumed again. This mirrors orca.train.authorization._claim_run_slot()'s
    own documented trade-off exactly; the security boundary is WHO can
    write to ORCA_HOME, not this guard mechanism."""
    run_a = ident.run()
    ident.validate(run_a)
    run_a.request_authorization()
    grant = ident.world().authorize(monkeypatch)
    run_a.authorize(grant)
    assert run_a.state is RunState.AUTHORIZED

    marker = ORCH._native_pretraining_replay_state_dir() / f"{grant.authorization_id}.claimed"
    marker.unlink()

    run_b = ident.run()
    ident.validate(run_b)
    run_b.request_authorization()
    run_b.authorize(grant)  # succeeds again -- the marker's absence means "never claimed"
    assert run_b.state is RunState.AUTHORIZED
