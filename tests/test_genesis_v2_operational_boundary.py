"""The composed operational boundary every future corpus-generation entry point must call. Tests explicit bypass
attempts: a valid corpus-generation authorization alone is not enough (runner must also be AUTHORIZED); an
AUTHORIZED-looking runner alone is not enough (a signed authorization is still required); a stale/mismatched
execution context is not enough even with both."""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
from orca.eval.genesis_v2 import inventory as INV
from orca.eval.genesis_v2 import operational_boundary as OB
from orca.eval.genesis_v2 import prereg as PR
from orca.eval.genesis_v2 import runner_registry as RN

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- against the real, current repo
def test_the_real_committed_repo_denies_corpus_generation_right_now():
    result = OB.check_authorization(ROOT, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch")
    assert result.authorized is False
    assert any("NOT_AUTHORIZED" in r for r in result.reasons)
    with pytest.raises(OB.CorpusGenerationNotAuthorized):
        OB.require_authorization(ROOT, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch")


def test_check_authorization_never_raises_on_the_real_repo():
    # a read-only inspection call must never raise even though the request is denied
    r = OB.check_authorization(ROOT, requested_scope=("QUALIFICATION_HOLDOUT",), event_name="push")
    assert isinstance(r, OB.BoundaryResult) and r.authorized is False


# ---------------------------------------------------------------- isolated temp-repo bypass attempts
@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    shutil.copytree(ROOT / "docs" / "orneur", r / "docs" / "orneur")
    return r


def _real_context():
    inv = json.loads((ROOT / INV.INVENTORY_PATH).read_text())
    inv_digest = INV.inventory_digest(inv)
    draft = json.loads((ROOT / PR.DRAFT_PATH).read_text())
    prereg_sha = draft["record_sha256"]
    return inv_digest, prereg_sha


def _git_init_with_head(repo_dir: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "snap"], cwd=repo_dir, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()


def _write_signed_cga(repo_dir: Path, sk, commit_sha: str, inv_digest: str, prereg_sha: str, **over):
    rec = CGA.default_record()
    rec.update({"authorization_id": "cgauth-" + "ef" * 8, "status": "AUTHORIZED", "purpose": CGA.PURPOSE,
                "authorized_scope": ["PILOT_TRAIN"], "authorized_commit_sha": commit_sha,
                "authorized_artifact_digests": {"corpus_inventory_digest": inv_digest, "preregistration_record_sha256": prereg_sha},
                "issued_at": ts(NOW - timedelta(hours=1)), "expires_at": ts(NOW + timedelta(days=1)),
                "authorizing_authority": {"identity": "orneur-owner-authority-1", "role": "OWNER", "key_id": "orneur-owner-authority-1"}})
    rec.update(over)
    rec["signature"] = sk.sign(CGA.canonical_signing_bytes(rec)).hex()
    (repo_dir / CGA.RECORD_PATH).write_text(json.dumps(rec))
    return rec


def _write_authority_registry_with_real_key(repo_dir: Path, sk):
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    from orca.eval.genesis_v2 import authority_registry as AR
    doc = {"schema_version": AR.SCHEMA_VERSION, "records": [{
        "id": "orneur-owner-authority-1", "role": "OWNER", "public_key_hex": pub,
        "activation_timestamp": ts(NOW - timedelta(days=1)), "expiry": None, "revoked": False,
        "permitted_authorization_classes": list(AR.AUTHORIZATION_CLASSES), "permitted_eval_stages": ["STAGE_1", "STAGE_2"],
        "gpu_permission": False, "spend_permission": False, "provider_inference_permission": False}]}
    (repo_dir / AR.REGISTRY_PATH).write_text(json.dumps(doc))


def test_bypass_attempt_valid_authorization_alone_is_not_enough_without_an_authorized_runner(repo):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha = _real_context()
    commit_sha = _git_init_with_head(repo)
    _write_signed_cga(repo, sk, commit_sha, inv_digest, prereg_sha)
    # runner registry still says REGISTERED_NOT_AUTHORIZED (the real committed state, copied by fixture) — must still deny.
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW)
    assert result.authorized is False
    assert any("RUNNER_NOT_AUTHORIZED" in r for r in result.reasons)
    with pytest.raises(OB.CorpusGenerationNotAuthorized):
        OB.require_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW)


def test_bypass_attempt_authorized_runner_alone_is_not_enough_without_a_signed_authorization(repo):
    reg_path = repo / RN.REGISTRY_PATH
    doc = json.loads(reg_path.read_text())
    doc["records"][0]["state"] = "AUTHORIZED"   # simulate a runner someone flipped to AUTHORIZED
    reg_path.write_text(json.dumps(doc))
    commit_sha = _git_init_with_head(repo)
    # CORPUS_GENERATION_AUTHORIZATION.json is still the real committed NOT_AUTHORIZED record (copied by fixture).
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW,
                                     runner_id=doc["records"][0]["runner_id"])
    assert result.authorized is False
    assert any("NOT_AUTHORIZED" in r for r in result.reasons)
    assert result.runner_authorized is True   # confirms the runner check alone WAS satisfied — the CGA check is what blocks it


def test_bypass_attempt_stale_context_denied_even_with_both_pieces_present(repo):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha = _real_context()
    commit_sha = _git_init_with_head(repo)
    reg_path = repo / RN.REGISTRY_PATH
    doc = json.loads(reg_path.read_text())
    doc["records"][0]["state"] = "AUTHORIZED"
    reg_path.write_text(json.dumps(doc))
    # signed for a DIFFERENT commit than the one actually checked out — the classic stale/replayed-authorization case
    _write_signed_cga(repo, sk, "0" * 40, inv_digest, prereg_sha)
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW)
    assert result.authorized is False
    assert any("COMMIT_SHA_MISMATCH" in r for r in result.reasons)


def test_full_positive_path_through_the_real_boundary_composition(repo):
    """Only when EVERY gate genuinely passes does the composed boundary authorize -- proves the positive path exists
    and is reachable, not just that denials work."""
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha = _real_context()
    commit_sha = _git_init_with_head(repo)
    _write_signed_cga(repo, sk, commit_sha, inv_digest, prereg_sha)
    reg_path = repo / RN.REGISTRY_PATH
    doc = json.loads(reg_path.read_text())
    doc["records"][0]["state"] = "AUTHORIZED"
    reg_path.write_text(json.dumps(doc))
    result = OB.require_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW,
                                       runner_id=doc["records"][0]["runner_id"])
    assert result.authorized is True and result.runner_authorized is True and result.reasons == []
