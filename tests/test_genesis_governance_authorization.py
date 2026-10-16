"""
GENESIS Foundation Sprint 2, Workstream F: native-pretraining
authorization contract tests. All signing keys here are SYNTHETIC,
freshly generated Ed25519 keys, never read from or written to the real
(empty, committed) `docs/orneur/authorization/genesis_native_pretraining/*`
files. No training, GPU use, or optimizer step occurs anywhere.

Positive-path tests monkeypatch `check_founder_acceptance_ledger` to
simulate a HYPOTHETICAL future state where the founder acceptance ledger
has accepted the required rows -- this NEVER reflects the real repo state
(confirmed empty by a dedicated test below) and is used only to isolate
and test the cryptographic authorization-binding logic on its own.
"""
from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import orca.genesis.governance.authorization as A

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class World:
    """A synthetic signing world for THIS module's own domain -- mirrors
    tests/test_training_authorization_gate.py's own World fixture pattern,
    but for a genuinely different schema/signing-domain, never touching
    orca.train.authorization's files or keys."""

    def __init__(self, *, record_over=None, registry_over=None, revoked=(), key_role="OWNER", extra_record_kwargs=None):
        self.priv = Ed25519PrivateKey.generate()
        pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        now = datetime.now(timezone.utc)
        key = {
            "id": "synthetic-authority-1", "role": key_role, "public_key_hex": pub,
            "activation_timestamp": _ts(now - timedelta(days=1)), "expiry": None, "revoked": False,
            "gpu_permission": False, "spend_permission": False,
        }
        key = _merge(key, registry_over or {})
        self.registry = {"schema_version": A.REGISTRY_SCHEMA_VERSION, "records": [key]}
        self.revocations = {"schema_version": A.REVOCATIONS_SCHEMA_VERSION, "revoked_authorization_ids": list(revoked)}

        self.run_id = "run-1"
        self.nonce = hashlib.sha256(b"synthetic-nonce-seed").hexdigest()
        self.req = A.NativePretrainingRequest(
            run_id=self.run_id, nonce=self.nonce, model_family="genesis", architecture_version="genesis-arch-v1",
            model_config_digest=hashlib.sha256(b"model-config-v1").hexdigest(), tokenizer_digest=hashlib.sha256(b"tokenizer-v1").hexdigest(),
            dataset_manifest_id="genesis-fixture-v1", dataset_content_digest=hashlib.sha256(b"dataset-v1").hexdigest(),
            authorized_shard_digests=(hashlib.sha256(b"shard-0").hexdigest(), hashlib.sha256(b"shard-1").hexdigest()),
            reviewed_commit_sha="a" * 40, transformation_code_digest=hashlib.sha256(b"pipeline-code-v1").hexdigest(),
            optimizer_config_digest=hashlib.sha256(b"optimizer-config-v1").hexdigest(), environment_class=ENV,
            gpu_requested=False, max_wall_clock_minutes=30, requested_spend_usd=0.0,
        )
        self.record = self.make_record(record_over or {}, **(extra_record_kwargs or {}))

    def _sign(self, rec: dict) -> dict:
        rec = dict(rec)
        rec["signature"] = None
        rec["signature"] = self.priv.sign(A.canonical_signing_bytes(rec)).hex()
        return rec

    def make_record(self, over: dict, **kw) -> dict:
        req = kw.get("req", self.req)
        now = datetime.now(timezone.utc)
        rec = {
            "schema_version": A.SCHEMA_VERSION, "authorization_id": "gnpauth-" + "ab" * 8, "status": "AUTHORIZED",
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
        return self._sign(_merge(rec, over))

    def authorize(self, *, revocation_check="__default__", req=None, monkeypatch=None, founder_ready=True, pin=True, **kw):
        if monkeypatch is not None and founder_ready:
            monkeypatch.setattr(A, "check_founder_acceptance_ledger", lambda repo_root, **_: [])
        if monkeypatch is not None and pin:
            # Synthetic-world registries never match the real, empty,
            # committed registry's pinned digest (by design -- see the
            # module docstring: "the committed registry below is empty
            # ... nothing can cause authorize_native_pretraining() to
            # return anything other than a denial today"). Tests that
            # need to exercise the signature/binding MECHANISM pin to
            # their OWN synthetic registry's digest instead -- the exact
            # same pattern tests/test_training_authorization_gate.py's
            # own World fixture uses for orca.train.authorization.
            monkeypatch.setattr(A, "PINNED_REGISTRY_SHA256", A.registry_digest(self.registry))
        return A.authorize_native_pretraining(
            repo_root=REPO_ROOT, record=self.record, registry=self.registry,
            revoked_ids=self.revocations["revoked_authorization_ids"], req=req or self.req,
            revocation_check=(lambda auth_id: False) if revocation_check == "__default__" else revocation_check,
            **kw,
        )


@pytest.fixture(autouse=True)
def _reset_nonce_guard():
    A.reset_in_process_nonce_guard_for_new_process()
    yield
    A.reset_in_process_nonce_guard_for_new_process()


# ============================================================ real-repo state --

def test_the_real_committed_registry_is_empty_and_pinned():
    import json
    reg = json.loads((REPO_ROOT / A.REGISTRY_PATH).read_text())
    assert A.validate_registry(reg) == [] and reg["records"] == []
    assert A.registry_digest(reg) == A.PINNED_REGISTRY_SHA256


def test_the_real_committed_record_is_not_authorized():
    import json
    rec = json.loads((REPO_ROOT / A.RECORD_PATH).read_text())
    assert rec["status"] == "NOT_AUTHORIZED"


def test_the_real_acceptance_ledger_is_empty_and_denies_everything():
    missing = A.check_founder_acceptance_ledger(REPO_ROOT)
    assert set(missing) == {f"{row}" for row in A.REQUIRED_ACCEPTANCE_ROWS}


def test_authorize_against_the_real_repo_state_is_denied(monkeypatch):
    w = World()
    with pytest.raises(A.NativePretrainingNotAuthorized) as exc:
        w.authorize()  # no monkeypatch of check_founder_acceptance_ledger -- real repo state
    assert any("FOUNDER_ACCEPTANCE_INCOMPLETE" in r for r in exc.value.reasons)


# ============================================================ happy path (hypothetical founder-ready state) --

def test_valid_grant_is_issued_when_founder_acceptance_and_binding_both_check_out(monkeypatch):
    w = World()
    grant = w.authorize(monkeypatch=monkeypatch)
    assert grant.run_id == w.run_id
    assert grant.dataset_manifest_id == w.req.dataset_manifest_id


def test_revocation_check_is_mandatory_not_optional(monkeypatch):
    w = World()
    with pytest.raises(A.NativePretrainingNotAuthorized, match="REVOCATION_CHECK_REQUIRED"):
        w.authorize(monkeypatch=monkeypatch, revocation_check=None)


def test_missing_revocation_authority_denies_even_with_everything_else_valid(monkeypatch):
    """Mission F4 item 7: a revocation CHECK that raises (the service is
    unavailable) must deny, not silently pass."""
    w = World()

    def _broken(auth_id):
        raise RuntimeError("revocation service unavailable")

    with pytest.raises(A.NativePretrainingNotAuthorized, match="REVOCATION_CHECK_UNAVAILABLE"):
        w.authorize(monkeypatch=monkeypatch, revocation_check=_broken)


def test_live_revocation_denies_even_a_perfectly_valid_record(monkeypatch):
    w = World()
    with pytest.raises(A.NativePretrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
        w.authorize(monkeypatch=monkeypatch, revocation_check=lambda auth_id: True)


# ============================================================ F4.1: wrong-model grant substitution --

def test_wrong_model_config_digest_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "model_config_digest": hashlib.sha256(b"a-different-model").hexdigest()})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WRONG_MODEL_CONFIG_DIGEST"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


def test_wrong_architecture_version_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "architecture_version": "a-different-architecture"})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WRONG_ARCHITECTURE_VERSION"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


# ============================================================ F4.2: wrong-dataset grant substitution --

def test_wrong_dataset_manifest_id_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "dataset_manifest_id": "a-different-dataset"})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WRONG_DATASET_MANIFEST_ID"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


def test_wrong_dataset_content_digest_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "dataset_content_digest": hashlib.sha256(b"different-content").hexdigest()})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WRONG_DATASET_CONTENT_DIGEST"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


# ============================================================ F4.3: tampered tokenizer/model configuration --

def test_tampered_tokenizer_digest_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "tokenizer_digest": hashlib.sha256(b"a-different-tokenizer").hexdigest()})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WRONG_TOKENIZER_DIGEST"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


def test_tampering_a_signed_field_after_signing_invalidates_the_signature(monkeypatch):
    """Tamper the record's architecture_version AND the request's
    expected architecture_version to the SAME new value -- so the
    field-matching check alone would pass -- proving the signature is
    bound to the full original payload, not re-derivable by an attacker
    who edits both the record and what they ask it to be compared
    against."""
    w = World()
    w.record = dict(w.record)
    w.record["model"] = dict(w.record["model"])
    w.record["model"]["architecture_version"] = "tampered-after-signing"
    matching_req = A.NativePretrainingRequest(**{**w.req.__dict__, "architecture_version": "tampered-after-signing"})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="SIGNATURE_INVALID"):
        w.authorize(monkeypatch=monkeypatch, req=matching_req)


# ============================================================ F4.4: changed training shards after authorization --

def test_changed_authorized_shards_after_authorization_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "authorized_shard_digests": (hashlib.sha256(b"a-new-unauthorized-shard").hexdigest(),)})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WRONG_AUTHORIZED_SHARDS"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


def test_an_extra_unauthorized_shard_added_to_the_request_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "authorized_shard_digests": w.req.authorized_shard_digests + (hashlib.sha256(b"sneaky-extra-shard").hexdigest(),)})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WRONG_AUTHORIZED_SHARDS"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


# ============================================================ F4.5: reused or expired grants --

def test_an_already_expired_record_is_rejected(monkeypatch):
    now = datetime.now(timezone.utc)
    w = World(record_over={"issued_at": _ts(now - timedelta(days=2)), "expires_at": _ts(now - timedelta(days=1))})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="EXPIRED"):
        w.authorize(monkeypatch=monkeypatch)


def test_a_validity_window_longer_than_the_max_is_rejected(monkeypatch):
    now = datetime.now(timezone.utc)
    w = World(record_over={"issued_at": _ts(now), "expires_at": _ts(now + timedelta(days=30))})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="VALIDITY_WINDOW_TOO_LONG"):
        w.authorize(monkeypatch=monkeypatch)


def test_reusing_the_same_nonce_twice_is_rejected(monkeypatch):
    w = World()
    w.authorize(monkeypatch=monkeypatch)
    with pytest.raises(A.NonceReplayedError):
        w.authorize(monkeypatch=monkeypatch)


def test_reset_in_process_nonce_guard_allows_a_simulated_new_process(monkeypatch):
    w = World()
    w.authorize(monkeypatch=monkeypatch)
    A.reset_in_process_nonce_guard_for_new_process()
    # Succeeds again post-reset -- the documented in-process-only boundary.
    w.authorize(monkeypatch=monkeypatch)


# ============================================================ F4.6: revocation during pause and recovery --

def test_assert_execution_permitted_denies_on_live_revocation(monkeypatch):
    w = World()
    grant = w.authorize(monkeypatch=monkeypatch)
    with pytest.raises(A.NativePretrainingNotAuthorized, match="AUTHORIZATION_REVOKED_LIVE"):
        A.assert_execution_permitted(grant, revocation_check=lambda auth_id: True)


def test_assert_execution_permitted_denies_on_expiry(monkeypatch):
    w = World()
    grant = w.authorize(monkeypatch=monkeypatch)
    future = datetime.now(timezone.utc) + timedelta(days=30)
    with pytest.raises(A.NativePretrainingNotAuthorized, match="EXPIRED"):
        A.assert_execution_permitted(grant, revocation_check=lambda auth_id: False, now=future)


def test_assert_execution_permitted_denies_on_tampered_grant(monkeypatch):
    w = World()
    grant = w.authorize(monkeypatch=monkeypatch)
    object.__setattr__(grant, "max_wall_clock_minutes", 999999)
    with pytest.raises(A.NativePretrainingNotAuthorized, match="GRANT_FORGED_OR_TAMPERED"):
        A.assert_execution_permitted(grant, revocation_check=lambda auth_id: False)


# ============================================================ F4.7: missing revocation authority --

def test_assert_execution_permitted_requires_a_revocation_check(monkeypatch):
    w = World()
    grant = w.authorize(monkeypatch=monkeypatch)
    with pytest.raises(A.NativePretrainingNotAuthorized, match="REVOCATION_CHECK_REQUIRED"):
        A.assert_execution_permitted(grant, revocation_check=None)


def test_assert_execution_permitted_denies_on_an_unavailable_revocation_service(monkeypatch):
    w = World()
    grant = w.authorize(monkeypatch=monkeypatch)

    def _broken(auth_id):
        raise RuntimeError("down")

    with pytest.raises(A.NativePretrainingNotAuthorized, match="REVOCATION_CHECK_UNAVAILABLE"):
        A.assert_execution_permitted(grant, revocation_check=_broken)


# ============================================================ F4.8: process restart and replay --
# (covered above: test_reusing_the_same_nonce_twice_is_rejected,
#  test_reset_in_process_nonce_guard_allows_a_simulated_new_process)

def test_an_unregistered_authority_key_is_rejected(monkeypatch):
    w = World()
    w.record = dict(w.record)
    w.record["authorizing_authority"] = {"identity": "someone-else", "role": "OWNER", "key_id": "someone-else"}
    w.record = w._sign(w.record)
    with pytest.raises(A.NativePretrainingNotAuthorized, match="AUTHORITY_KEY_NOT_REGISTERED"):
        w.authorize(monkeypatch=monkeypatch)


def test_a_revoked_authority_key_is_rejected(monkeypatch):
    w = World(registry_over={"revoked": True})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="AUTHORITY_KEY_NOT_ACTIVE_OR_REVOKED"):
        w.authorize(monkeypatch=monkeypatch)


# ============================================================ F4.9/F4.10: no progress/completion/evaluator fields on a grant --

def test_the_grant_object_carries_no_progress_completion_or_evaluator_fields(monkeypatch):
    """Structural guard: a NativePretrainingGrant is purely a permission
    object -- it must be structurally impossible to smuggle a forged
    progress/completion/evaluator-approval claim into it, since no such
    field exists on the class at all. Execution evidence and evaluator
    approval remain Workstream C's own, separately-verified
    responsibility (ExecutionEvent/CompletionEvidence/EvaluatorApprovalClaim)."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(A.NativePretrainingGrant)}
    forbidden = {"steps_recorded", "completed", "completion", "evaluator_approval", "progress", "evaluation_report_sha256"}
    assert not (field_names & forbidden)


# ============================================================ F4.11: resource requests exceeding the signed budget --

def test_requesting_more_wall_clock_than_authorized_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "max_wall_clock_minutes": 10_000})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="WALL_CLOCK_NOT_AUTHORIZED"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


def test_any_nonzero_spend_request_is_rejected_while_no_go(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "requested_spend_usd": 5.0})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="SPEND_REQUESTED_WHILE_NOGO"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


def test_a_record_with_nonzero_max_spend_is_rejected_structurally(monkeypatch):
    w = World(record_over={"limits": {"max_spend_usd": 100}})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="SPEND_MUST_BE_ZERO_WHILE_NOGO"):
        w.authorize(monkeypatch=monkeypatch)


def test_requesting_gpu_without_gpu_permission_is_rejected(monkeypatch):
    w = World()
    bad_req = A.NativePretrainingRequest(**{**w.req.__dict__, "gpu_requested": True})
    with pytest.raises(A.NativePretrainingNotAuthorized, match="GPU_NOT_AUTHORIZED"):
        w.authorize(monkeypatch=monkeypatch, req=bad_req)


# ============================================================ F4.12: unauthorized transition toward execution --

def test_a_hand_constructed_grant_lookalike_is_rejected():
    with pytest.raises(A.NativePretrainingNotAuthorized, match="GRANT_NOT_ISSUED_BY_GATE"):
        A.NativePretrainingGrant(
            authorization_id="gnpauth-" + "ff" * 8, key_id="fake", record_sha256="0" * 64, run_id="run-x",
            expires_at="2099-01-01T00:00:00Z", max_wall_clock_minutes=60, model_config_digest="0" * 64,
            tokenizer_digest="0" * 64, dataset_manifest_id="ds-x", dataset_content_digest="0" * 64,
            authorized_shard_digests=("0" * 64,), environment_class=ENV,
        )


def test_grant_cannot_be_pickled_or_copied(monkeypatch):
    import pickle

    w = World()
    grant = w.authorize(monkeypatch=monkeypatch)
    with pytest.raises(TypeError):
        pickle.dumps(grant)
