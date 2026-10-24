"""
GENESIS Foundation Sprint 2 -- cross-workstream integration tests
(Mission F6's second, previously `NOT_IMPLEMENTED` requirement).

Lives ONLY on `claude/genesis-cross-workstream-integration-2026-10-16`, a
branch that merges Workstream A (PR #63), Workstream C (PR #61, which
itself carries PR #58's Workstream B/D/Mission 1A), and Workstream F
(PR #64) together. **All four parent PRs remain draft, unaccepted, and
unmerged to `main`** -- PR #58 in particular carries an independent Audit
#017 successor verdict of `CONDITIONAL_REMEDIATION_REQUIRED`, not yet
resolved. This branch exists SOLELY to prove the real, concrete code from
all three workstreams binds together correctly end to end; it is NOT a
claim that any parent is independently qualified, and this branch must
never be merged to `main` on its own authority.

No training, GPU use, model-weight modification, or real signed grant
occurs anywhere in this file.
"""
from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import orca.config as orca_config  # noqa: E402
import orca.genesis.governance.authorization as GOV  # noqa: E402
from orca.genesis.data.manifest import (  # noqa: E402
    GenesisDatasetManifest,
    SourceOrigin,
    TokenizerBinding,
    TransformationStep,
)
from orca.genesis.training.orchestration import (  # noqa: E402
    GenesisTrainingRun,
    InvalidTransitionError,
    RunState,
)
import orca.genesis.training.orchestration as ORCH  # noqa: E402
from orca.train.authorization import TrainingGrant  # noqa: E402
from tests.test_training_authorization_gate import ENV as LORA_ENV, World as LoraWorld  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
GOV_ENV = "SELF_HOSTED_GPU"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _real_head_sha() -> str:
    """A real commit SHA that is trivially its own ancestor, for
    validate()'s live _is_live_ancestor_of_head() check (M2-01) -- see
    tests/test_genesis_training_orchestration.py's own identical
    helper."""
    import subprocess
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0
    return p.stdout.strip()


_HEAD_SHA = _real_head_sha()


@pytest.fixture(autouse=True)
def _reset_in_process_guards(tmp_path, monkeypatch):
    """Also isolates the DURABLE, on-disk native-pretraining-authorization
    replay claim (Mission 2) under a per-test ORCA_HOME -- without this,
    `_GovWorld`'s fixed default `authorization_id` would collide across
    test functions in this file via the real, persistent claim directory."""
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
    GenesisTrainingRun.reset_in_process_replay_guard_for_new_process()
    GOV.reset_in_process_nonce_guard_for_new_process()
    yield
    GenesisTrainingRun.reset_in_process_replay_guard_for_new_process()
    GOV.reset_in_process_nonce_guard_for_new_process()


def _real_dataset_manifest() -> tuple[GenesisDatasetManifest, list[str]]:
    """A real GenesisDatasetManifest (Workstream A) built from real
    records -- not a stub."""
    records = ["a synthetic genesis pretraining record one", "a synthetic genesis pretraining record two"]
    origin = SourceOrigin(
        source_id="integration-fixture-1", description="synthetic integration-test fixture",
        license_name="CC0-1.0", usage_restrictions="none", retrieved_at=_ts(datetime.now(timezone.utc)),
    )
    tb = TokenizerBinding(
        tokenizer_model_path="/tmp/integration-tok.model", architecture_version="genesis-arch-v1",
        vocab_digest=hashlib.sha256(b"integration-tokenizer-vocab-v1").hexdigest(),
    )
    manifest = GenesisDatasetManifest.build(
        dataset_name="cross-workstream-integration-fixture", version="v1", origins=[origin],
        normalized_records=records, transformation_lineage=[TransformationStep(name="normalize", code_reference="normalize_record_text")],
        tokenizer_binding=tb,
    )
    return manifest, records


class _GovWorld:
    """Mirrors tests/test_genesis_governance_authorization.py's own World
    fixture, parameterized by a REAL manifest's verified identity rather
    than arbitrary synthetic digests."""

    def __init__(
        self, manifest: GenesisDatasetManifest, *, run_id: str = "integration-run-1",
        dataset_content_digest: str | None = None, record_dataset_digest_override: str | None = None,
        tmp_path: Path | None = None,
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
        self.run_id = run_id
        self.model_config_digest = hashlib.sha256(b"integration-model-config-v1").hexdigest()
        self.shard_dir: Path | None = None
        if tmp_path is not None:
            # Antigravity Audit #71 (AUDIT-P0-01): GenesisTrainingRun.validate()
            # now independently re-verifies authorized_shard_digests against
            # real on-disk shard-*.jsonl bytes -- a caller-chosen digest
            # string no longer suffices.
            self.shard_dir = tmp_path / f"shards-{run_id}"
            self.shard_dir.mkdir(parents=True, exist_ok=True)
            (self.shard_dir / "shard-0000-train.jsonl").write_text('{"text": "integration fixture shard record"}\n')
            real_digests = ORCH._compute_authorized_shard_file_digests(self.shard_dir)
            self.authorized_shard_digests = tuple(sorted(d for _, d in real_digests))
        else:
            self.authorized_shard_digests = (hashlib.sha256(b"integration-shard-0").hexdigest(),)
        self.req = GOV.NativePretrainingRequest(
            run_id=run_id, nonce=hashlib.sha256(f"integration-nonce-seed-{run_id}".encode()).hexdigest(),
            model_family="genesis", architecture_version="genesis-arch-v1",
            model_config_digest=self.model_config_digest,
            tokenizer_digest=manifest.tokenizer_binding.vocab_digest, dataset_manifest_id=manifest.manifest_id,
            dataset_content_digest=dataset_content_digest if dataset_content_digest is not None else manifest.source_content_digest,
            authorized_shard_digests=self.authorized_shard_digests,
            reviewed_commit_sha=_HEAD_SHA, transformation_code_digest=hashlib.sha256(b"integration-pipeline-code-v1").hexdigest(),
            optimizer_config_digest=hashlib.sha256(b"integration-optimizer-config-v1").hexdigest(),
            environment_class=GOV_ENV, gpu_requested=False, max_wall_clock_minutes=30, requested_spend_usd=0.0,
        )
        self._record_dataset_digest_override = record_dataset_digest_override
        self.record = self._sign(self._make_record())

    def validate_matching_run(self, run: "GenesisTrainingRun") -> None:
        """Validates `run` with EXACTLY the identity fields this
        `_GovWorld`'s own request/record declare, so a grant minted from
        this world can genuinely authorize it (Mission 2's positive
        integration path)."""
        assert self.shard_dir is not None, "validate_matching_run() requires _GovWorld to have been constructed with tmp_path"
        records = ["cross-workstream-fixture-record"]
        run.validate(
            dataset_manifest=ORCH.BoundDatasetRecords(
                manifest_id=self.req.dataset_manifest_id,
                source_content_digest=self.req.dataset_content_digest,
                expected_records=tuple(records),
            ),
            dataset_records=records,
            model_config_digest=self.model_config_digest,
            tokenizer_digest=self.req.tokenizer_digest, authorized_shard_digests=self.authorized_shard_digests,
            shard_dir=self.shard_dir, reviewed_commit_sha=self.req.reviewed_commit_sha,
            transformation_code_digest=self.req.transformation_code_digest,
            optimizer_config_digest=self.req.optimizer_config_digest, gpu_requested=self.req.gpu_requested,
            requested_spend_usd=self.req.requested_spend_usd, requested_wall_clock_minutes=self.req.max_wall_clock_minutes,
        )

    def _sign(self, rec: dict) -> dict:
        rec = dict(rec)
        rec["signature"] = None
        rec["signature"] = self.priv.sign(GOV.canonical_signing_bytes(rec)).hex()
        return rec

    def _make_record(self) -> dict:
        now = datetime.now(timezone.utc)
        req = self.req
        return {
            "schema_version": GOV.SCHEMA_VERSION, "authorization_id": "gnpauth-" + "cd" * 8, "status": "AUTHORIZED",
            "run_id": req.run_id, "nonce": req.nonce,
            "model": {"family": req.model_family, "architecture_version": req.architecture_version, "model_config_digest": req.model_config_digest},
            "tokenizer": {"tokenizer_digest": req.tokenizer_digest},
            "dataset": {
                "dataset_manifest_id": req.dataset_manifest_id,
                "dataset_content_digest": self._record_dataset_digest_override or req.dataset_content_digest,
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

    def authorize(self, monkeypatch, **kw):
        monkeypatch.setattr(GOV, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
        monkeypatch.setattr(GOV, "PINNED_REGISTRY_SHA256", GOV.registry_digest(self.registry))
        return GOV.authorize_native_pretraining(
            repo_root=REPO_ROOT, record=self.record, registry=self.registry, revoked_ids=[],
            req=self.req, revocation_check=lambda auth_id: False, **kw,
        )


# ====================================================== real dataset identity binding =============

def test_a_real_dataset_manifest_content_digest_passes_governance_binding(monkeypatch):
    """The direct Mission F3 proof: Workstream F's authorization record is
    bound to Workstream A's REAL, independently re-verified
    source_content_digest -- not an arbitrary string."""
    manifest, records = _real_dataset_manifest()
    ok, msg = manifest.verify_against_records(records)
    assert ok, msg  # re-verify from the actual records BEFORE trusting the digest at all

    gov = _GovWorld(manifest)
    grant = gov.authorize(monkeypatch)
    assert grant.dataset_manifest_id == manifest.manifest_id
    assert grant.dataset_content_digest == manifest.source_content_digest


def test_a_tampered_dataset_content_digest_is_rejected_by_governance(monkeypatch):
    """The signed record claims a FORGED dataset_content_digest (not
    matching Workstream A's real, re-verified manifest digest) while the
    request still carries the manifest's genuine digest -- proving a
    caller cannot substitute an arbitrary digest string into the signed
    record and still have it accepted as referring to this manifest."""
    manifest, records = _real_dataset_manifest()
    forged_digest = hashlib.sha256(b"a forged, unrelated dataset content digest").hexdigest()
    gov = _GovWorld(manifest, record_dataset_digest_override=forged_digest)
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="WRONG_DATASET_CONTENT_DIGEST"):
        gov.authorize(monkeypatch)


def test_a_manifest_tampered_after_the_fact_is_caught_before_governance_ever_sees_it():
    """Workstream A's own re-verification boundary (not Workstream F's)
    is what catches a manifest whose on-disk content no longer matches
    its own claimed digest -- confirming the two workstreams' trust
    boundaries are complementary, not redundant or conflicting."""
    manifest, records = _real_dataset_manifest()
    tampered_records = [records[0], "a substituted, never-authorized record"]
    ok, msg = manifest.verify_against_records(tampered_records)
    assert ok is False
    assert "digest mismatch" in msg


# ====================================================== authorization-layer binding (Mission 2) =============

def test_a_correctly_bound_native_pretraining_grant_does_authorize_a_genesis_training_run(monkeypatch, tmp_path):
    """Native-Authorization-Convergence Mission 2: this is the FLIPPED
    expectation from the pre-Mission-2 version of this test (which
    confirmed a NativePretrainingGrant could NEVER authorize a
    GenesisTrainingRun, since the orchestrator only recognized the
    legacy LoRA TrainingGrant type). Mission 2 made NativePretrainingGrant
    the orchestrator's REAL, correct authorization type -- so a grant
    whose every field is genuinely bound to this run's own declared
    identity (including Workstream A's real, independently re-verified
    dataset manifest identity) now DOES authorize it. This is the direct,
    positive proof of Mission 2's cross-workstream integration."""
    manifest, records = _real_dataset_manifest()
    ok, msg = manifest.verify_against_records(records)
    assert ok, msg

    gov = _GovWorld(manifest, run_id="integration-run-1", tmp_path=tmp_path)
    native_grant = gov.authorize(monkeypatch)
    assert isinstance(native_grant, GOV.NativePretrainingGrant)

    run = GenesisTrainingRun(
        "integration-run-1", dataset_manifest_ids=(manifest.manifest_id,), environment_class=GOV_ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    gov.validate_matching_run(run)
    run.request_authorization()
    run.authorize(native_grant)
    assert run.state is RunState.AUTHORIZED
    assert run.grant is native_grant


def test_a_native_pretraining_grant_bound_to_a_different_run_is_still_rejected(monkeypatch, tmp_path):
    """The positive case above does not mean ANY NativePretrainingGrant
    authorizes ANY run -- exact workload binding (Mission 2's own
    requirement) still applies between two independently-constructed
    GenesisTrainingRun/grant pairs."""
    manifest, records = _real_dataset_manifest()
    gov = _GovWorld(manifest, run_id="integration-run-OTHER", tmp_path=tmp_path)
    native_grant = gov.authorize(monkeypatch)

    run = GenesisTrainingRun(
        "integration-run-1", dataset_manifest_ids=(manifest.manifest_id,), environment_class=GOV_ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    gov.validate_matching_run(run)
    run.request_authorization()
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="WRONG_RUN_ID"):
        run.authorize(native_grant)
    assert run.state is RunState.REJECTED


def test_a_lora_training_grant_still_cannot_authorize_a_genesis_training_run(tmp_path, monkeypatch):
    """Re-confirms Workstream C's own C-01 fix still holds on this merged
    branch, now expressed against the real native grant type: a real,
    legitimately-issued orca.train.authorization.TrainingGrant for an
    unrelated LoRA config is REJECTED AT THE TYPE LEVEL by
    GenesisTrainingRun (Mission 2 no longer accepts it at all, not even
    via a fingerprint check) -- the legacy and native authorization
    mechanisms do not interfere with or weaken each other."""
    manifest, records = _real_dataset_manifest()
    lora_world = LoraWorld(tmp_path, monkeypatch)
    lora_grant = lora_world.authorize()
    assert isinstance(lora_grant, TrainingGrant)

    run = GenesisTrainingRun(
        "integration-run-2", dataset_manifest_ids=(manifest.manifest_id,), environment_class=LORA_ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    # Antigravity Audit #71 (AUDIT-P0-01): validate() now independently
    # re-verifies authorized_shard_digests against real on-disk bytes.
    unused_shard_dir = tmp_path / "shards-integration-run-2"
    unused_shard_dir.mkdir(parents=True, exist_ok=True)
    (unused_shard_dir / "shard-0000-train.jsonl").write_text('{"text": "unused fixture shard record"}\n')
    unused_shard_digests = tuple(sorted(d for _, d in ORCH._compute_authorized_shard_file_digests(unused_shard_dir)))
    run.validate(
        dataset_manifest=manifest, dataset_records=records,
        model_config_digest=hashlib.sha256(b"unused").hexdigest(),
        tokenizer_digest=hashlib.sha256(b"unused").hexdigest(), authorized_shard_digests=unused_shard_digests,
        shard_dir=unused_shard_dir, reviewed_commit_sha=_HEAD_SHA,
        transformation_code_digest=hashlib.sha256(b"unused-pipeline").hexdigest(),
        optimizer_config_digest=hashlib.sha256(b"unused-optimizer").hexdigest(),
    )
    run.request_authorization()
    with pytest.raises(GOV.NativePretrainingNotAuthorized, match="NO_NATIVE_PRETRAINING_GRANT"):
        run.authorize(lora_grant)  # type: ignore[arg-type]
    assert run.state is RunState.REJECTED


def test_authorizing_a_genesis_training_run_does_not_itself_authorize_native_pretraining(monkeypatch):
    """The converse direction: even a (hypothetically) successfully
    AUTHORIZED GenesisTrainingRun carries no standing to call
    authorize_native_pretraining() -- the two gates are consulted
    independently; neither's success implies the other's. Demonstrated
    here by confirming that reaching GenesisTrainingRun.start() (via the
    test-only bypass already established in Workstream C's own test
    suite, since no real GENESIS-scoped LoRA grant can naturally exist)
    has no effect whatsoever on whether
    orca.genesis.governance.authorization.authorize_native_pretraining()
    succeeds -- it still independently requires its own real founder
    acceptance ledger and its own signed record, checked here with THAT
    check deliberately left un-mocked to confirm the real, current, empty
    ledger still denies regardless of the GenesisTrainingRun's own state."""
    manifest, records = _real_dataset_manifest()
    gov = _GovWorld(manifest)
    # Deliberately do NOT monkeypatch check_founder_acceptance_ledger here --
    # prove the real repo's real ledger still blocks this, independent of
    # anything happening on the GenesisTrainingRun side.
    with pytest.raises(GOV.NativePretrainingNotAuthorized) as exc:
        GOV.authorize_native_pretraining(
            repo_root=REPO_ROOT, record=gov.record, registry=gov.registry, revoked_ids=[],
            req=gov.req, revocation_check=lambda auth_id: False,
        )
    assert any("FOUNDER_ACCEPTANCE_INCOMPLETE" in r for r in exc.value.reasons)


# ====================================================== end-to-end real-object wiring =============

def test_full_real_object_chain_dataset_manifest_to_training_run_to_native_grant(monkeypatch, tmp_path):
    """The complete positive chain, all real objects, now through
    GENUINE authorization (Mission 2): a real GenesisDatasetManifest (A)
    re-verified from real records, a real GenesisTrainingRun (C)
    validated against that manifest's real digest, and a real
    NativePretrainingGrant (F) bound to that same manifest's real
    identity -- three independently-developed modules, on three separate
    draft branches, genuinely interoperating all the way to a real
    AUTHORIZED state (still short of execution, which additionally
    requires the FINAL-1/FINAL-2/EXEC-1 acceptance gate -- see the
    dedicated test below)."""
    manifest, records = _real_dataset_manifest()
    ok, msg = manifest.verify_against_records(records)
    assert ok, msg

    gov = _GovWorld(manifest, run_id="integration-run-3", tmp_path=tmp_path)
    run = GenesisTrainingRun(
        "integration-run-3", dataset_manifest_ids=(manifest.manifest_id,), environment_class=GOV_ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    gov.validate_matching_run(run)
    assert run.identity.dataset_digest == manifest.source_content_digest
    run.request_authorization()
    assert run.state is RunState.AWAITING_AUTHORIZATION

    native_grant = gov.authorize(monkeypatch)
    assert native_grant.dataset_manifest_id == run.identity.dataset_manifest_ids[0]
    assert native_grant.dataset_content_digest == run.identity.dataset_digest

    run.authorize(native_grant)
    assert run.state is RunState.AUTHORIZED
    assert run.grant is native_grant


def test_full_real_object_chain_execution_start_still_requires_the_real_empty_acceptance_ledger(monkeypatch, tmp_path):
    """The positive chain above reaches AUTHORIZED -- it must NOT, by
    itself, reach RUNNING. start() requires the project-wide
    founder-acceptance ledger to additionally show FINAL-2 and EXEC-1
    accepted; the real, committed ledger is empty, so even this fully
    and correctly authorized run is denied at the execution-start
    boundary, confirming native training remains NO-GO end to end."""
    manifest, records = _real_dataset_manifest()
    gov = _GovWorld(manifest, run_id="integration-run-4", tmp_path=tmp_path)
    run = GenesisTrainingRun(
        "integration-run-4", dataset_manifest_ids=(manifest.manifest_id,), environment_class=GOV_ENV,
        repo_root=REPO_ROOT, revocation_check=lambda auth_id: False,
    )
    gov.validate_matching_run(run)
    run.request_authorization()
    native_grant = gov.authorize(monkeypatch)
    run.authorize(native_grant)
    assert run.state is RunState.AUTHORIZED

    with pytest.raises(ORCH.ExecutionAcceptanceIncompleteError):
        run.start()
    assert run.state is RunState.REJECTED
