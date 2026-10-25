"""The encrypted software key is a ceremony tool, not an operational founder key.

Synthetic keys exist only inside the test process. The writer refuses the
repository, a symlink, an existing file, and a cloud-sync path.
"""
import os
import stat
from pathlib import Path

import pytest

from orca.founder_key_store import (
    AES_256_CBC_OID,
    HMAC_SHA256_OID,
    PBES2_OID,
    PBKDF2_ITERATIONS,
    PBKDF2_OID,
    FounderKeyStoreError,
    describe_encrypted_private_key,
    ssh_ed25519_sk_is_not_enrollment_compatible,
    write_encrypted_software_key,
)

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = b"synthetic-test-password"


def _synthetic():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


def _raw(private) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    return private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def test_best_available_encryption_does_not_name_the_cipher():
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption

    chosen = BestAvailableEncryption(PASSWORD)
    assert vars(chosen) == {"password": PASSWORD}
    assert ssh_ed25519_sk_is_not_enrollment_compatible() == "hardware_sk_not_compatible"
    source = (ROOT / "orca" / "founder_key_store.py").read_text(encoding="utf-8")
    assert "Ed25519PrivateKey.generate" not in source
    assert "O_EXCL" in source and "O_NOFOLLOW" in source


def test_encrypted_file_uses_the_parsed_algorithm_and_refuses_a_wrong_password(tmp_path):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = _synthetic()
    seed = _raw(key)
    destination = tmp_path / "synthetic-founder.pem"
    previous = os.umask(0)
    try:
        described = write_encrypted_software_key(destination, key, PASSWORD)
    finally:
        os.umask(previous)
    payload = destination.read_bytes()
    parsed = describe_encrypted_private_key(payload)
    assert parsed["encryption"] == "PBES2"
    assert parsed["encryption_oid"] == PBES2_OID
    assert parsed["kdf"] == "PBKDF2-HMAC-SHA256"
    assert parsed["kdf_oid"] == PBKDF2_OID
    assert parsed["prf_oid"] == HMAC_SHA256_OID
    assert parsed["cipher"] == "AES-256-CBC"
    assert parsed["cipher_oid"] == AES_256_CBC_OID
    assert parsed["iterations"] == PBKDF2_ITERATIONS == 600000
    assert parsed == {key: value for key, value in described.items() if key in parsed}
    assert seed not in payload
    assert b"PRIVATE KEY" in payload and b"ENCRYPTED PRIVATE KEY" in payload
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    loaded = load_pem_private_key(payload, password=PASSWORD)
    assert _raw(loaded) == seed
    with pytest.raises(ValueError):
        load_pem_private_key(payload, password=b"wrong-password-value")


def test_creation_refuses_symlink_overwrite_repository_and_cloud_sync(tmp_path):
    key = _synthetic()
    target = tmp_path / "target.pem"
    target.write_bytes(b"untouched")
    planted = tmp_path / "planted.pem"
    planted.symlink_to(target)
    with pytest.raises(FounderKeyStoreError) as symlink_error:
        write_encrypted_software_key(planted, key, PASSWORD)
    assert symlink_error.value.code == "symlink_refused"
    assert target.read_bytes() == b"untouched"
    real = tmp_path / "real.pem"
    write_encrypted_software_key(real, key, PASSWORD)
    first = real.read_bytes()
    with pytest.raises(FounderKeyStoreError) as overwrite_error:
        write_encrypted_software_key(real, key, PASSWORD)
    assert overwrite_error.value.code == "exclusive_create_refused"
    assert real.read_bytes() == first
    inside = ROOT / "synthetic-founder-refused.pem"
    with pytest.raises(FounderKeyStoreError) as repo_error:
        write_encrypted_software_key(inside, key, PASSWORD)
    assert repo_error.value.code == "repository_path_refused"
    assert not inside.exists()
    cloud = tmp_path / "Dropbox" / "founder.pem"
    with pytest.raises(FounderKeyStoreError) as cloud_error:
        write_encrypted_software_key(cloud, key, PASSWORD)
    assert cloud_error.value.code == "cloud_sync_path_refused"
    assert not cloud.exists()
    with pytest.raises(FounderKeyStoreError) as password_error:
        write_encrypted_software_key(tmp_path / "short.pem", key, b"too-short")
    assert password_error.value.code == "password_refused"
    assert not (tmp_path / "short.pem").exists()
    with pytest.raises(FounderKeyStoreError) as relative_error:
        write_encrypted_software_key(Path("founder.pem"), key, PASSWORD)
    assert relative_error.value.code == "path_not_absolute"
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(FounderKeyStoreError) as parent_error:
        write_encrypted_software_key(linked_parent / "through-link.pem", key, PASSWORD)
    assert parent_error.value.code == "symlink_refused"
    assert not (tmp_path / "through-link.pem").exists()
