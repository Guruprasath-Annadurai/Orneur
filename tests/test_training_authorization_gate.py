"""
P0 -- Training authorization gate (fail closed).

All credentials here are SYNTHETIC: Ed25519 keys generated inside each test, registered in a throw-away registry inside a throw-away git
repository, with the gate's pin patched to that registry. The real committed registry is empty and the real committed record is
NOT_AUTHORIZED; nothing in this file provisions a live key, touches a GPU, or runs a training job. Every test that expects a denial also
proves no training work (manifest creation, dependency import, SSH, upload) happened.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import orca.config as orca_config
import orca.train.authorization as A
from orca.train.config import TrainingConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV = "SELF_HOSTED_GPU"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class World:
    """A synthetic repository + registry + signed record + data files."""

    def __init__(self, tmp_path: Path, monkeypatch, *, record_over=None, registry_over=None, revoked=(), authorize_record=True,
                 sign_domain=True, extra_keys=0, pin=True):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        self.tmp = tmp_path
        self.root = tmp_path / "repo"
        (self.root / "orca/train").mkdir(parents=True)
        (self.root / "orca/registry").mkdir(parents=True)
        (self.root / "docs/orneur/authorization").mkdir(parents=True)
        (self.root / "orca/train/dummy.py").write_text("X = 1\n")
        (self.root / "orca/registry/dummy.py").write_text("Y = 2\n")
        self.priv = Ed25519PrivateKey.generate()
        pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        now = datetime.now(timezone.utc)
        key = {
            "id": "synthetic-authority-1", "role": "OWNER", "public_key_hex": pub, "activation_timestamp": _ts(now - timedelta(days=1)),
            "expiry": None, "revoked": False, "permitted_purposes": ["EXPERIMENTAL_PILOT", "CANONICAL_RUN"],
            "permitted_environment_classes": ["SELF_HOSTED_GPU", "SSH_RENTED_GPU"], "permitted_families": [A.GENERIC_FAMILY, "genesis", "novus"],
            "gpu_permission": True, "spend_permission": True,
        }
        key = _merge(key, registry_over or {})
        self.registry = {"schema_version": A.REGISTRY_SCHEMA_VERSION, "records": [key]}
        for i in range(extra_keys):
            self.registry["records"].append({**key, "id": f"synthetic-extra-{i}"})
        self.sign = lambda rec: self._sign(rec, sign_domain)
        self._write(A.REGISTRY_PATH, self.registry)
        self._write(A.REVOCATIONS_PATH, {"schema_version": A.REVOCATIONS_SCHEMA_VERSION, "revoked_authorization_ids": list(revoked)})
        self._write(A.RECORD_PATH, A.default_record())
        _git(self.root, "init", "-q", "-b", "main")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "reviewed")
        self.reviewed = _git(self.root, "rev-parse", "HEAD")

        data = tmp_path / "data"
        data.mkdir()
        self.train, self.eval = data / "train.jsonl", data / "eval.jsonl"
        self.train.write_text('{"text": "a"}\n{"text": "b"}\n')
        self.eval.write_text('{"text": "c"}\n')
        self.cfg = TrainingConfig()
        self.cfg.train_file, self.cfg.eval_file = str(self.train), str(self.eval)

        self.record = None
        if authorize_record:
            self.record = self.make_record(record_over or {})
            self._write(A.RECORD_PATH, self.record)
            _git(self.root, "add", "-A")
            _git(self.root, "commit", "-q", "-m", "signed authorization record")

        monkeypatch.setattr(A, "_default_root", lambda: self.root)
        if pin:
            monkeypatch.setattr(A, "PINNED_REGISTRY_SHA256", A.registry_digest(self.registry))
        monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")
        self.state = tmp_path / "ornhome" / "training" / "authorization"

    def _write(self, rel: str, obj) -> None:
        (self.root / rel).write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")

    def _sign(self, rec: dict, domain: bool) -> dict:
        rec = dict(rec)
        rec["signature"] = None
        body = A.canonical_signing_bytes(rec) if domain else A._canonical({k: v for k, v in rec.items() if k != "signature"})
        rec["signature"] = self.priv.sign(body).hex()
        return rec

    def make_record(self, over: dict) -> dict:
        now = datetime.now(timezone.utc)
        rec = {
            "schema_version": A.SCHEMA_VERSION, "authorization_id": "tauth-" + "ab" * 8, "status": "AUTHORIZED", "purpose": "EXPERIMENTAL_PILOT",
            "reviewed_commit_sha": self.reviewed, "authorized_code_tree_sha256": A.code_tree_sha256(self.root),
            "model": {"family": A.GENERIC_FAMILY, "base_model": self.cfg.base_model, "base_model_revision": None},
            "datasets": {"train_sha256": A.file_sha256(self.train), "eval_sha256": A.file_sha256(self.eval),
                         "dataset_manifest_ids": ["ds-1"], "dataset_bundle_id": None},
            "environment_class": ENV,
            "limits": {"max_runs": 1, "max_epochs": 3, "max_lora_rank": 64, "max_seq_length": 4096, "max_wall_clock_minutes": 90, "max_spend_usd": 0},
            "permissions": {"gpu_allowed": True}, "issued_at": _ts(now - timedelta(hours=1)), "expires_at": _ts(now + timedelta(days=6)),
            "authorizing_authority": {"identity": "synthetic-authority-1", "role": "OWNER", "key_id": "synthetic-authority-1"}, "signature": None,
        }
        return self.sign(_merge(rec, over))

    def authorize(self, **kw):
        kw.setdefault("environment_class", ENV)
        kw.setdefault("dataset_manifest_ids", ["ds-1"])
        return A.authorize_training(self.cfg, **kw)

    def events(self) -> list:
        p = self.state / "events.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def reasons_of(fn) -> list:
    with pytest.raises(A.TrainingNotAuthorized) as exc:
        fn()
    return exc.value.reasons


# ─── the committed (real) state authorizes nothing ───────────────────────────────────────────────────────────────────────────────

def test_committed_registry_is_empty_pinned_and_record_is_not_authorized():
    reg = json.loads((REPO_ROOT / A.REGISTRY_PATH).read_text())
    assert A.validate_registry(reg) == [] and reg["records"] == []
    assert A.registry_digest(reg) == A.PINNED_REGISTRY_SHA256
    assert json.loads((REPO_ROOT / A.RECORD_PATH).read_text()) == A.default_record()
    assert json.loads((REPO_ROOT / A.REVOCATIONS_PATH).read_text()) == A.empty_revocations()


def test_real_repo_denies_even_a_perfectly_formed_request(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    cfg = TrainingConfig()
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")
    cfg.train_file = str(t)
    assert "NOT_AUTHORIZED" in reasons_of(lambda: A.authorize_training(cfg, environment_class=ENV))


# ─── happy path + evidence ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_valid_grant_is_issued_bound_and_audited(world):
    g = world.authorize()
    assert g.authorization_id == world.record["authorization_id"] and g.run_slot == 0 and g.key_id == "synthetic-authority-1"
    g.assert_valid_for(world.cfg, environment_class=ENV)
    g.assert_files(world.train, world.eval)
    ev = [e for e in world.events() if e["event"] == "TRAINING_AUTHORIZED"]
    assert len(ev) == 1
    e = ev[0]
    assert e["train_sha256"] == A.file_sha256(world.train) and e["code_tree_sha256"] == A.code_tree_sha256(world.root)
    assert e["head_sha"] == _git(world.root, "rev-parse", "HEAD") and e["reviewed_commit_sha"] == world.reviewed
    assert A.verify_event_chain(world.state)


def test_event_chain_detects_tampering(world):
    world.authorize()
    with pytest.raises(A.TrainingNotAuthorized):
        world.authorize()                      # budget exhausted -> second (denial) event
    assert A.verify_event_chain(world.state) and len(world.events()) == 2
    p = world.state / "events.jsonl"
    p.write_text(p.read_text().replace('"TRAINING_AUTHORIZED"', '"TRAINING_AUTHORIZEX"', 1))
    assert not A.verify_event_chain(world.state)


# ─── request-exact binding: every mismatch fails closed ───────────────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)
DENY_CASES = [
    ("expired", dict(issued_at=_ts(NOW - timedelta(days=3)), expires_at=_ts(NOW - timedelta(days=1))), "EXPIRED"),
    ("not_yet_valid", dict(issued_at=_ts(NOW + timedelta(days=1)), expires_at=_ts(NOW + timedelta(days=3))), "NOT_YET_VALID"),
    ("window_too_long", dict(issued_at=_ts(NOW - timedelta(hours=1)), expires_at=_ts(NOW + timedelta(days=30))), "VALIDITY_WINDOW_TOO_LONG"),
    ("bad_timestamp", dict(expires_at="tomorrow"), "BAD_TIMESTAMPS"),
    ("wrong_family", dict(model=dict(family="novus")), "WRONG_FAMILY"),
    ("wrong_base_model", dict(model=dict(base_model="evil/other-model")), "WRONG_BASE_MODEL"),
    ("wrong_revision", dict(model=dict(base_model_revision="a" * 40)), "WRONG_BASE_MODEL_REVISION"),
    ("wrong_train_data", dict(datasets=dict(train_sha256="0" * 64)), "WRONG_TRAIN_DATASET"),
    ("wrong_eval_data", dict(datasets=dict(eval_sha256="1" * 64)), "WRONG_EVAL_DATASET"),
    ("eval_omitted", dict(datasets=dict(eval_sha256=None)), "WRONG_EVAL_DATASET"),
    ("wrong_manifests", dict(datasets=dict(dataset_manifest_ids=["ds-2"])), "WRONG_DATASET_MANIFESTS"),
    ("wrong_bundle", dict(datasets=dict(dataset_bundle_id="bundle-x")), "WRONG_DATASET_BUNDLE"),
    ("wrong_environment", dict(environment_class="SSH_RENTED_GPU"), "WRONG_ENVIRONMENT_CLASS"),
    ("wrong_purpose", dict(purpose="CANONICAL_RUN"), "WRONG_PURPOSE"),
    ("epochs_over_limit", dict(limits=dict(max_epochs=2)), "EPOCHS_NOT_AUTHORIZED"),
    ("rank_over_limit", dict(limits=dict(max_lora_rank=32)), "LORA_RANK_NOT_AUTHORIZED"),
    ("seq_over_limit", dict(limits=dict(max_seq_length=2048)), "SEQUENCE_LENGTH_NOT_AUTHORIZED"),
    ("zero_runs", dict(limits=dict(max_runs=0)), "LIMITS_INVALID"),
    ("bool_as_int_limit", dict(limits=dict(max_epochs=True)), "LIMITS_INVALID"),
    ("negative_spend_cap", dict(limits=dict(max_spend_usd=-1)), "LIMITS_INVALID"),
    ("gpu_not_allowed", dict(permissions=dict(gpu_allowed=False)), "GPU_NOT_AUTHORIZED"),
    ("gpu_flag_not_bool", dict(permissions=dict(gpu_allowed="yes")), "GPU_NOT_AUTHORIZED"),
    ("bad_auth_id", dict(authorization_id="not-an-id"), "AUTHORIZATION_ID_INVALID"),
    ("status_invalid", dict(status="MAYBE"), "RECORD_INVALID"),
    ("status_not_authorized", dict(status="NOT_AUTHORIZED"), "NOT_AUTHORIZED"),
    ("bad_reviewed_sha", dict(reviewed_commit_sha="nothex"), "BAD_REVIEWED_COMMIT_SHA"),
    ("bad_code_hash", dict(authorized_code_tree_sha256="short"), "BAD_AUTHORIZED_CODE_TREE_HASH"),
    ("code_hash_mismatch", dict(authorized_code_tree_sha256="f" * 64), "CODE_TREE_HASH_MISMATCH"),
    ("unregistered_key", dict(authorizing_authority=dict(key_id="nobody", identity="nobody")), "AUTHORITY_KEY_NOT_REGISTERED"),
    ("identity_mismatch", dict(authorizing_authority=dict(identity="someone-else")), "AUTHORITY_IDENTITY_MISMATCH"),
    ("role_mismatch", dict(authorizing_authority=dict(role="DELEGATED_OWNER")), "AUTHORITY_IDENTITY_MISMATCH"),
]


@pytest.mark.parametrize("name,over,reason", DENY_CASES, ids=[c[0] for c in DENY_CASES])
def test_signed_but_mismatched_record_is_denied(tmp_path, monkeypatch, name, over, reason):
    w = World(tmp_path, monkeypatch, record_over=over)          # re-signed with the registered key: ONLY the targeted check can fail
    assert reason in reasons_of(w.authorize)
    assert not [e for e in w.events() if e["event"] == "TRAINING_AUTHORIZED"]
    assert not (w.state / "runs").exists() or not any((w.state / "runs").rglob("slot-*"))


def test_request_side_mismatches_are_denied(world):
    cfg = world.cfg
    cfg.num_epochs = 4
    assert "EPOCHS_NOT_AUTHORIZED" in reasons_of(world.authorize)
    cfg.num_epochs = 3
    cfg.lora.r = 128
    assert "LORA_RANK_NOT_AUTHORIZED" in reasons_of(world.authorize)
    cfg.lora.r = 64
    assert "SPEND_NOT_AUTHORIZED" in reasons_of(lambda: world.authorize(requested_spend_usd=5.0))
    assert "SPEND_NOT_AUTHORIZED" in reasons_of(lambda: world.authorize(requested_spend_usd=float("inf")))
    assert "SPEND_NOT_AUTHORIZED" in reasons_of(lambda: world.authorize(requested_spend_usd=float("nan")))
    assert "WRONG_ENVIRONMENT_CLASS" in reasons_of(lambda: world.authorize(environment_class="SSH_RENTED_GPU"))
    assert "UNKNOWN_ENVIRONMENT_CLASS" in reasons_of(lambda: world.authorize(environment_class="LAPTOP_CPU"))
    assert "WRONG_DATASET_MANIFESTS" in reasons_of(lambda: world.authorize(dataset_manifest_ids=[]))
    cfg.base_model = "evil/other-model"
    assert "WRONG_BASE_MODEL" in reasons_of(world.authorize)


def test_data_modified_after_signing_is_denied_and_after_authorizing_is_caught(world):
    g = world.authorize()
    world.train.write_text('{"text": "poisoned"}\n')
    with pytest.raises(A.TrainingNotAuthorized) as e:
        g.assert_files(world.train, world.eval)
    assert "TRAIN_DATA_CHANGED_AFTER_AUTHORIZATION" in e.value.reasons
    assert "WRONG_TRAIN_DATASET" in reasons_of(world.authorize)           # fresh attempt: slot budget aside, the digest no longer matches
    world.train.write_text('{"text": "a"}\n{"text": "b"}\n')
    with pytest.raises(A.TrainingNotAuthorized) as e2:
        g.assert_files(world.train, None)
    assert "EVAL_DATA_CHANGED_AFTER_AUTHORIZATION" in e2.value.reasons


def test_unapproved_extra_eval_file_is_rejected(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, record_over=dict(datasets=dict(eval_sha256=None)))
    w.cfg.eval_file = str(tmp_path / "does-not-exist.jsonl")
    g = w.authorize()
    with pytest.raises(A.TrainingNotAuthorized) as e:
        g.assert_files(w.train, w.eval)
    assert "UNAUTHORIZED_EVAL_DATA" in e.value.reasons


# ─── signature, domain separation, registry, revocation ──────────────────────────────────────────────────────────────────────────

def test_tampering_after_signing_is_detected(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    rec = json.loads((w.root / A.RECORD_PATH).read_text())
    rec["limits"]["max_runs"] = 99
    w._write(A.RECORD_PATH, rec)
    _git(w.root, "commit", "-qam", "tamper")
    assert "SIGNATURE_INVALID" in reasons_of(w.authorize)


def test_signature_from_another_purpose_domain_is_rejected(tmp_path, monkeypatch):
    """A signature produced the way the model-eval gate signs (no training domain prefix) can never authorize training."""
    w = World(tmp_path, monkeypatch, sign_domain=False)
    assert "SIGNATURE_INVALID" in reasons_of(w.authorize)


def test_signature_by_unregistered_key_is_rejected(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    w = World(tmp_path, monkeypatch)
    w.priv = Ed25519PrivateKey.generate()
    rec = w.make_record({})
    w._write(A.RECORD_PATH, rec)
    _git(w.root, "commit", "-qam", "forged")
    assert "SIGNATURE_INVALID" in reasons_of(w.authorize)


def test_revoked_key_expired_key_and_unactivated_key_are_rejected(tmp_path, monkeypatch):
    assert "AUTHORITY_KEY_NOT_ACTIVE_OR_REVOKED" in reasons_of(World(tmp_path / "a", monkeypatch, registry_over=dict(revoked=True)).authorize)
    expired = dict(expiry=_ts(datetime.now(timezone.utc) - timedelta(minutes=1)))
    assert "AUTHORITY_KEY_NOT_ACTIVE_OR_REVOKED" in reasons_of(World(tmp_path / "b", monkeypatch, registry_over=expired).authorize)
    future = dict(activation_timestamp=_ts(datetime.now(timezone.utc) + timedelta(days=1)))
    assert "AUTHORITY_KEY_NOT_ACTIVE_OR_REVOKED" in reasons_of(World(tmp_path / "c", monkeypatch, registry_over=future).authorize)


@pytest.mark.parametrize("scope,reason", [
    (dict(permitted_purposes=["CANONICAL_RUN"]), "AUTHORITY_NOT_SCOPED_TO_PURPOSE"),
    (dict(permitted_environment_classes=["SSH_RENTED_GPU"]), "AUTHORITY_NOT_SCOPED_TO_ENVIRONMENT"),
    (dict(permitted_families=["novus"]), "AUTHORITY_NOT_SCOPED_TO_FAMILY"),
    (dict(gpu_permission=False), "AUTHORITY_LACKS_GPU_PERMISSION"),
])
def test_authority_scope_is_enforced(tmp_path, monkeypatch, scope, reason):
    assert reason in reasons_of(World(tmp_path, monkeypatch, registry_over=scope).authorize)


def test_spend_requires_spend_permission_on_the_authority(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, record_over=dict(limits=dict(max_spend_usd=10)), registry_over=dict(spend_permission=False))
    assert "AUTHORITY_LACKS_SPEND_PERMISSION" in reasons_of(w.authorize)


def test_registry_not_matching_the_source_pin_authorizes_nothing(tmp_path, monkeypatch):
    """Adding a key to the registry file alone (without the reviewed source change to the pin) grants nothing."""
    w = World(tmp_path, monkeypatch, extra_keys=1, pin=False)
    monkeypatch.setattr(A, "PINNED_REGISTRY_SHA256", "0" * 64)
    assert "AUTHORITY_REGISTRY_UNREADABLE_OR_NOT_PINNED" in reasons_of(w.authorize)


@pytest.mark.parametrize("which", ["registry", "revocations", "record"])
def test_unreadable_or_malformed_trust_files_fail_closed(tmp_path, monkeypatch, which):
    w = World(tmp_path, monkeypatch)
    target = {"registry": A.REGISTRY_PATH, "revocations": A.REVOCATIONS_PATH, "record": A.RECORD_PATH}[which]
    (w.root / target).write_text("{ not json")
    _git(w.root, "commit", "-qam", "break")
    rs = reasons_of(w.authorize)
    assert any(r in rs for r in ("AUTHORITY_REGISTRY_UNREADABLE_OR_NOT_PINNED", "REVOCATION_LIST_UNREADABLE", "RECORD_UNREADABLE"))


def test_revocation_list_revokes_a_grant(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, revoked=["tauth-" + "ab" * 8])
    assert "AUTHORIZATION_REVOKED" in reasons_of(w.authorize)


@pytest.mark.parametrize("bad", [None, [], "AUTHORIZED", {"status": "AUTHORIZED"}])
def test_garbage_records_are_denied(world, bad):
    verdict = A.verify(bad, A.Request("a" * 40, True, True, "b" * 64, "x", "m", None, "c" * 64, None, (), None, ENV, "EXPERIMENTAL_PILOT", 1, 1, 1, 0.0),
                       world.registry, [])
    assert verdict.authorized is False and verdict.reasons


def test_empty_registry_with_authorized_record_is_denied(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.registry["records"] = []
    w._write(A.REGISTRY_PATH, w.registry)
    _git(w.root, "commit", "-qam", "empty registry")
    monkeypatch.setattr(A, "PINNED_REGISTRY_SHA256", A.registry_digest(w.registry))
    assert "NO_TRUSTED_TRAINING_AUTHORITY_REGISTERED" in reasons_of(w.authorize)


# ─── commit / code / tree binding ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_dirty_working_tree_is_denied(world):
    (world.root / "orca/train/dummy.py").write_text("X = 999\n")
    assert "DIRTY_WORKING_TREE" in reasons_of(world.authorize)


def test_code_changed_after_review_even_if_committed_is_denied(world):
    (world.root / "orca/train/dummy.py").write_text("X = 999  # reviewer never saw this\n")
    _git(world.root, "commit", "-qam", "post-review change")
    assert "CODE_TREE_HASH_MISMATCH" in reasons_of(world.authorize)


def test_reviewed_commit_that_is_not_an_ancestor_is_denied(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    _git(w.root, "checkout", "-q", "--orphan", "other")
    (w.root / "orca/train/dummy.py").write_text("X = 1\n")
    _git(w.root, "add", "-A")
    _git(w.root, "commit", "-qm", "unrelated history with identical files")
    assert "REVIEWED_COMMIT_NOT_ANCESTOR_OF_HEAD" in reasons_of(w.authorize)


def test_not_a_git_repository_is_denied(world):
    import shutil
    shutil.rmtree(world.root / ".git")
    rs = reasons_of(world.authorize)
    assert "BAD_HEAD_SHA" in rs or "REVIEWED_COMMIT_NOT_ANCESTOR_OF_HEAD" in rs or "DIRTY_WORKING_TREE" in rs


# ─── run budget / replay ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_run_budget_is_enforced_and_failed_runs_still_consume(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, record_over=dict(limits=dict(max_runs=2)))
    assert w.authorize().run_slot == 0
    assert w.authorize().run_slot == 1
    assert "RUN_BUDGET_EXHAUSTED" in reasons_of(w.authorize)


def test_concurrent_claims_never_exceed_budget(tmp_path, monkeypatch):
    import threading
    w = World(tmp_path, monkeypatch, record_over=dict(limits=dict(max_runs=3)))
    results = []

    def go():
        try:
            results.append(w.authorize().run_slot)
        except A.TrainingNotAuthorized:
            results.append(None)

    ts = [threading.Thread(target=go) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    granted = sorted(r for r in results if r is not None)
    assert granted == [0, 1, 2]


# ─── no environment / flag / self-issue path ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("var", ["ORNEUR_ALLOW_TRAINING", "ORCA_ALLOW_TRAINING", "ORNEUR_TRAINING_AUTHORIZED", "ORNEUR_DRY_RUN", "CI",
                                 "ORNEUR_ENV", "TRAINING_AUTHORIZED", "ORNEUR_TEST_MODE", "ORNEUR_HOME"])
def test_environment_variables_cannot_grant_authority(tmp_path, monkeypatch, var):
    monkeypatch.setenv(var, "1")
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    cfg = TrainingConfig()
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")
    cfg.train_file = str(t)
    assert "NOT_AUTHORIZED" in reasons_of(lambda: A.authorize_training(cfg, environment_class=ENV))


def test_gate_module_never_reads_the_environment_or_holds_signing_keys():
    src = (REPO_ROOT / "orca/train/authorization.py").read_text()
    tree = ast.parse(src)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"environ", "getenv", "putenv"}, "authorization must not consult environment variables"
    assert "Ed25519PrivateKey" not in src and "private_bytes" not in src, "the gate must be unable to sign"
    assert ".sign(" not in src


def test_no_training_code_anywhere_in_orca_holds_a_signing_key():
    for py in (REPO_ROOT / "orca/train").rglob("*.py"):
        text = py.read_text()
        assert "Ed25519PrivateKey" not in text, py


def test_grant_cannot_be_minted_through_the_public_api():
    kw = dict(authorization_id="tauth-" + "a" * 16, key_id="k", record_sha256="0" * 64, run_slot=0, expires_at="2099-01-01T00:00:00Z",
              max_wall_clock_minutes=1, cfg_fingerprint="0" * 64, train_sha256="0" * 64, eval_sha256=None, environment_class=ENV)
    with pytest.raises(A.TrainingNotAuthorized):
        A.TrainingGrant(**kw)
    with pytest.raises(A.TrainingNotAuthorized):
        A.TrainingGrant(**kw, _seal=object())


def test_require_grant_rejects_missing_wrong_type_and_stale_grants(world):
    for bad in (None, "granted", {"authorization_id": "x"}, object()):
        assert reasons_of(lambda b=bad: A.require_grant(b, world.cfg, environment_class=ENV)) == ["NO_TRAINING_GRANT"]
    g = world.authorize()
    world.cfg.num_epochs = 1                                   # config mutated after authorization
    assert "CONFIG_CHANGED_AFTER_AUTHORIZATION" in reasons_of(lambda: A.require_grant(g, world.cfg, environment_class=ENV))
    world.cfg.num_epochs = 3
    assert "WRONG_ENVIRONMENT_CLASS" in reasons_of(lambda: A.require_grant(g, world.cfg, environment_class="SSH_RENTED_GPU"))
    late = datetime.now(timezone.utc) + timedelta(days=30)
    assert "EXPIRED" in reasons_of(lambda: g.assert_valid_for(world.cfg, environment_class=ENV, now=late))


def test_wall_clock_limit_stops_training():
    class Ctl:
        should_training_stop = False

    t = [0.0]
    cb = A.WallClockLimit(60, clock=lambda: t[0])
    c = Ctl()
    cb.on_step_end(None, None, c)
    assert not c.should_training_stop
    t[0] = 61.0
    cb.on_step_end(None, None, c)
    assert c.should_training_stop and cb.tripped
    assert cb.on_train_begin(None, None, c) is c            # unrelated hooks are harmless no-ops


# ─── every entry path is gated; lower-level bypass attempts ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def sentinel(monkeypatch):
    """Any real-training side effect is a test failure."""
    import orca.train.finetune as ft

    def boom(*a, **k):
        raise AssertionError("training work started without authorization")

    monkeypatch.setattr(ft, "start_training_run", boom)
    monkeypatch.setattr(ft, "_check_deps", boom)
    return ft


def test_train_is_denied_before_any_work_when_unauthorized(tmp_path, monkeypatch, sentinel):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    cfg = TrainingConfig()
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")
    cfg.train_file = str(t)
    with pytest.raises(A.TrainingNotAuthorized):
        sentinel.train(cfg)


def test_train_with_valid_grant_proceeds_and_passes_the_grant_down(world, monkeypatch):
    import orca.train.finetune as ft
    seen = {}
    monkeypatch.setattr(ft, "start_training_run", lambda cfg, **k: seen.setdefault("manifest", object()))

    def fake_impl(cfg, log, manifest, grant=None):
        seen["grant"] = grant
        return {"ok": True}

    monkeypatch.setattr(ft, "_train_impl", fake_impl)
    assert ft.train(world.cfg, dataset_manifest_ids=["ds-1"]) == {"ok": True}
    assert isinstance(seen["grant"], A.TrainingGrant) and seen["manifest"] is not None


def test_train_impl_cannot_be_called_directly(world, sentinel):
    """Bypass attempt: skip train() and call the private implementation."""
    import orca.train.finetune as ft
    for grant in (None, "yes", object()):
        with pytest.raises(A.TrainingNotAuthorized) as e:
            ft._train_impl(world.cfg, print, object(), grant)
        assert e.value.reasons == ["NO_TRAINING_GRANT"]
    with pytest.raises(A.TrainingNotAuthorized):
        ft._train_impl(world.cfg, print, object())


def test_train_impl_rejects_a_grant_for_a_different_config(world, sentinel):
    import orca.train.finetune as ft
    g = world.authorize()
    other = copy.deepcopy(world.cfg)
    other.lora.r = 8
    with pytest.raises(A.TrainingNotAuthorized) as e:
        ft._train_impl(other, print, object(), g)
    assert "CONFIG_CHANGED_AFTER_AUTHORIZATION" in e.value.reasons


def test_malformed_config_still_reports_its_precise_error_first(tmp_path, monkeypatch, sentinel):
    cfg = TrainingConfig()
    cfg.base_model = None
    with pytest.raises(ValueError):
        sentinel.train(cfg)


def test_cloud_trainer_is_denied_before_any_ssh_or_upload(tmp_path, monkeypatch):
    import orca.train.cloud as cloud
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    fmt = tmp_path / "formatted"
    fmt.mkdir()
    (fmt / "orca_llama3_train.jsonl").write_text('{"text":"a"}\n')
    monkeypatch.setattr(cloud, "FORMATTED_DIR", fmt)

    def boom(*a, **k):
        raise AssertionError("remote work started without authorization")

    for fn in ("_ssh_run", "_rsync_up", "_rsync_down"):
        monkeypatch.setattr(cloud, fn, boom)
    with pytest.raises(A.TrainingNotAuthorized) as e:
        cloud.CloudTrainer(ssh="ssh root@192.0.2.1", preset="cloud").run()
    assert "NOT_AUTHORIZED" in e.value.reasons


def test_cloud_trainer_unknown_cost_is_treated_as_unbounded(tmp_path, monkeypatch):
    import orca.train.cloud as cloud
    t = cloud.CloudTrainer(ssh="ssh root@192.0.2.1", preset="cloud")
    assert t._estimated_spend_usd(tmp_path / "missing.jsonl") == float("inf")


@pytest.mark.parametrize("args", [["train", "run"], ["train", "nano"], ["train", "core"], ["train", "run", "--preset", "laptop", "--epochs", "1"]])
def test_cli_training_commands_exit_nonzero_and_start_nothing(tmp_path, monkeypatch, sentinel, args):
    from typer.testing import CliRunner
    from orca.cli import app
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0
    assert "training work started" not in (result.output or "")
    assert not isinstance(result.exception, AssertionError)


def test_cli_has_no_dry_run_or_force_flag_for_training():
    from typer.main import get_command
    from orca.cli import app
    train = get_command(app).commands["train"]
    for name, cmd in train.commands.items():
        flags = {o for p in cmd.params for o in getattr(p, "opts", [])}
        assert not flags & {"--dry-run", "--force", "--yes", "--skip-auth", "--no-auth", "--unsafe"}, (name, flags)


def test_train_signature_has_no_bypass_parameter():
    import orca.train.finetune as ft
    assert list(inspect.signature(ft.train).parameters) == ["cfg", "on_log", "dataset_manifest_ids", "dataset_bundle_id"]
    assert list(inspect.signature(A.authorize_training).parameters) == [
        "cfg", "environment_class", "dataset_manifest_ids", "dataset_bundle_id", "requested_spend_usd", "now"]


def test_every_trainer_construction_site_in_the_repo_is_gated():
    """Static reachability guard. Any module that references a TRL/HF trainer or calls `.train()` on one must be on this allowlist, and each
    allowlisted module must route through the gate. A new training entry point therefore fails this test until it is gated and reviewed."""
    allow = {"orca/train/finetune.py": ("authorize_training", "require_grant"), "orca/train/cloud.py": ("authorize_training", "assert_files")}
    trainer_names = {"SFTTrainer", "DPOTrainer", "ORPOTrainer", "KTOTrainer", "GRPOTrainer", "PPOTrainer", "RewardTrainer", "Trainer"}
    offenders = []
    scanned = 0
    for base in ("orca", "orneur", "scripts"):
        for py in (REPO_ROOT / base).rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(REPO_ROOT).as_posix()
            text = py.read_text(encoding="utf-8")
            scanned += 1
            try:
                tree = ast.parse(text)
            except SyntaxError:
                offenders.append(f"{rel}: unparseable")
                continue
            hit = any(
                (isinstance(n, ast.Name) and n.id in trainer_names) or (isinstance(n, ast.Attribute) and n.attr in trainer_names)
                or (isinstance(n, ast.ImportFrom) and any(a.name in trainer_names for a in n.names))
                or (isinstance(n, ast.Constant) and isinstance(n.value, str) and "trainer.train()" in n.value)
                for n in ast.walk(tree)
            )
            if hit:
                if rel not in allow:
                    offenders.append(f"{rel}: constructs/runs a trainer outside the gated allowlist")
                elif not all(tok in text for tok in allow[rel]):
                    offenders.append(f"{rel}: allowlisted but missing gate references {allow[rel]}")
    assert scanned > 100
    assert offenders == []


def test_gate_is_invoked_before_start_training_run_in_source_order():
    src = (REPO_ROOT / "orca/train/finetune.py").read_text()
    body = src[src.index("def train("):src.index("def _load_base_model_and_tokenizer")]
    assert body.index("grant = authorize_training(") < body.index("manifest = start_training_run(")
    impl = src[src.index("def _train_impl("):]
    assert impl.index("require_grant(") < impl.index("_check_deps()") < impl.index("load_dataset(") < impl.index("trainer.train()")
    assert impl.index("grant.assert_files") < impl.index("load_dataset(\"json\"")
    assert impl.rindex("grant.assert_files") > impl.index("load_dataset(\"json\"")      # and again after the load
