"""Shared SYNTHETIC fixtures for the evalinfra tests. Keys here are ephemeral, in-process, test-only Ed25519 keys; nothing touches the repository's registries."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import authorization as A
from orca.eval.genesis_v2 import ledger as LG
from orca.eval.genesis_v2 import review as RV
from orca.eval.genesis_v2 import spec
from orca.evalinfra.access import ProtectedAccessRequest, ProtectedEvalGate

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
CODE = hashlib.sha256(b"synthetic-runner-code").hexdigest()
CORPUS = hashlib.sha256(b"synthetic-corpus-digest").hexdigest()
COMMIT = "a" * 40
ITEM = "gce2-" + "ab" * 12
PLACEHOLDER_HEX = hashlib.sha256(b"synthetic-test-placeholder").hexdigest()      # 64 hex chars, NOT a key of anything


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def need_crypto():
    pytest.importorskip("cryptography")


def keypair():
    need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    return sk, sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


@dataclass
class World:
    root: Path
    ledger_dir: Path
    replay: Path
    env: dict
    auth_sk: object
    rev_sk: object
    runner_doc_path: Path
    authority_path: Path
    reviewer_path: Path

    def request(self, **over) -> ProtectedAccessRequest:
        base = dict(runner_id="syn-runner", code_sha256=CODE, purpose=spec.PURPOSE_QUALIFICATION, split="QUALIFICATION_HOLDOUT", corpus_digest=CORPUS,
                    run_id="run-1", candidate_model_id="cand-x", candidate_revision="rev-1", candidate_lineage="lin-1", commit_sha=COMMIT,
                    authorization_purpose="QUALIFICATION", stage="STAGE_2", runner_class="SELF_HOSTED_CPU", timestamp_utc=ts(NOW),
                    authorization_record=self.auth(), reviewer_manifest=self.manifest())
        base.update(over)
        return ProtectedAccessRequest(**base)

    def auth(self, **over) -> dict:
        r = A.default_record()
        r.update({"authorization_id": "auth-" + "0f" * 8, "status": "AUTHORIZED", "commit_sha": COMMIT, "eval_version": spec.EVAL_VERSION,
                  "candidate": {"model_id": "cand-x", "revision": "rev-1"}, "permitted_stage": "STAGE_2", "permitted_runner_class": "SELF_HOSTED_CPU",
                  "permitted_purpose": "QUALIFICATION", "max_runs": 1, "max_spend_usd": 0, "issued_at": ts(NOW - timedelta(hours=1)),
                  "expires_at": ts(NOW + timedelta(days=1)), "authorizing_authority": {"identity": "syn-authority", "role": "OWNER", "key_id": "syn-authority"},
                  "gpu_allowed": False, "network_provider_inference_allowed": False})
        sign = over.pop("_sign", True)
        r.update(over)
        if sign:
            r["signature"] = self.auth_sk.sign(A.canonical_signing_bytes(r)).hex()
        return r

    def manifest(self, disposition="CLEAR", corpus=CORPUS, signer=None, reviewer_key_id="syn-reviewer") -> dict:
        rv = {"review_schema_version": RV.SCHEMA_VERSION, "item_id": ITEM, "eval_version": spec.EVAL_VERSION,
              "reviewer": {"identity": reviewer_key_id, "role": "PRIVATE_BENCHMARK_REVIEWER", "key_id": reviewer_key_id},
              "review_purpose": "CONTAMINATION_REVIEW", "corpus_digest": corpus, "similarity_evidence_digest": hashlib.sha256(b"evidence").hexdigest(),
              "disposition": disposition, "timestamp": ts(NOW - timedelta(hours=2)), "signature": ""}
        rv["signature"] = (signer or self.rev_sk).sign(RV.signing_bytes(rv)).hex()
        return RV.build_manifest([rv], corpus)

    def gate(self, **over) -> ProtectedEvalGate:
        kw = dict(env=self.env, expected_corpus_digest=CORPUS, revoked_authorization_ids=[], freeze={"frozen": True}, now=NOW,
                  expected_ledger_head={"seq": -1, "record_hash": LG.GENESIS_HASH})
        kw.update(over)
        return ProtectedEvalGate(self.root, self.ledger_dir, self.replay, **kw)


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, sort_keys=True))
    return path


def build_world(tmp_path: Path, *, runner_state="AUTHORIZED", with_authority=True, with_reviewer=True, env_ok=True) -> World:
    asec, apub = keypair()
    rsec, rpub = keypair()
    root = tmp_path / "synthetic_root"
    d = root / "docs/orneur/authorization"
    base = {"activation_timestamp": "2026-10-01T00:00:00Z", "expiry": None, "revoked": False}
    authority = {"schema_version": "genesis-v2-authority-registry/1", "records": ([{"id": "syn-authority", "role": "OWNER", "public_key_hex": apub, **base,
                 "permitted_authorization_classes": ["QUALIFICATION"], "permitted_eval_stages": ["STAGE_2"], "gpu_permission": False, "spend_permission": False,
                 "provider_inference_permission": False}] if with_authority else [])}
    reviewer = {"schema_version": "genesis-v2-reviewer-registry/1", "records": ([{"id": "syn-reviewer", "role": "PRIVATE_BENCHMARK_REVIEWER", "public_key_hex": rpub, **base,
                "allowed_review_domains": ["CONTAMINATION_REVIEW"], "allow_dual_role": False}] if with_reviewer else [])}
    runner = {"schema_version": "genesis-v2-qualification-runner-registry/1", "records": [{
        "runner_id": "syn-runner", "runner_class": "SELF_HOSTED_CPU", "os_runtime": "synthetic", "code_sha256": CODE, "allowed_purposes": [spec.PURPOSE_QUALIFICATION],
        "allowed_splits": ["QUALIFICATION_HOLDOUT"], "sandbox_image_digest": PLACEHOLDER_HEX, "semantic_engine_digest": PLACEHOLDER_HEX,
        "storage_backend_verification_digest": PLACEHOLDER_HEX, "ledger_database_identity_digest": PLACEHOLDER_HEX, "network_policy": "none",
        "credential_scope": {"private_store_read": True, "public_repo_write": False, "training_credentials": False, "unrelated_cloud_credentials": False, "developer_tokens": False},
        "state": runner_state}]}
    ap = _write(d / "AUTHORITY_REGISTRY.json", authority)
    rp = _write(d / "REVIEWER_REGISTRY.json", reviewer)
    np_ = _write(d / "QUALIFICATION_RUNNER_REGISTRY.json", runner)
    env = {spec.STORE_ENV: "ENCRYPTED_ARTIFACT:" + str(tmp_path / "synthetic_vault_location"), spec.VAULT_PRIVATE_KEY_ENV: PLACEHOLDER_HEX} if env_ok else {}
    return World(root, tmp_path / "ledger", tmp_path / "replay.jsonl", env, asec, rsec, np_, ap, rp)
