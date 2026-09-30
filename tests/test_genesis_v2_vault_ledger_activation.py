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


# ---------------------------------------------------------------- item 1: sentinel-preservation and failure-path regression tests
def test_vault_activation_preserves_pre_existing_content_on_success(tmp_path):
    """The core safety fix: a real vault directory may hold OTHER corpora already. A fresh activation must touch
    NONE of them -- only the one corpus_id (and backup dir) it creates for itself."""
    _need_crypto()
    repo = _repo(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    # A pre-existing REAL corpus already in the vault. Its content must be byte-for-byte untouched by the fresh
    # activation -- and it must remain a valid, scannable ciphertext-only artifact (ending in .enc) so the
    # activation's own permission/plaintext-sibling scan of the whole vault directory still legitimately passes,
    # exactly as it would for a real vault holding other real corpora.
    sentinel_dir = vault / "gce2c-deadbeefdeadbeef"
    sentinel_dir.mkdir(mode=0o700)
    sentinel_file = sentinel_dir / "SEAL.enc"
    sentinel_file.write_bytes(b"PRE-EXISTING-REAL-CORPUS-CONTENT-DO-NOT-TOUCH")
    os.chmod(sentinel_file, 0o400)

    act = VA.activate_test_vault(vault, repo)
    assert act["pass"] is True

    assert sentinel_dir.is_dir() and sentinel_file.is_file()
    assert sentinel_file.read_bytes() == b"PRE-EXISTING-REAL-CORPUS-CONTENT-DO-NOT-TOUCH"
    # only the sentinel corpus remains -- the activation's own corpus_id and backup dir were cleaned up
    remaining = {p.name for p in vault.iterdir()}
    assert remaining == {"gce2c-deadbeefdeadbeef"}


def test_vault_activation_preserves_pre_existing_content_when_isolation_fails(tmp_path):
    """The failure-path regression this item exists to close: an isolation failure must perform NO filesystem
    writes to vault_dir at all, let alone delete anything already there."""
    _need_crypto()
    repo = _repo(tmp_path)
    vault = repo / "vault"   # INSIDE the repo -- isolation check fails
    vault.mkdir(mode=0o700)
    sentinel = vault / "pre-existing-real-file.txt"
    sentinel.write_text("must survive a failed activation attempt")

    act = VA.activate_test_vault(vault, repo)
    assert act["pass"] is False and "isolated" in act["error"]
    assert sentinel.is_file() and sentinel.read_text() == "must survive a failed activation attempt"
    assert {p.name for p in vault.iterdir()} == {"pre-existing-real-file.txt"}


def test_vault_activation_preserves_pre_existing_content_when_an_unexpected_exception_occurs(tmp_path, monkeypatch):
    """Even a genuinely unexpected exception mid-activation (not merely the isolation-failure early return) must
    never touch anything the activation did not itself create."""
    _need_crypto()
    from orca.eval.genesis_v2 import store as ST
    repo = _repo(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    sentinel = vault / "pre-existing-real-file.txt"
    sentinel.write_text("must survive an exception mid-activation")

    def boom(self, *a, **k):
        raise RuntimeError("simulated unexpected failure")
    monkeypatch.setattr(ST.EncryptedVaultReader, "read_split", boom)

    act = VA.activate_test_vault(vault, repo)
    assert act["pass"] is False and act["error"] is not None
    assert sentinel.is_file() and sentinel.read_text() == "must survive an exception mid-activation"
    # the writer's own corpus_id directory it created before the simulated failure is still cleaned up
    remaining = {p.name for p in vault.iterdir()}
    assert remaining == {"pre-existing-real-file.txt"}


def test_vault_activation_backup_check_is_genuinely_computed_not_hardcoded(tmp_path, monkeypatch):
    """Item 2: backup_ciphertext_only must reflect a REAL export_backup() outcome. Simulate a genuine backup
    failure and confirm the check reports False (never a hardcoded True) with an honest NOT_TESTED explanation."""
    _need_crypto()
    from orca.eval.genesis_v2 import store as ST
    repo = _repo(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)

    def boom_export(self, *a, **k):
        raise ST.PrivateStorageIntegrityError("simulated backup failure")
    monkeypatch.setattr(ST.EncryptedVaultReader, "export_backup", boom_export)

    act = VA.activate_test_vault(vault, repo)
    assert act["checks"]["backup_ciphertext_only"] is False
    assert "NOT_TESTED" in act["checks"].get("backup_test_error", "")
    assert act["pass"] is False   # a failed backup check must fail the overall activation, never be silently ignored


def test_vault_activation_backup_is_verified_before_destructive_tamper_test(tmp_path):
    """The backup check must run against UNCORRUPTED content -- confirmed by observing that a successful activation
    (which necessarily ran the tamper test afterward) still reports a genuinely matching, non-hardcoded backup."""
    _need_crypto()
    repo = _repo(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    act = VA.activate_test_vault(vault, repo)
    assert act["pass"] is True
    assert act["checks"]["backup_ciphertext_only"] is True
    assert act["checks"]["tamper_detected"] is True   # both ran, in that order, and both genuinely passed


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
