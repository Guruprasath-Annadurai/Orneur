"""Protected-evaluation access control (SYNTHETIC registries in temp dirs; the repository's real registries are only READ in the last section).

Every denial case below must raise AccessDeniedError carrying a specific reason code; the baseline case proves the fixture itself can succeed (otherwise
'denied' would be vacuous).
"""
import json
import sqlite3
import sys
from datetime import timedelta

import pytest

from orca.eval.genesis_v2 import ledger as LG
from orca.eval.genesis_v2 import spec
from orca.evalinfra.access import Grant
from orca.evalinfra.errors import AccessDeniedError
from orca.evalinfra.private_store import GuardedReader, SyntheticMemoryStore
from tests.evalinfra_helpers import CORPUS, NOW, ROOT, build_world, keypair, ts


def reasons(world, req=None, **gate_over):
    with pytest.raises(AccessDeniedError) as e:
        world.gate(**gate_over).authorize(req or world.request())
    return e.value.reasons


def has(rs, prefix):
    return any(r.startswith(prefix) for r in rs)


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path)


def test_baseline_synthetic_world_can_succeed_and_grant_is_ledgered(world):
    g = world.gate()
    grant = g.authorize(world.request())
    assert isinstance(grant, Grant) and grant.ledger_seq == 0
    assert g.check_grant(grant, split="QUALIFICATION_HOLDOUT", corpus_digest=CORPUS) == []
    assert LG.AccessLedger(world.ledger_dir, {}, freeze={"frozen": True}).verify_chain(g.anchor) == 1


# ------------------------------------------------------------------------------------------------ identity / runner
def test_unregistered_runner_denied(world):
    assert "RUNNER_NOT_REGISTERED" in reasons(world, world.request(runner_id="intruder"))


@pytest.mark.parametrize("state", ["REGISTERED_NOT_AUTHORIZED", "REVOKED"])
def test_runner_not_authorized_denied(tmp_path, state):
    w = build_world(tmp_path, runner_state=state)
    assert f"RUNNER_NOT_AUTHORIZED:{state}" in reasons(w)


def test_runner_code_drift_and_scope_mismatch_denied(world):
    assert "RUNNER_CODE_MISMATCH" in reasons(world, world.request(code_sha256="b" * 64))
    assert "RUNNER_SCOPE_MISMATCH" in reasons(world, world.request(purpose=spec.PURPOSE_RETIREMENT))


def test_unreadable_runner_registry_denied(world):
    world.runner_doc_path.write_text("{not json")
    assert "RUNNER_REGISTRY_UNAVAILABLE" in reasons(world)


# ------------------------------------------------------------------------------------------------ authorization record
def test_missing_not_authorized_and_unsigned_authorization_denied(world):
    assert "AUTHORIZATION_MISSING" in reasons(world, world.request(authorization_record=None))
    from orca.eval.genesis_v2 import authorization as A
    assert has(reasons(world, world.request(authorization_record=A.default_record())), "AUTHORIZATION:NOT_AUTHORIZED")
    assert has(reasons(world, world.request(authorization_record=world.auth(signature="00" * 64, _sign=False))), "AUTHORIZATION:SIGNATURE_INVALID")


def test_signature_by_unregistered_key_denied(world):
    other_sk, _ = keypair()
    r = world.auth(_sign=False)
    from orca.eval.genesis_v2 import authorization as A
    r["signature"] = other_sk.sign(A.canonical_signing_bytes(r)).hex()
    assert has(reasons(world, world.request(authorization_record=r)), "AUTHORIZATION:SIGNATURE_INVALID")


def test_tampered_after_signing_denied(world):
    r = world.auth()
    r["max_runs"] = 99
    assert has(reasons(world, world.request(authorization_record=r)), "AUTHORIZATION:SIGNATURE_INVALID")


def test_expired_and_not_yet_valid_authorization_denied(world):
    exp = world.auth(issued_at=ts(NOW - timedelta(days=3)), expires_at=ts(NOW - timedelta(days=1)))
    assert has(reasons(world, world.request(authorization_record=exp)), "AUTHORIZATION:AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
    fut = world.auth(issued_at=ts(NOW + timedelta(days=1)), expires_at=ts(NOW + timedelta(days=2)))
    assert has(reasons(world, world.request(authorization_record=fut)), "AUTHORIZATION:AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")


def test_wrong_candidate_commit_stage_denied(world):
    assert has(reasons(world, world.request(candidate_model_id="other")), "AUTHORIZATION:WRONG_CANDIDATE")
    assert has(reasons(world, world.request(commit_sha="c" * 40)), "AUTHORIZATION:WRONG_COMMIT_SHA")
    assert has(reasons(world, world.request(stage="STAGE_1")), "AUTHORIZATION:WRONG_STAGE")


def test_non_dispatch_event_denied(world):
    assert has(reasons(world, world.request(event_name="push")), "AUTHORIZATION:EVENT_NOT_EXPLICIT_DISPATCH")


def test_revoked_authority_key_denied(world):
    doc = json.loads(world.authority_path.read_text())
    doc["records"][0]["revoked"] = True
    world.authority_path.write_text(json.dumps(doc))
    rs = reasons(world)
    assert has(rs, "AUTHORIZATION:NO_TRUSTED_AUTHORITY_KEY_REGISTERED")


def test_expired_authority_key_denied(world):
    doc = json.loads(world.authority_path.read_text())
    doc["records"][0]["expiry"] = ts(NOW - timedelta(hours=1))
    world.authority_path.write_text(json.dumps(doc))
    assert has(reasons(world), "AUTHORIZATION:NO_TRUSTED_AUTHORITY_KEY_REGISTERED")


def test_authority_scope_mismatch_denied(world):
    doc = json.loads(world.authority_path.read_text())
    doc["records"][0]["permitted_eval_stages"] = ["STAGE_1"]
    world.authority_path.write_text(json.dumps(doc))
    assert "AUTHORITY_SCOPE_MISMATCH" in reasons(world)


def test_empty_or_missing_authority_registry_denied(tmp_path):
    w = build_world(tmp_path, with_authority=False)
    assert has(reasons(w), "AUTHORIZATION:NO_TRUSTED_AUTHORITY_KEY_REGISTERED")
    w.authority_path.unlink()
    assert "AUTHORITY_REGISTRY_UNAVAILABLE" in reasons(w)


def test_revoked_authorization_id_and_unavailable_revocation_list_denied(world):
    assert "AUTHORIZATION_REVOKED" in reasons(world, revoked_authorization_ids=["auth-" + "0f" * 8])
    assert "REVOCATION_LIST_UNAVAILABLE" in reasons(world, revoked_authorization_ids=None)


def test_replayed_authorization_denied(world):
    g = world.gate()
    g.authorize(world.request(run_id="run-1"))
    # a different run id under the SAME single-use authorization
    with pytest.raises(AccessDeniedError) as e:
        g.authorize(world.request(run_id="run-2", candidate_lineage="lin-2"))
    assert "AUTHORIZATION_REPLAYED" in e.value.reasons
    # the very same run id again
    with pytest.raises(AccessDeniedError) as e:
        world.gate(expected_ledger_head=g.anchor).authorize(world.request(run_id="run-1"))
    assert "AUTHORIZATION_REPLAYED" in e.value.reasons


def test_tampered_replay_log_denied(world):
    g = world.gate()
    g.authorize(world.request())
    world.replay.write_text(world.replay.read_text().replace("run-1", "run-9"))
    assert "REPLAY_LOG_CORRUPT" in reasons(world, expected_ledger_head=g.anchor)


# ------------------------------------------------------------------------------------------------ ledger
def test_missing_ledger_anchor_denied(world):
    assert "LEDGER_ANCHOR_UNAVAILABLE" in reasons(world, expected_ledger_head=None)


def test_fabricated_grant_with_no_ledger_entry_is_denied_at_use(world):
    g = world.gate()
    real = g.authorize(world.request())
    fake = Grant("run-never-recorded", real.split, real.corpus_digest, 5, "9" * 64, real.authorization_id, real.runner_id, real.ledger_head_after)
    assert g.check_grant(fake, split=real.split, corpus_digest=real.corpus_digest) == ["LEDGER_ENTRY_MISSING"]
    store = SyntheticMemoryStore(configured=True)
    digest = store.write_corpus("gce2c-" + "ab" * 8, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    reader = GuardedReader(store, grant_checker=g.check_grant)
    with pytest.raises(AccessDeniedError) as e:
        reader.read_split(fake, "gce2c-" + "ab" * 8, "QUALIFICATION_HOLDOUT", expected_corpus_digest=digest)
    assert "LEDGER_ENTRY_MISSING" in e.value.reasons
    with pytest.raises(AccessDeniedError):
        reader.read_split(None, "gce2c-" + "ab" * 8, "QUALIFICATION_HOLDOUT", expected_corpus_digest=digest)


def test_grant_for_other_split_or_digest_denied(world):
    g = world.gate()
    real = g.authorize(world.request())
    assert "GRANT_SCOPE_MISMATCH" in g.check_grant(real, split="SCREEN", corpus_digest=real.corpus_digest)
    assert "GRANT_SCOPE_MISMATCH" in g.check_grant(real, split=real.split, corpus_digest="1" * 64)


def _tamper_ledger(world):
    c = sqlite3.connect(world.ledger_dir / "ledger.sqlite3")
    c.execute("DROP TRIGGER records_no_update")
    c.execute("UPDATE records SET body = replace(body, 'run-1', 'run-X') WHERE seq = 0")
    c.commit()
    c.close()


def test_tampered_ledger_chain_denies_new_access_and_existing_grants(world):
    g = world.gate()
    grant = g.authorize(world.request())
    _tamper_ledger(world)
    with pytest.raises(AccessDeniedError) as e:
        g.authorize(world.request(run_id="run-2", authorization_record=world.auth(authorization_id="auth-" + "1e" * 8)))
    assert has(e.value.reasons, "LEDGER_TAMPERED")
    assert has(g.check_grant(grant, split=grant.split, corpus_digest=grant.corpus_digest), "LEDGER_TAMPERED")


def test_ledger_rollback_or_truncation_detected_by_anchor(world):
    g = world.gate()
    g.authorize(world.request())
    stale_new_ledger = world.ledger_dir.parent / "other_ledger"
    from orca.evalinfra.access import ProtectedEvalGate
    gate2 = ProtectedEvalGate(world.root, stale_new_ledger, world.replay.parent / "r2.jsonl", env=world.env, expected_corpus_digest=CORPUS,
                              revoked_authorization_ids=[], freeze={"frozen": True}, now=NOW, expected_ledger_head=g.anchor)
    with pytest.raises(AccessDeniedError) as e:
        gate2.authorize(world.request(run_id="run-3"))
    assert has(e.value.reasons, "LEDGER_TAMPERED")


def test_not_frozen_denies_without_burning_the_authorization(world):
    assert "EVAL_NOT_FROZEN" in reasons(world, freeze={"frozen": False})
    assert not world.replay.exists() or world.replay.read_text() == ""
    assert world.gate().authorize(world.request()).run_id == "run-1"            # the same single-use authorization is still usable


def test_second_qualification_of_same_lineage_denied_by_write_once_ledger(world):
    g = world.gate()
    g.authorize(world.request())
    r2 = world.request(run_id="run-2", authorization_record=world.auth(authorization_id="auth-" + "1e" * 8))
    with pytest.raises(AccessDeniedError) as e:
        g.authorize(r2)
    assert "LEDGER:HOLDOUT_ALREADY_OPENED" in e.value.reasons


# ------------------------------------------------------------------------------------------------ secrets / reviewers / signatures / commitments unavailable
def test_missing_secret_or_store_denied(tmp_path):
    w = build_world(tmp_path, env_ok=False)
    assert "SECRET_OR_STORE_UNAVAILABLE" in reasons(w)
    w2 = build_world(tmp_path / "b")
    env = dict(w2.env)
    env.pop(spec.VAULT_PRIVATE_KEY_ENV)
    assert "SECRET_OR_STORE_UNAVAILABLE" in reasons(w2, env=env)
    env2 = dict(w2.env)
    env2[spec.VAULT_PRIVATE_KEY_ENV] = "not-hex"
    assert "SECRET_OR_STORE_UNAVAILABLE" in reasons(w2, env=env2)


def test_gate_never_reads_the_process_environment_by_default(world, monkeypatch):
    monkeypatch.setenv(spec.VAULT_PRIVATE_KEY_ENV, "ab" * 32)
    monkeypatch.setenv(spec.STORE_ENV, "ENCRYPTED_ARTIFACT:/somewhere")
    from orca.evalinfra.access import ProtectedEvalGate
    g = ProtectedEvalGate(world.root, world.ledger_dir, world.replay, expected_corpus_digest=CORPUS, revoked_authorization_ids=[], freeze={"frozen": True},
                          now=NOW, expected_ledger_head={"seq": -1, "record_hash": LG.GENESIS_HASH})
    with pytest.raises(AccessDeniedError) as e:
        g.authorize(world.request())
    assert "SECRET_OR_STORE_UNAVAILABLE" in e.value.reasons


def test_no_reviewers_denied(tmp_path):
    w = build_world(tmp_path, with_reviewer=False)
    rs = reasons(w)
    assert "NO_ACTIVE_REVIEWER" in rs and has(rs, "REVIEW_MANIFEST_INVALID:NO_TRUSTED_REVIEWER_KEY_REGISTERED")


def test_missing_unregistered_or_negative_review_denied(world):
    assert "REVIEW_MANIFEST_MISSING" in reasons(world, world.request(reviewer_manifest=None))
    other, _ = keypair()
    assert has(reasons(world, world.request(reviewer_manifest=world.manifest(signer=other))), "REVIEW_MANIFEST_INVALID:SIGNATURE_INVALID")
    assert has(reasons(world, world.request(reviewer_manifest=world.manifest(reviewer_key_id="ghost"))), "REVIEW_MANIFEST_INVALID:REVIEWER_KEY_NOT_REGISTERED")
    assert "REVIEW_NOT_CLEAR" in reasons(world, world.request(reviewer_manifest=world.manifest(disposition="REJECT_CONTAMINATED")))
    assert has(reasons(world, world.request(reviewer_manifest=world.manifest(corpus="3" * 64))), "REVIEW_MANIFEST_INVALID:CORPUS_DIGEST_MISMATCH")


def test_too_few_distinct_reviewers_denied(world):
    assert "REVIEWS_INSUFFICIENT" in reasons(world, min_clear_reviewers=2)


def test_dual_role_authority_and_reviewer_denied(world):
    doc = json.loads(world.reviewer_path.read_text())
    adoc = json.loads(world.authority_path.read_text())
    doc["records"][0]["id"] = "syn-authority"
    world.reviewer_path.write_text(json.dumps(doc))
    rs = reasons(world, world.request(reviewer_manifest=world.manifest(reviewer_key_id="syn-authority")))
    assert "DUAL_ROLE_VIOLATION" in rs and adoc["records"][0]["id"] == "syn-authority"


def test_signature_verifier_unavailable_denies(world, monkeypatch):
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.asymmetric.ed25519", None)
    rs = reasons(world)
    assert "AUTHORIZATION:SIGNATURE_VERIFIER_UNAVAILABLE" in rs and "REVIEW_MANIFEST_INVALID:SIGNATURE_VERIFIER_UNAVAILABLE" in rs


def test_dataset_commitment_unavailable_or_mismatched_denied(world):
    assert "DATASET_COMMITMENT_UNAVAILABLE" in reasons(world, expected_corpus_digest=None)
    assert "DATASET_COMMITMENT_UNAVAILABLE" in reasons(world, expected_corpus_digest="short")
    assert "DATASET_COMMITMENT_MISMATCH" in reasons(world, expected_corpus_digest="2" * 64)


def test_every_gate_is_evaluated_not_short_circuited(tmp_path):
    w = build_world(tmp_path, runner_state="REVOKED", with_reviewer=False, env_ok=False)
    rs = reasons(w, w.request(authorization_record=None, reviewer_manifest=None), expected_corpus_digest=None, expected_ledger_head=None, freeze={"frozen": False})
    for want in ("RUNNER_NOT_AUTHORIZED:REVOKED", "AUTHORIZATION_MISSING", "NO_ACTIVE_REVIEWER", "REVIEW_MANIFEST_MISSING", "DATASET_COMMITMENT_UNAVAILABLE",
                 "SECRET_OR_STORE_UNAVAILABLE", "EVAL_NOT_FROZEN", "LEDGER_ANCHOR_UNAVAILABLE"):
        assert want in rs


# ------------------------------------------------------------------------------------------------ the repository's real committed state (read only)
def test_real_repository_state_denies_everything(tmp_path):
    from orca.evalinfra.access import ProtectedAccessRequest, ProtectedEvalGate
    from tests.evalinfra_helpers import CODE
    g = ProtectedEvalGate(ROOT, tmp_path / "ledger", tmp_path / "replay.jsonl", env={}, expected_corpus_digest=None, revoked_authorization_ids=None,
                          expected_ledger_head=None)
    req = ProtectedAccessRequest(runner_id="any", code_sha256=CODE, purpose=spec.PURPOSE_QUALIFICATION, split="QUALIFICATION_HOLDOUT", corpus_digest=CORPUS, run_id="r",
                                 candidate_model_id="m", candidate_revision="v", candidate_lineage="l", commit_sha="a" * 40, authorization_purpose="QUALIFICATION",
                                 stage="STAGE_2", runner_class="SELF_HOSTED_CPU", timestamp_utc="2026-10-11T00:00:00Z")
    with pytest.raises(AccessDeniedError) as e:
        g.authorize(req)
    for want in ("RUNNER_NOT_REGISTERED", "AUTHORIZATION_MISSING", "NO_ACTIVE_REVIEWER", "REVIEW_MANIFEST_MISSING", "SECRET_OR_STORE_UNAVAILABLE", "EVAL_NOT_FROZEN"):
        assert want in e.value.reasons
    committed = json.loads((ROOT / "docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json").read_text())
    assert committed["status"] == "NOT_AUTHORIZED" and committed["max_runs"] == 0
    assert json.loads((ROOT / "docs/orneur/authorization/REVIEWER_REGISTRY.json").read_text())["records"] == []
