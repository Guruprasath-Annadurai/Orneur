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


def test_unset_generator_id_is_never_authenticated_even_when_exactly_one_registry_record_exists(repo):
    """Hardening: an earlier version of this check silently used 'the one record' when generator_id was omitted --
    ambient registry state (how many rows a JSON file has) is not evidence of who is executing. Even with exactly
    one AUTHORIZED record present, an unset/empty generator_id must never be treated as that identity."""
    _, _, code_hash = _real_context()
    _authorize_generator(repo, code_hash)   # exactly one record, AUTHORIZED
    _git_init_with_head(repo)
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=None)
    assert result.authorized is False
    assert result.generator_authorized is False
    assert result.generator_state is None
    with pytest.raises(OB.CorpusGenerationNotAuthorized):
        OB.require_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=None)


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


def test_code_tree_hash_does_not_cover_dependencies_outside_code_paths(repo):
    """Item 5, honestly demonstrated rather than hidden: `corpus_generation_authorization.CODE_PATHS` currently binds
    only `orca/eval/genesis_v2/`. A change to a file OUTSIDE that path -- code a real generator implementation might
    still import -- is INVISIBLE to `code_tree_sha256()`, so an authorization signed before such a change still
    verifies against it. This is the residual limitation documented in operational_boundary.py's module docstring;
    the fix, when a real generator exists, is to extend CODE_PATHS to cover everything it genuinely depends on."""
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    reviewed_sha = _git_init_with_head(repo)
    gid = _authorize_generator(repo, code_hash)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha)
    # a file OUTSIDE CODE_PATHS that a real generator could plausibly import from
    outside_dep = repo / "orca" / "eval" / "_shared_dependency_outside_code_paths.py"
    outside_dep.parent.mkdir(parents=True, exist_ok=True)
    outside_dep.write_text("def helper():\n    return 1\n")
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "add outside dependency"], cwd=repo, check=True)
    assert CGA.code_tree_sha256(repo) == code_hash   # unchanged -- the new file is invisible to this binding
    result = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert not any("CODE_TREE_HASH_MISMATCH" in r for r in result.reasons)   # the drift outside CODE_PATHS was NOT caught
    # now modify a file THAT IS covered -- this one IS caught, confirming the boundary is exactly CODE_PATHS
    target = next((repo / "orca/eval/genesis_v2").glob("*.py"))
    target.write_text(target.read_text() + "\n# drift inside CODE_PATHS\n")
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "drift inside"], cwd=repo, check=True)
    result2 = OB.check_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert any("CODE_TREE_HASH_MISMATCH" in r for r in result2.reasons)


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


# ---------------------------------------------------------------- generator allowed_artifact_classes scope enforcement
def test_generator_authorized_only_for_pilot_train_cannot_generate_screen_or_holdout(repo):
    """A real gap this round closed: a generator's OWN allowed_artifact_classes must be checked against what is
    actually being requested, independent of whatever the CORPUS_GENERATION_AUTHORIZATION record's scope says."""
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    gid = _authorize_generator(repo, code_hash)   # allowed_artifact_classes == ["PILOT_TRAIN"] only
    reviewed_sha = _git_init_with_head(repo)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha, authorized_scope=["PILOT_TRAIN", "SCREEN"])
    result = OB.check_authorization(repo, requested_scope=("SCREEN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert result.authorized is False
    assert result.generator_authorized is False
    assert result.generator_state == "REQUESTED_SCOPE_EXCEEDS_GENERATOR_ALLOWED_CLASSES"
    with pytest.raises(OB.CorpusGenerationNotAuthorized):
        OB.require_authorization(repo, requested_scope=("SCREEN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)


def test_generator_authorized_for_its_own_declared_classes_still_works(repo):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    inv_digest, prereg_sha, code_hash = _real_context()
    gid = _authorize_generator(repo, code_hash)   # allowed_artifact_classes == ["PILOT_TRAIN"]
    reviewed_sha = _git_init_with_head(repo)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "evidence"], cwd=repo, check=True)
    result = OB.require_authorization(repo, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert result.authorized is True and result.generator_authorized is True


# ---------------------------------------------------------------- GeneratorWriteHandle / protected_generate_write_handle
class _FakeWriteOnlyStore:
    """A minimal stand-in exposing ONLY write_corpus -- no read_split at all -- matching what a genuine
    store.EncryptedVaultWriter looks like (see its own tests in test_genesis_v2_storage.py for the real crypto)."""
    def __init__(self):
        self.written = []

    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        self.written.append((corpus_id, dict(splits)))
        return "gce2c-" + "a" * 16


class _FakeReadCapableStore:
    """A stand-in exposing BOTH write_corpus and read_split, used ONLY to prove GeneratorWriteHandle refuses to be
    built from it at all -- a generator's write capability must never be backed by something that could also read."""
    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        return "gce2c-" + "a" * 16

    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        raise AssertionError("read_split must never be reachable through GeneratorWriteHandle")


def test_generator_write_handle_refuses_a_read_capable_backing_store():
    """Item 3: genuine key/process isolation, not an API convention. Even before any scope check, the handle itself
    refuses to be constructed from an object that ALSO exposes read_split."""
    with pytest.raises(OB.PrivateStorageWriteHandleViolation):
        OB.GeneratorWriteHandle(_FakeReadCapableStore(), authorized_scope=frozenset({"SCREEN", "QUALIFICATION_HOLDOUT"}))


def test_generator_write_handle_exposes_only_write_corpus_and_enforces_its_own_authorized_scope():
    store = _FakeWriteOnlyStore()
    handle = OB.GeneratorWriteHandle(store, authorized_scope=frozenset({"SCREEN", "QUALIFICATION_HOLDOUT"}))
    assert not hasattr(handle, "read_split")
    digest = handle.write_corpus("gce2c-" + "0" * 16, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    assert digest.startswith("gce2c-") and store.written == [("gce2c-" + "0" * 16, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})]
    assert "write_corpus only" in repr(handle)
    # item 1: enforced at the ACTUAL write call, not merely at handle-issuance -- a handle authorized for a NARROWER
    # scope refuses a write exceeding it, even though the underlying (fake, permissive) store would accept anything.
    narrow_store = _FakeWriteOnlyStore()
    narrow_handle = OB.GeneratorWriteHandle(narrow_store, authorized_scope=frozenset({"SCREEN"}))
    with pytest.raises(OB.PrivateStorageWriteHandleViolation):
        narrow_handle.write_corpus("gce2c-" + "9" * 16, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    assert narrow_store.written == []   # the bad call never reached the store


def test_generator_write_handle_with_no_store_refuses_every_write():
    """The structural case for a purely public-scoped authorization: no vault-capable object is even held."""
    handle = OB.GeneratorWriteHandle(None, authorized_scope=frozenset())
    with pytest.raises(OB.PrivateStorageWriteHandleViolation):
        handle.write_corpus("gce2c-" + "0" * 16, {"SCREEN": b"x", "QUALIFICATION_HOLDOUT": b"y"})


def test_protected_generate_write_handle_denied_without_authorization(repo):
    """An unauthorized process must never obtain a write handle at all -- proves there is no alternative API to
    reach private writes when the composed boundary itself denies."""
    store = _FakeWriteOnlyStore()
    with pytest.raises(OB.CorpusGenerationNotAuthorized):
        OB.protected_generate_write_handle(repo, store, requested_scope=("SCREEN", "QUALIFICATION_HOLDOUT"), event_name="workflow_dispatch", now=NOW)
    assert store.written == []


def _authorize_generator_for(repo_dir: Path, code_hash: str, allowed_artifact_classes: list, generator_id: str = "gen-1"):
    doc = json.loads((repo_dir / GR.REGISTRY_PATH).read_text())
    doc["records"] = [{"generator_id": generator_id, "os_runtime": "test", "code_sha256": code_hash,
                        "allowed_artifact_classes": allowed_artifact_classes, "network_policy": "none",
                        "credential_scope": {"vault_write": True, "vault_read": False, "public_repo_write": False,
                                              "training_credentials": False, "unrelated_cloud_credentials": False, "developer_tokens": False},
                        "state": "AUTHORIZED"}]
    (repo_dir / GR.REGISTRY_PATH).write_text(json.dumps(doc))
    return generator_id


def _authorize_and_commit(repo, sk, requested_scope: tuple, allowed_artifact_classes: list):
    """Shared setup for the write-handle adversarial tests: a real signed authorization + a generator registered for
    exactly `allowed_artifact_classes`, committed so the tree is clean."""
    inv_digest, prereg_sha, code_hash = _real_context()
    gid = _authorize_generator_for(repo, code_hash, allowed_artifact_classes)
    reviewed_sha = _git_init_with_head(repo)
    _write_signed_cga(repo, sk, reviewed_sha, code_hash, inv_digest, prereg_sha, authorized_scope=list(requested_scope))
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-q", "-m", "evidence"], cwd=repo, check=True)
    return gid


def test_pilot_train_only_generator_gets_a_handle_with_no_vault_object_at_all(repo):
    """Items 1+2: a generator authorized ONLY for PILOT_TRAIN must never receive a handle wrapping ANY vault-capable
    object, and any attempt to write a private split through it -- even one it never should have been able to
    request -- is refused at the actual write call."""
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    gid = _authorize_and_commit(repo, sk, ("PILOT_TRAIN",), ["PILOT_TRAIN"])
    store = _FakeWriteOnlyStore()   # even a genuinely write-only vault object must never be reachable here
    handle = OB.protected_generate_write_handle(repo, store, requested_scope=("PILOT_TRAIN",), event_name="workflow_dispatch",
                                                 now=NOW, generator_id=gid)
    assert isinstance(handle, OB.GeneratorWriteHandle)
    assert handle._store is None   # structurally eliminated, not merely blocked by a runtime check
    with pytest.raises(OB.PrivateStorageWriteHandleViolation):
        handle.write_corpus("gce2c-" + "2" * 16, {"SCREEN": b"x", "QUALIFICATION_HOLDOUT": b"y"})
    assert store.written == []   # the underlying store was never touched


def test_generator_authorized_for_both_private_splits_writes_through_a_write_only_handle(repo):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    gid = _authorize_and_commit(repo, sk, ("SCREEN", "QUALIFICATION_HOLDOUT"), ["SCREEN", "QUALIFICATION_HOLDOUT"])
    store = _FakeWriteOnlyStore()
    handle = OB.protected_generate_write_handle(repo, store, requested_scope=("SCREEN", "QUALIFICATION_HOLDOUT"),
                                                 event_name="workflow_dispatch", now=NOW, generator_id=gid)
    assert handle._store is store
    handle.write_corpus("gce2c-" + "3" * 16, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    assert store.written == [("gce2c-" + "3" * 16, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})]


def test_generator_with_both_splits_authorized_still_cannot_smuggle_a_read_capable_store(repo):
    """Even a fully, legitimately authorized generator must not be able to reach private reads through an
    alternative store object -- protected_generate_write_handle refuses a read-capable `store` outright."""
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    _write_authority_registry_with_real_key(repo, sk)
    gid = _authorize_and_commit(repo, sk, ("SCREEN", "QUALIFICATION_HOLDOUT"), ["SCREEN", "QUALIFICATION_HOLDOUT"])
    with pytest.raises(OB.PrivateStorageWriteHandleViolation):
        OB.protected_generate_write_handle(repo, _FakeReadCapableStore(), requested_scope=("SCREEN", "QUALIFICATION_HOLDOUT"),
                                            event_name="workflow_dispatch", now=NOW, generator_id=gid)


# ---------------------------------------------------------------- genuine asymmetric key isolation (store.EncryptedVaultWriter/Reader)
def test_vault_writer_and_reader_key_isolation_end_to_end(tmp_path):
    """Item 3, proven with the REAL crypto (not a fake stand-in): a generator holding ONLY the vault's public key can
    write, but the same object graph contains no path to decrypt -- and the SEPARATE private-key-holding reader can
    read exactly what was written."""
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    assert not hasattr(writer, "read_split")
    # no private key byte exists anywhere in the writer's own state
    for v in vars(writer).values():
        assert v != priv
    corpus_id = "gce2c-" + "4" * 16
    digest = writer.write_corpus(corpus_id, {"SCREEN": b"real-screen", "QUALIFICATION_HOLDOUT": b"real-holdout"})

    reader = ST.EncryptedVaultReader(vault_dir, priv, repo_root=tmp_path / "not-a-repo")
    assert not hasattr(reader, "write_corpus")
    assert reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=digest) == b"real-screen"
    assert reader.read_split(corpus_id, "QUALIFICATION_HOLDOUT", expected_corpus_digest=digest) == b"real-holdout"


def test_vault_writer_public_key_bytes_cannot_be_used_to_decrypt(tmp_path):
    """Attempts to access underlying storage through internal attributes or alternative APIs: even taking the
    writer's own stored bytes and feeding them into a reader as if they were a private key must fail closed."""
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    corpus_id = "gce2c-" + "5" * 16
    digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    forged_reader = ST.EncryptedVaultReader(vault_dir, writer._pub, repo_root=tmp_path / "not-a-repo")
    with pytest.raises(ST.PrivateStorageIntegrityError):
        forged_reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=digest)


def test_vault_reader_with_wrong_private_key_fails_closed(tmp_path):
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    other_priv, _ = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    corpus_id = "gce2c-" + "6" * 16
    digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    wrong_reader = ST.EncryptedVaultReader(vault_dir, other_priv, repo_root=tmp_path / "not-a-repo")
    with pytest.raises(ST.PrivateStorageIntegrityError):
        wrong_reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=digest)


# ---------------------------------------------------------------- authorized_manifest_verification_bytes() (PURPOSE_CREATION_VERIFICATION)
def _write_runner_registry(root: Path, runner_id: str, code_hash: str, purposes: list, splits: list):
    doc = {"schema_version": RN.SCHEMA_VERSION, "records": [{
        "runner_id": runner_id, "runner_class": "SELF_HOSTED_CPU", "os_runtime": "test", "code_sha256": code_hash,
        "allowed_purposes": purposes, "allowed_splits": splits, "sandbox_image_digest": "sha256:" + "b" * 64,
        "semantic_engine_digest": "c" * 64, "storage_backend_verification_digest": "d" * 64, "ledger_database_identity_digest": "e" * 64,
        "network_policy": "none", "credential_scope": {"private_store_read": True, "public_repo_write": False, "training_credentials": False,
                                                         "unrelated_cloud_credentials": False, "developer_tokens": False}, "state": "AUTHORIZED"}]}
    (root / RN.REGISTRY_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / RN.REGISTRY_PATH).write_text(json.dumps(doc))


class _FakeVaultStore:
    def __init__(self):
        self.reads = []

    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        self.reads.append(split)
        return f"{split}-plaintext".encode()


def test_authorized_manifest_verification_bytes_uses_creation_verification_purpose_and_does_not_require_freeze(tmp_path):
    from orca.eval.genesis_v2 import ledger as LG
    from orca.eval.genesis_v2 import spec as SPEC
    root = tmp_path / "fakeroot"
    code_hash = "a" * 64
    _write_runner_registry(root, "verifier-1", code_hash, [SPEC.PURPOSE_CREATION_VERIFICATION],
                            ["SCREEN", "QUALIFICATION_HOLDOUT"])
    store = _FakeVaultStore()
    screen_plain, holdout_plain = OB.authorized_manifest_verification_bytes(
        root, tmp_path / "ledger", store, process_id="verifier-1", code_sha256=code_hash, corpus_id="gce2c-" + "0" * 16,
        expected_corpus_digest="b" * 64, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
        run_id_prefix="cv-run", timestamp_utc=ts(NOW))
    assert screen_plain == b"SCREEN-plaintext" and holdout_plain == b"QUALIFICATION_HOLDOUT-plaintext"
    assert store.reads == ["SCREEN", "QUALIFICATION_HOLDOUT"]
    led = LG.AccessLedger(tmp_path / "ledger", {})
    recs = [r for r in led.records() if r["purpose"] == SPEC.PURPOSE_CREATION_VERIFICATION]
    assert len(recs) == 2
    # never counted toward the holdout's real open/lineage bookkeeping
    assert led.holdout_state(SPEC.EVAL_VERSION) == {"state": SPEC.STATE_SEALED, "opened_by": None, "lineages": []}


def test_authorized_manifest_verification_bytes_refuses_once_v2_is_frozen(tmp_path, monkeypatch):
    from orca.eval.genesis_v2 import spec as SPEC
    root = tmp_path / "fakeroot"
    code_hash = "a" * 64
    _write_runner_registry(root, "verifier-1", code_hash, [SPEC.PURPOSE_CREATION_VERIFICATION], ["SCREEN", "QUALIFICATION_HOLDOUT"])
    store = _FakeVaultStore()
    monkeypatch.setattr(SPEC, "GENESIS_CAPABILITY_EVAL_V2_FROZEN", True)
    with pytest.raises(OB.PrivateSplitAccessDenied):
        OB.authorized_manifest_verification_bytes(
            root, tmp_path / "ledger", store, process_id="verifier-1", code_sha256=code_hash, corpus_id="gce2c-" + "0" * 16,
            expected_corpus_digest="b" * 64, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
            run_id_prefix="cv-run", timestamp_utc=ts(NOW))
    assert store.reads == []


def test_authorized_manifest_verification_bytes_refuses_a_write_capable_reader_object(tmp_path):
    from orca.eval.genesis_v2 import spec as SPEC
    root = tmp_path / "fakeroot"
    code_hash = "a" * 64
    _write_runner_registry(root, "verifier-1", code_hash, [SPEC.PURPOSE_CREATION_VERIFICATION], ["SCREEN", "QUALIFICATION_HOLDOUT"])
    with pytest.raises(OB.PrivateSplitAccessDenied):
        OB.authorized_manifest_verification_bytes(
            root, tmp_path / "ledger", _FakeWriteOnlyStore(), process_id="verifier-1", code_sha256=code_hash, corpus_id="gce2c-" + "0" * 16,
            expected_corpus_digest="b" * 64, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
            run_id_prefix="cv-run", timestamp_utc=ts(NOW))


def test_authorized_manifest_verification_bytes_refuses_a_verifier_also_authorized_for_real_qualification(tmp_path):
    """Item 4: a creation-time verifier must be a SEPARATELY CONTROLLED, restricted-access identity -- one also
    authorized for PURPOSE_QUALIFICATION could double as a real qualification runner, defeating the separation this
    capability exists to provide."""
    from orca.eval.genesis_v2 import spec as SPEC
    root = tmp_path / "fakeroot"
    code_hash = "a" * 64
    _write_runner_registry(root, "dual-purpose-runner", code_hash, [SPEC.PURPOSE_CREATION_VERIFICATION, SPEC.PURPOSE_QUALIFICATION],
                            ["SCREEN", "QUALIFICATION_HOLDOUT"])
    store = _FakeVaultStore()
    with pytest.raises(OB.PrivateSplitAccessDenied, match="separately controlled"):
        OB.authorized_manifest_verification_bytes(
            root, tmp_path / "ledger", store, process_id="dual-purpose-runner", code_sha256=code_hash, corpus_id="gce2c-" + "0" * 16,
            expected_corpus_digest="b" * 64, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
            run_id_prefix="cv-run", timestamp_utc=ts(NOW))
    assert store.reads == []


def test_authorized_manifest_verification_bytes_with_the_real_asymmetric_vault_reader(tmp_path):
    """End-to-end with the REAL EncryptedVaultReader (not the fake stand-in): proves the whole authorization chain
    (restricted verifier identity + ledger grant) composes correctly with genuine key-isolated decryption."""
    from orca.eval.genesis_v2 import spec as SPEC
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    root = tmp_path / "fakeroot"
    code_hash = "a" * 64
    _write_runner_registry(root, "verifier-real", code_hash, [SPEC.PURPOSE_CREATION_VERIFICATION], ["SCREEN", "QUALIFICATION_HOLDOUT"])
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    corpus_id = "gce2c-" + "7" * 16
    digest = writer.write_corpus(corpus_id, {"SCREEN": b"real-screen-content", "QUALIFICATION_HOLDOUT": b"real-holdout-content"})
    reader = ST.EncryptedVaultReader(vault_dir, priv, repo_root=tmp_path / "not-a-repo")
    screen_plain, holdout_plain = OB.authorized_manifest_verification_bytes(
        root, tmp_path / "ledger", reader, process_id="verifier-real", code_sha256=code_hash, corpus_id=corpus_id,
        expected_corpus_digest=digest, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
        run_id_prefix="cv-real", timestamp_utc=ts(NOW))
    assert screen_plain == b"real-screen-content" and holdout_plain == b"real-holdout-content"


# ---------------------------------------------------------------- verify_manifest_digest_only_same_process() (item 3: no plaintext leaves)
def _signed_owner_key():
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub_hex = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "k-owner", "public_key_hex": pub_hex, "identity": "owner-1", "role": "OWNER"}]
    return sk, keys


def _sign_manifest(manifest: dict, sk) -> dict:
    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    unsigned = {**manifest, "signing_authority": {"identity": "owner-1", "role": "OWNER", "key_id": "k-owner"}, "signature": "0" * 128}
    return {**unsigned, "signature": sk.sign(CMAN.manifest_signing_bytes(unsigned)).hex()}


def test_digest_only_same_process_verification_never_returns_plaintext(tmp_path):
    """The core item-3 claim, checked directly: the function's return value is a list of diagnostic strings that
    never contains the real plaintext, even though it genuinely had access to it internally to compute the result."""
    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    from orca.eval.genesis_v2 import runner_registry as RN
    from orca.eval.genesis_v2 import spec as SPEC
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    code_dir = tmp_path / "generator_code"
    code_dir.mkdir()
    (code_dir / "gen_a.py").write_text("def a():\n    return 1\n")
    code_sha = RN.code_sha256_of(sorted(code_dir.glob("*.py")))

    root = tmp_path / "fakeroot"
    _write_runner_registry(root, "verifier-restricted", code_sha, [SPEC.PURPOSE_CREATION_VERIFICATION], ["SCREEN", "QUALIFICATION_HOLDOUT"])
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    screen_bytes = b'{"marker":"SECRET-SCREEN-PLAINTEXT-MUST-NEVER-LEAK"}'
    holdout_bytes = b'{"marker":"SECRET-HOLDOUT-PLAINTEXT-MUST-NEVER-LEAK"}'
    corpus_id = "gce2c-" + "8" * 32
    digest = writer.write_corpus(corpus_id, {"SCREEN": screen_bytes, "QUALIFICATION_HOLDOUT": holdout_bytes})
    reader = ST.EncryptedVaultReader(vault_dir, priv, repo_root=tmp_path / "not-a-repo")

    sk, authority_keys = _signed_owner_key()
    reviewed_sha = "b" * 40
    manifest = _sign_manifest({"schema_version": CMAN.SCHEMA_VERSION, "corpus_id": corpus_id, "eval_version": SPEC.EVAL_VERSION,
                                "generator_code_sha256": code_sha, "generated_at_commit_sha": reviewed_sha,
                                "screen_digest": __import__("hashlib").sha256(screen_bytes).hexdigest(),
                                "qualification_holdout_digest": __import__("hashlib").sha256(holdout_bytes).hexdigest(),
                                "per_category_item_counts": {"reasoning": 1}, "corpus_generation_authorization_id": "cgauth-" + "ef" * 8}, sk)
    authorization_record = {"status": "AUTHORIZED", "authorization_id": manifest["corpus_generation_authorization_id"],
                             "reviewed_commit_sha": reviewed_sha, "authorized_code_tree_sha256": code_sha,
                             "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"]}

    problems = OB.verify_manifest_digest_only_same_process(
        root, tmp_path / "ledger", reader, manifest, authorization_record, authority_keys, process_id="verifier-restricted",
        code_sha256=code_sha, corpus_id=corpus_id, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
        run_id_prefix="restricted-verify", timestamp_utc=ts(NOW), generator_code_root=code_dir, commit_is_descendant=True)
    assert problems == []
    blob = repr(problems)
    assert b"SECRET-SCREEN-PLAINTEXT-MUST-NEVER-LEAK".decode() not in blob and b"SECRET-HOLDOUT-PLAINTEXT-MUST-NEVER-LEAK".decode() not in blob


def test_digest_only_same_process_verification_detects_tampering_without_leaking_plaintext(tmp_path):
    """A manifest claiming the wrong content is still caught -- and the problem list, while informative, never
    embeds the real plaintext bytes that proved the claim wrong."""
    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    from orca.eval.genesis_v2 import runner_registry as RN
    from orca.eval.genesis_v2 import spec as SPEC
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    code_dir = tmp_path / "generator_code"
    code_dir.mkdir()
    (code_dir / "gen_a.py").write_text("def a():\n    return 1\n")
    code_sha = RN.code_sha256_of(sorted(code_dir.glob("*.py")))

    root = tmp_path / "fakeroot"
    _write_runner_registry(root, "verifier-restricted-2", code_sha, [SPEC.PURPOSE_CREATION_VERIFICATION], ["SCREEN", "QUALIFICATION_HOLDOUT"])
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    screen_bytes = b'{"marker":"SECRET-SCREEN-TAMPER-TEST"}'
    holdout_bytes = b'{"marker":"SECRET-HOLDOUT-TAMPER-TEST"}'
    corpus_id = "gce2c-" + "9" * 32
    digest = writer.write_corpus(corpus_id, {"SCREEN": screen_bytes, "QUALIFICATION_HOLDOUT": holdout_bytes})
    reader = ST.EncryptedVaultReader(vault_dir, priv, repo_root=tmp_path / "not-a-repo")

    sk, authority_keys = _signed_owner_key()
    reviewed_sha = "b" * 40
    manifest = _sign_manifest({"schema_version": CMAN.SCHEMA_VERSION, "corpus_id": corpus_id, "eval_version": SPEC.EVAL_VERSION,
                                "generator_code_sha256": code_sha, "generated_at_commit_sha": reviewed_sha,
                                "screen_digest": "0" * 64,   # WRONG on purpose
                                "qualification_holdout_digest": __import__("hashlib").sha256(holdout_bytes).hexdigest(),
                                "per_category_item_counts": {"reasoning": 1}, "corpus_generation_authorization_id": "cgauth-" + "ef" * 8}, sk)
    authorization_record = {"status": "AUTHORIZED", "authorization_id": manifest["corpus_generation_authorization_id"],
                             "reviewed_commit_sha": reviewed_sha, "authorized_code_tree_sha256": code_sha,
                             "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"]}

    problems = OB.verify_manifest_digest_only_same_process(
        root, tmp_path / "ledger", reader, manifest, authorization_record, authority_keys, process_id="verifier-restricted-2",
        code_sha256=code_sha, corpus_id=corpus_id, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
        run_id_prefix="restricted-tamper", timestamp_utc=ts(NOW), generator_code_root=code_dir, commit_is_descendant=True)
    assert problems and any("CORPUS_DIGEST_MISMATCH" in p for p in problems)
    blob = repr(problems)
    assert "SECRET-SCREEN-TAMPER-TEST" not in blob and "SECRET-HOLDOUT-TAMPER-TEST" not in blob


def test_digest_only_same_process_verification_preserves_ledger_evidence_and_sealed_lifecycle(tmp_path):
    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    from orca.eval.genesis_v2 import ledger as LG
    from orca.eval.genesis_v2 import runner_registry as RN
    from orca.eval.genesis_v2 import spec as SPEC
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    code_dir = tmp_path / "generator_code"
    code_dir.mkdir()
    (code_dir / "gen_a.py").write_text("def a():\n    return 1\n")
    code_sha = RN.code_sha256_of(sorted(code_dir.glob("*.py")))

    root = tmp_path / "fakeroot"
    _write_runner_registry(root, "verifier-restricted-3", code_sha, [SPEC.PURPOSE_CREATION_VERIFICATION], ["SCREEN", "QUALIFICATION_HOLDOUT"])
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    screen_bytes, holdout_bytes = b"s", b"h"
    corpus_id = "gce2c-" + "f" * 32
    digest = writer.write_corpus(corpus_id, {"SCREEN": screen_bytes, "QUALIFICATION_HOLDOUT": holdout_bytes})
    reader = ST.EncryptedVaultReader(vault_dir, priv, repo_root=tmp_path / "not-a-repo")

    sk, authority_keys = _signed_owner_key()
    reviewed_sha = "b" * 40
    manifest = _sign_manifest({"schema_version": CMAN.SCHEMA_VERSION, "corpus_id": corpus_id, "eval_version": SPEC.EVAL_VERSION,
                                "generator_code_sha256": code_sha, "generated_at_commit_sha": reviewed_sha,
                                "screen_digest": __import__("hashlib").sha256(screen_bytes).hexdigest(),
                                "qualification_holdout_digest": __import__("hashlib").sha256(holdout_bytes).hexdigest(),
                                "per_category_item_counts": {"reasoning": 1}, "corpus_generation_authorization_id": "cgauth-" + "ef" * 8}, sk)
    authorization_record = {"status": "AUTHORIZED", "authorization_id": manifest["corpus_generation_authorization_id"],
                             "reviewed_commit_sha": reviewed_sha, "authorized_code_tree_sha256": code_sha,
                             "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"]}

    OB.verify_manifest_digest_only_same_process(
        root, tmp_path / "ledger", reader, manifest, authorization_record, authority_keys, process_id="verifier-restricted-3",
        code_sha256=code_sha, corpus_id=corpus_id, eval_version=SPEC.EVAL_VERSION, candidate_revision="rev-1", candidate_lineage="lineage-1",
        run_id_prefix="restricted-ledger", timestamp_utc=ts(NOW), generator_code_root=code_dir, commit_is_descendant=True)
    led = LG.AccessLedger(tmp_path / "ledger", {})
    recs = [r for r in led.records() if r["purpose"] == SPEC.PURPOSE_CREATION_VERIFICATION]
    assert len(recs) == 2   # one per split, same evidence-preservation guarantee as the underlying function
    assert led.holdout_state(SPEC.EVAL_VERSION) == {"state": SPEC.STATE_SEALED, "opened_by": None, "lineages": []}


def test_digest_only_same_process_verification_refuses_an_unsigned_manifest_before_touching_the_vault(tmp_path):
    """Item 1's core adversarial claim, isolated at the operational_boundary level: a structurally perfect but
    UNSIGNED manifest must be refused before authorized_manifest_verification_bytes is ever called -- proven here
    by using a process_id that isn't even registered, confirming the signature check runs first and the (nonexistent)
    ledger grant is never attempted."""
    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    from orca.eval.genesis_v2 import spec as SPEC
    from orca.eval.genesis_v2 import store as ST
    _need_crypto()
    priv, pub = ST.generate_vault_keypair()
    vault_dir = tmp_path / "vault"
    writer = ST.EncryptedVaultWriter(vault_dir, pub, repo_root=tmp_path / "not-a-repo")
    corpus_id = "gce2c-" + "77" * 16
    digest = writer.write_corpus(corpus_id, {"SCREEN": b"s", "QUALIFICATION_HOLDOUT": b"h"})
    reader = ST.EncryptedVaultReader(vault_dir, priv, repo_root=tmp_path / "not-a-repo")

    _, authority_keys = _signed_owner_key()   # a registered key exists, but the manifest below is NOT signed by it
    manifest = {"schema_version": CMAN.SCHEMA_VERSION, "corpus_id": corpus_id, "eval_version": SPEC.EVAL_VERSION,
                "generator_code_sha256": "a" * 64, "generated_at_commit_sha": "b" * 40,
                "screen_digest": __import__("hashlib").sha256(b"s").hexdigest(),
                "qualification_holdout_digest": __import__("hashlib").sha256(b"h").hexdigest(),
                "per_category_item_counts": {"reasoning": 1}, "corpus_generation_authorization_id": "cgauth-" + "ef" * 8,
                "signing_authority": {"identity": "owner-1", "role": "OWNER", "key_id": "k-owner"}, "signature": "0" * 128}
    authorization_record = {"status": "AUTHORIZED", "authorization_id": manifest["corpus_generation_authorization_id"],
                             "reviewed_commit_sha": "b" * 40, "authorized_code_tree_sha256": "a" * 64,
                             "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"]}

    problems = OB.verify_manifest_digest_only_same_process(
        tmp_path / "fakeroot", tmp_path / "ledger", reader, manifest, authorization_record, authority_keys,
        process_id="never-registered-process", code_sha256="a" * 64, corpus_id=corpus_id, eval_version=SPEC.EVAL_VERSION,
        candidate_revision="rev-1", candidate_lineage="lineage-1", run_id_prefix="unsigned-attack", timestamp_utc=ts(NOW),
        generator_code_root=tmp_path, commit_is_descendant=True)
    assert problems == ["MANIFEST_SIGNATURE_INVALID:INVALID_SIGNATURE"]


def test_digest_only_same_process_verifier_is_honestly_named_not_process_isolated():
    """Item 5 (prior round): the function's own name and docstring must not overstate a process-isolation guarantee
    it does not provide -- a same-process function claiming 'restricted process' was the exact problem being
    corrected. Item 6 (this round): verifier process isolation must be explicitly marked as requiring REAL
    DEPLOYMENT validation -- never established merely by this same-process wrapper existing."""
    assert not hasattr(OB, "verify_manifest_in_restricted_process")   # the old, overstated name is gone
    doc = OB.verify_manifest_digest_only_same_process.__doc__
    assert "does NOT provide operating-system process isolation" in doc
    assert "SAME Python process" in doc
    assert "DIGEST-ONLY DIAGNOSTICS" in doc
    assert "REQUIRES REAL DEPLOYMENT VALIDATION" in doc
    assert "UNVERIFIED until" in doc


def test_digest_only_same_process_verifier_has_no_training_inference_or_publishing_imports():
    """Item 5: an isolated verifier must have no training, inference or publishing capabilities. Scans the actual
    module dependencies this function's own code pulls in -- corpus_manifest.py and operational_boundary.py itself
    -- for anything resembling model loading, network access, or a repository-publishing action."""
    import ast
    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    import inspect
    forbidden_substrings = ("torch", "transformers", "openai", "anthropic", "requests", "httpx", "urllib",
                             "subprocess.Popen", "git push", "git commit")
    for module in (OB, CMAN):
        src = inspect.getsource(module)
        low = src.lower()
        for bad in forbidden_substrings:
            assert bad.lower() not in low, f"{module.__name__} unexpectedly references {bad!r}"
    # AST-level: no `import torch`/`import requests`/etc. anywhere in either module, not just absent from source text
    for module in (OB, CMAN):
        tree = ast.parse(inspect.getsource(module))
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module.split(".")[0])
        assert not (imported_names & {"torch", "transformers", "requests", "httpx", "urllib", "openai", "anthropic"})
