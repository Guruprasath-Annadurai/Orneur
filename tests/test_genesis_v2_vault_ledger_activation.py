"""Vault and ledger ACTIVATION admin modules: real round-trip mechanics with an ephemeral TEST key that is destroyed, and public-safe records
that carry no path/key/plaintext."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import ledger_admin as LA
from orca.eval.genesis_v2 import vault_admin as VA

ROOT = Path(__file__).resolve().parents[1]


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def _repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    return r


def test_vault_activation_succeeds_and_leaves_no_trace(tmp_path):
    _need_crypto()
    repo = _repo(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    act = VA.activate_test_vault(vault, repo)
    assert act["pass"] and act["error"] is None
    assert all(v is True for v in act["checks"].values())
    assert list(vault.iterdir()) == []                                   # everything destroyed afterward


def test_vault_activation_public_record_carries_no_path_or_key(tmp_path):
    _need_crypto()
    repo = _repo(tmp_path)
    vault = tmp_path / "some" / "very" / "specific" / "vault-name-xyz"
    vault.mkdir(parents=True, mode=0o700)
    act = VA.activate_test_vault(vault, repo)
    rec = VA.build_storage_verification_record(act, vault_dir=vault)
    blob = json.dumps(rec)
    assert str(vault) not in blob and "vault-name-xyz" not in blob and "specific" not in blob
    assert set(rec) == {"document", "schema_version", "store_type", "verification_timestamp", "store_descriptor_digest", "permission_policy_result",
                        "repository_isolation_result", "encryption_policy_result", "key_isolation_result", "backup_policy_result",
                        "verifier_code_sha256", "pass", "evidence_digests", "note"}
    assert rec["pass"] is True and len(rec["store_descriptor_digest"]) == 64


def test_vault_activation_fails_closed_when_not_isolated(tmp_path):
    _need_crypto()
    repo = _repo(tmp_path)
    vault = repo / "vault"
    vault.mkdir(mode=0o700)
    act = VA.activate_test_vault(vault, repo)
    assert not act["pass"] and "isolated" in act["error"]


def test_committed_vault_verification_record_is_valid_and_passed():
    rec = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_V2_VAULT_VERIFICATION.json").read_text())
    assert rec["pass"] is True and rec["store_type"] == "ENCRYPTED_ARTIFACT"
    assert rec["encryption_policy_result"] is True and rec["repository_isolation_result"] is True and rec["backup_policy_result"] is True
    assert "TEST activation only" in rec["note"]
    for forbidden in ("/Users/", "/home/", "corpus_secret", "-----BEGIN"):
        assert forbidden not in json.dumps(rec)


def test_ledger_activation_succeeds_empty_and_permissions_restrictive(tmp_path):
    repo = _repo(tmp_path)
    ledger_dir = tmp_path / "ledger"
    act = LA.activate_ledger(ledger_dir, repo)
    assert act["pass"] and all(v is True for v in act["checks"].values())
    rec = LA.build_deployment_record(act, ledger_dir=ledger_dir)
    blob = json.dumps(rec)
    assert str(ledger_dir) not in blob
    assert rec["no_benchmark_content_result"] is True and rec["integrity_controls_result"] is True


def test_ledger_activation_fails_closed_when_inside_repo(tmp_path):
    repo = _repo(tmp_path)
    act = LA.activate_ledger(repo / "ledger", repo)
    assert not act["pass"] and "inside" in act["error"]


def test_committed_ledger_deployment_record_is_valid_and_passed():
    rec = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_V2_LEDGER_DEPLOYMENT_RECORD.json").read_text())
    assert rec["pass"] is True and rec["backend"] == "sqlite" and rec["no_benchmark_content_result"] is True
    for forbidden in ("/Users/", "/home/"):
        assert forbidden not in json.dumps(rec)
