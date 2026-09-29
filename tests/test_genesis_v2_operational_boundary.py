"""The composed operational boundary every future corpus-generation entry point must call. Tests explicit bypass
attempts: a valid corpus-generation authorization alone is not enough (a SEPARATE generator identity must also be
AUTHORIZED); an AUTHORIZED-looking generator alone is not enough (a signed authorization is still required); a
stale/rolled-back execution context, a dirty working tree, or drifted code are not enough even with both. Also
covers the separate, later-stage require_private_split_access() gate through the real AccessLedger."""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
from orca.eval.genesis_v2 import generator_registry as GR
from orca.eval.genesis_v2 import inventory as INV
from orca.eval.genesis_v2 import ledger as LG
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
    r = OB.check_authorization(ROOT, requested_scope=("QUALIFICATION_HOLDOUT",), event_name="push")
    assert isinstance(r, OB.BoundaryResult) and r.authorized is False


def test_event_name_defaults_to_trusted_environment_evidence_not_a_bare_default(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert OB._trusted_event_name(None) == "push"                  # no caller-supplied value: reads real CI env evidence
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert OB._trusted_event_name(None) == "workflow_dispatch"
    assert OB._trusted_event_name("push") == "push"                # explicit override still accepted (tests only)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    assert OB._trusted_event_name(None) == ""                      # absent env evidence -> empty, never a silent pass


# ---------------------------------------------------------------- isolated temp-repo bypass attempts
@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    shutil.copytree(ROOT / "docs" / "orneur", r / "docs" / "orneur")
    (r / "orca" / "eval" / "genesis_v2").mkdir(parents=True)
    for f in (ROOT / "orca" / "eval" / "genesis_v2").glob("*.py"):
        shutil.copy(f, r / "orca" / "eval" / "genesis_v2" / f.name)
    return r


def _real_context():
    inv = json.loads((ROOT / INV.INVENTORY_PATH).read_text())
    inv_digest = INV.inventory_digest(inv)
    draft = json.loads((ROOT / PR.DRAFT_PATH).read_text())
    prereg_sha = draft["record_sha256"]
    code_hash = CGA.code_tree_sha256(ROOT)
    return inv_digest, prereg_sha, code_hash


def _git_init_with_head(repo_dir: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "snap"], cwd=repo_dir, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()


def _write_signed_cga(repo_dir: Path, sk, reviewed_sha: str, code_hash: str, inv_digest: str, prereg_sha: str, **over):
    rec = CGA.default_record()
    rec.update({"authorization_id": "cgauth-" + "ef" * 8, "status": "AUTHORIZED", "purpose": CGA.PURPOSE,
                "authorized_scope": ["PILOT_TRAIN"], "reviewed_commit_sha": reviewed_sha, "authorized_code_tree_sha256": code_hash,
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


def _authorize_generator(repo_dir: Path, code_hash: str, generator_id: str = "gen-1"):
    doc = json.loads((repo_dir / GR.REGISTRY_PATH).read_text())
    doc["records"] = [{"generator_id": generator_id, "os_runtime": "test", "code_sha256": code_hash,
                        "allowed_artifact_classes": ["PILOT_TRAIN"], "network_policy": "none",
                        "credential_scope": {"vault_write": True, "vault_read": False, "public_repo_write": False,
                                              "training_credentials": False, "unrelated_cloud_credentials": False, "developer_tokens": False},
                        "state": "AUTHORIZED"}]
    (repo_dir / GR.REGISTRY_PATH).write_text(json.dumps(doc))
    return generator_id


def test_bypass_attempt_valid_authorization_alone_is_not_enough_without_an_authorized_generator(repo):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    reviewed_sha = _git_init_with_head(repo)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha)
    # generator registry still says the real committed empty state (no records) — must still deny.
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW)
    assert result.authorized is False
    assert any("GENERATOR_NOT_AUTHORIZED" in r for r in result.reasons)
    with pytest.raises(OB.CorpusGenerationNotAuthorized):
        OB.require_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW)


def test_bypass_attempt_authorized_generator_alone_is_not_enough_without_a_signed_authorization(repo):
    _, _, code_hash = _real_context()
    gid = _authorize_generator(repo, code_hash)
    _git_init_with_head(repo)
    # CORPUS_GENERATION_AUTHORIZATION.json is still the real committed NOT_AUTHORIZED record (copied by fixture).
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert result.authorized is False
    assert any("NOT_AUTHORIZED" in r for r in result.reasons)
    assert result.generator_authorized is True   # confirms the generator check alone WAS satisfied — the CGA check is what blocks it


def test_bypass_attempt_stale_reviewed_commit_denied_when_not_an_ancestor(repo):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    _git_init_with_head(repo)
    gid = _authorize_generator(repo, code_hash)
    # signed against an unrelated commit that is NOT an ancestor of what's actually checked out
    _write_signed_cga(repo, sk, "0" * 40, code_hash, inv_digest, prereg_sha)
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert result.authorized is False
    assert any("REVIEWED_COMMIT_NOT_ANCESTOR_OF_EXECUTION" in r for r in result.reasons)


def test_bypass_attempt_dirty_working_tree_denied_even_with_everything_else_valid(repo):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    reviewed_sha = _git_init_with_head(repo)
    gid = _authorize_generator(repo, code_hash)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha)
    (repo / "uncommitted_marker.txt").write_text("dirty")   # leave the tree dirty AFTER the reviewed commit
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert result.authorized is False
    assert any("DIRTY_WORKING_TREE" in r for r in result.reasons)


def test_bypass_attempt_code_drift_after_review_denied_even_on_the_same_commit_lineage(repo):
    """The scenario the code-tree hash specifically exists to catch: the reviewed commit's code tree hash is bound,
    then a LATER commit (still a genuine descendant, still a clean tree) changes the generator code -- ancestry alone
    would accept this, but the code-tree hash must not."""
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    reviewed_sha = _git_init_with_head(repo)
    gid = _authorize_generator(repo, code_hash)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha)
    # simulate code drift: modify a generator file and commit again (a genuine descendant, clean tree)
    target = next((repo / "orca/eval/genesis_v2").glob("*.py"))
    target.write_text(target.read_text() + "\n# drifted after review\n")
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "drift"], cwd=repo, check=True)
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert result.authorized is False
    assert any("CODE_TREE_HASH_MISMATCH" in r for r in result.reasons)


def test_generator_registry_flags_an_identity_shared_with_the_qualification_runner_registry(repo):
    _, _, code_hash = _real_context()
    gid = _authorize_generator(repo, code_hash)
    reg_path = repo / RN.REGISTRY_PATH
    doc = json.loads(reg_path.read_text())
    doc["records"][0]["runner_id"] = gid   # same identity registered as BOTH roles
    reg_path.write_text(json.dumps(doc))
    gen_doc = json.loads((repo / GR.REGISTRY_PATH).read_text())
    problems = GR.validate(gen_doc, qualification_runner_doc=doc)
    assert any("registered as BOTH" in p for p in problems)


def test_full_positive_path_through_the_real_boundary_composition(repo):
    """Only when EVERY gate genuinely passes does the composed boundary authorize -- including a genuinely CLEAN
    working tree, so the signed authorization and generator registration are written and committed TOGETHER (the
    realistic case: the evidence commit that stores them is itself the clean, reviewed state)."""
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    # `reviewed_commit_sha` refers to the code tree the owner reviewed; the FIRST commit here stands in for that.
    reviewed_sha = _git_init_with_head(repo)
    gid = _authorize_generator(repo, code_hash)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha)
    # Commit the evidence (signed authorization + generator registration) so the tree is clean when checked --
    # this second commit is a genuine descendant of reviewed_sha and touches no CODE_PATHS, so the code-tree hash
    # bound at signing time is unaffected, exactly the scenario schema /2 was redesigned to support.
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "evidence"], cwd=repo, check=True)
    result = OB.require_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert result.authorized is True and result.generator_authorized is True and result.reasons == []


# ---------------------------------------------------------------- require_private_split_access() through the real ledger
def test_private_split_access_denied_without_an_authorized_qualification_runner(tmp_path):
    with pytest.raises(OB.PrivateSplitAccessDenied):
        OB.require_private_split_access(ROOT, tmp_path / "ledger", process_id="not-registered-at-all", code_sha256="a" * 64,
                                         purpose="STAGE1_SCREEN", split="SCREEN", eval_version="genesis-capability-eval/2.0.0",
                                         corpus_digest="b" * 64, run_id="run-1", candidate_revision="rev-1",
                                         candidate_lineage="lineage-1", timestamp_utc=ts(NOW))


def test_private_split_access_goes_through_the_real_ledger_and_is_denied_pre_freeze(tmp_path):
    """Even a genuinely AUTHORIZED qualification runner cannot read a private split before V2 is frozen -- the real
    ledger enforces this independently; this module does not (and must not) bypass it."""
    reg_path = tmp_path / "runner_registry.json"
    root = tmp_path / "fakeroot"
    (root / RN.REGISTRY_PATH).parent.mkdir(parents=True)
    doc = {"schema_version": RN.SCHEMA_VERSION, "records": [{
        "runner_id": "runner-1", "runner_class": "SELF_HOSTED_CPU", "os_runtime": "test", "code_sha256": "a" * 64,
        "allowed_purposes": ["STAGE1_SCREEN"], "allowed_splits": ["SCREEN"], "sandbox_image_digest": "sha256:" + "b" * 64,
        "semantic_engine_digest": "c" * 64, "storage_backend_verification_digest": "d" * 64, "ledger_database_identity_digest": "e" * 64,
        "network_policy": "none", "credential_scope": {"private_store_read": True, "public_repo_write": False, "training_credentials": False,
                                                         "unrelated_cloud_credentials": False, "developer_tokens": False}, "state": "AUTHORIZED"}]}
    (root / RN.REGISTRY_PATH).write_text(json.dumps(doc))
    with pytest.raises(OB.PrivateSplitAccessDenied):
        OB.require_private_split_access(root, tmp_path / "ledger", process_id="runner-1", code_sha256="a" * 64, purpose="STAGE1_SCREEN",
                                         split="SCREEN", eval_version="genesis-capability-eval/2.0.0", corpus_digest="b" * 64,
                                         run_id="run-1", candidate_revision="rev-1", candidate_lineage="lineage-1", timestamp_utc=ts(NOW))
