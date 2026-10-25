"""Encrypted software-key file for the founder ceremony.

This module does not generate a key. The caller passes a key that already
exists in their own process. Tests must pass a synthetic key and a path
outside the repository. Nothing here writes an operational founder key.

``BestAvailableEncryption`` is not used. In cryptography 50.0.2 that class
stores only a password. The installed OpenSSL 3.0.13 backend then calls
``PEM_write_bio_PKCS8PrivateKey`` with the cipher name ``aes-256-cbc``, and
the PEM it emits is PBES2 / PBKDF2-HMAC-SHA256 / AES-256-CBC at 2048
iterations. That count is OpenSSL's default, not a parameter of the Python
class, and a later library can change it without renaming the class.

The writer below builds PBES2 itself and records the algorithm that
``describe_encrypted_private_key`` reads back from the file:

- PBES2, OID 1.2.840.113549.1.5.13
- PBKDF2-HMAC-SHA256, OID 1.2.840.113549.1.5.12 and 1.2.840.113549.2.9
- 600000 iterations, 16-byte salt, 32-byte derived key
- AES-256-CBC, OID 2.16.840.1.101.3.4.1.42, 16-byte IV

SSH ``ed25519-sk`` is not a compatible substitute. The enrollment verifier
checks a 64-byte signature over ``domain || canonical JSON`` with a raw
32-byte public key. An SK signature is not that signature.
"""

from __future__ import annotations

import base64
import os
import stat
from pathlib import Path

PBKDF2_ITERATIONS = 600_000
PBES2_OID = "1.2.840.113549.1.5.13"
PBKDF2_OID = "1.2.840.113549.1.5.12"
HMAC_SHA256_OID = "1.2.840.113549.2.9"
AES_256_CBC_OID = "2.16.840.1.101.3.4.1.42"
_CLOUD = (
    "dropbox",
    "icloud",
    "onedrive",
    "google drive",
    "com~apple~clouddocs",
    "mobile documents",
)
_CREATE_FLAGS = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY | os.O_CLOEXEC


class FounderKeyStoreError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def ssh_ed25519_sk_is_not_enrollment_compatible() -> str:
    """FIDO/SSH SK signatures do not verify as raw enrollment signatures."""
    return "hardware_sk_not_compatible"


def _tlv(tag: int, body: bytes) -> bytes:
    length = len(body)
    if length < 128:
        encoded = bytes([length])
    else:
        raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
        encoded = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + encoded + body


def _oid(dotted: str) -> bytes:
    parts = [int(part) for part in dotted.split(".")]
    body = bytes([40 * parts[0] + parts[1]])
    for part in parts[2:]:
        encoded = [part & 0x7F]
        part >>= 7
        while part:
            encoded.append(0x80 | (part & 0x7F))
            part >>= 7
        body += bytes(reversed(encoded))
    return _tlv(0x06, body)


def _integer(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return _tlv(0x02, raw)


def _parse_tlv(data: bytes, offset: int = 0) -> tuple[int, bytes, int]:
    if offset + 2 > len(data):
        raise FounderKeyStoreError("algorithm_not_verified")
    tag = data[offset]
    length_byte = data[offset + 1]
    if length_byte < 128:
        length = length_byte
        start = offset + 2
    else:
        count = length_byte & 0x7F
        start = offset + 2 + count
        if count == 0 or start > len(data):
            raise FounderKeyStoreError("algorithm_not_verified")
        length = int.from_bytes(data[offset + 2:start], "big")
    end = start + length
    if end > len(data):
        raise FounderKeyStoreError("algorithm_not_verified")
    return tag, data[start:end], end


def _expect(data: bytes, tag: int) -> bytes:
    found, body, end = _parse_tlv(data, 0)
    if found != tag or end != len(data):
        raise FounderKeyStoreError("algorithm_not_verified")
    return body


def _oid_text(body: bytes) -> str:
    if not body:
        raise FounderKeyStoreError("algorithm_not_verified")
    parts = [str(body[0] // 40), str(body[0] % 40)]
    value = 0
    for byte in body[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(str(value))
            value = 0
    if value:
        raise FounderKeyStoreError("algorithm_not_verified")
    return ".".join(parts)


def _read_oid(data: bytes) -> tuple[str, bytes]:
    tag, body, end = _parse_tlv(data, 0)
    if tag != 0x06:
        raise FounderKeyStoreError("algorithm_not_verified")
    return _oid_text(body), data[end:]


def _read_integer(data: bytes) -> tuple[int, bytes]:
    tag, body, end = _parse_tlv(data, 0)
    if tag != 0x02 or not body or (len(body) > 1 and body[0] == 0 and not body[1] & 0x80):
        raise FounderKeyStoreError("algorithm_not_verified")
    if body[0] & 0x80:
        raise FounderKeyStoreError("algorithm_not_verified")
    return int.from_bytes(body, "big"), data[end:]


def describe_encrypted_private_key(pem: bytes) -> dict:
    """Read the encryption parameters from a PEM. This does not decrypt it."""
    text = pem.decode("ascii")
    lines = [line.strip() for line in text.splitlines() if line and not line.startswith("-----")]
    der = base64.b64decode("".join(lines), validate=True)
    body = _expect(der, 0x30)
    algorithm, encrypted = _split_one(body, 0x30)
    ciphertext = _expect(encrypted, 0x04)
    pbes_oid, parameters = _read_oid(algorithm)
    if pbes_oid != PBES2_OID:
        raise FounderKeyStoreError("algorithm_not_verified")
    params = _expect(parameters, 0x30)
    kdf, cipher = _split_one(params, 0x30)
    kdf_oid, kdf_rest = _read_oid(kdf)
    if kdf_oid != PBKDF2_OID:
        raise FounderKeyStoreError("algorithm_not_verified")
    kdf_params = _expect(kdf_rest, 0x30)
    salt_tag, salt, salt_end = _parse_tlv(kdf_params, 0)
    if salt_tag != 0x04 or len(salt) != 16:
        raise FounderKeyStoreError("algorithm_not_verified")
    iterations, after_iterations = _read_integer(kdf_params[salt_end:])
    key_length, after_length = _read_integer(after_iterations)
    prf = _expect(after_length, 0x30)
    prf_oid, prf_rest = _read_oid(prf)
    if prf_oid != HMAC_SHA256_OID or _expect(prf_rest, 0x05) != b"":
        raise FounderKeyStoreError("algorithm_not_verified")
    cipher_oid, iv_bytes = _read_oid(_expect(cipher, 0x30))
    iv = _expect(iv_bytes, 0x04)
    if cipher_oid != AES_256_CBC_OID or len(iv) != 16 or key_length != 32:
        raise FounderKeyStoreError("algorithm_not_verified")
    if not ciphertext:
        raise FounderKeyStoreError("algorithm_not_verified")
    return {
        "encryption": "PBES2",
        "encryption_oid": pbes_oid,
        "kdf": "PBKDF2-HMAC-SHA256",
        "kdf_oid": kdf_oid,
        "prf_oid": prf_oid,
        "cipher": "AES-256-CBC",
        "cipher_oid": cipher_oid,
        "iterations": iterations,
        "key_length": key_length,
        "salt_length": len(salt),
        "iv_length": len(iv),
    }


def _split_one(data: bytes, tag: int) -> tuple[bytes, bytes]:
    found, body, end = _parse_tlv(data, 0)
    if found != tag:
        raise FounderKeyStoreError("algorithm_not_verified")
    return body, data[end:]


def _location_problem(path: Path) -> str | None:
    if not path.is_absolute() or path.name in ("", ".", ".."):
        return "path_not_absolute"
    lexical = path.as_posix().casefold()
    if any(marker in lexical for marker in _CLOUD):
        return "cloud_sync_path_refused"
    probe = path.parent
    for _ in range(64):
        marker = probe / ".git"
        if marker.exists() or marker.is_symlink():
            return "repository_path_refused"
        if probe.parent == probe:
            break
        probe = probe.parent
    return None


def _pem(der: bytes) -> bytes:
    body = base64.encodebytes(der).decode("ascii")
    return f"-----BEGIN ENCRYPTED PRIVATE KEY-----\n{body}-----END ENCRYPTED PRIVATE KEY-----\n".encode()


def _encrypt(private_key, password: bytes) -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives import hashes, padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

    try:
        public = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        # In-memory PrivateKeyInfo only. The bytes that reach disk are the
        # encrypted PEM below, never this DER and never a raw seed.
        inner = private_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    except Exception as exc:
        raise FounderKeyStoreError("key_not_raw_ed25519") from exc
    if len(public) != 32:
        raise FounderKeyStoreError("key_not_raw_ed25519")
    salt = os.urandom(16)
    iv = os.urandom(16)
    derived = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    ).derive(password)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(inner) + padder.finalize()
    encryptor = Cipher(algorithms.AES(derived), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    null = _tlv(0x05, b"")
    prf = _tlv(0x30, _oid(HMAC_SHA256_OID) + null)
    kdf_params = _tlv(0x30, _tlv(0x04, salt) + _integer(PBKDF2_ITERATIONS) + _integer(32) + prf)
    kdf = _tlv(0x30, _oid(PBKDF2_OID) + kdf_params)
    scheme = _tlv(0x30, _oid(AES_256_CBC_OID) + _tlv(0x04, iv))
    algorithm = _tlv(0x30, _oid(PBES2_OID) + _tlv(0x30, kdf + scheme))
    der = _tlv(0x30, algorithm + _tlv(0x04, ciphertext))
    return _pem(der), public


def write_encrypted_software_key(destination: Path, private_key, password: bytes) -> dict:
    """Create an encrypted PKCS#8 file with O_EXCL|O_NOFOLLOW and mode 0600.

    The destination must be an absolute path outside every git worktree and
    outside a cloud-sync directory. An existing file or a symlink is refused.
    """
    path = Path(destination)
    if not isinstance(password, bytes) or len(password) < 16 or len(password) > 1024:
        raise FounderKeyStoreError("password_refused")
    problem = _location_problem(path)
    if problem:
        raise FounderKeyStoreError(problem)
    if path.is_symlink():
        raise FounderKeyStoreError("symlink_refused")
    if path.exists():
        raise FounderKeyStoreError("exclusive_create_refused")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise FounderKeyStoreError("symlink_refused" if path.parent.is_symlink() else "parent_absent")
    pem, public = _encrypt(private_key, password)
    if public in pem:
        raise FounderKeyStoreError("plaintext_key_refused")
    parent_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        parent = os.open(path.parent, parent_flags)
    except OSError as exc:
        raise FounderKeyStoreError("symlink_refused") from exc
    fd = None
    created = False
    try:
        try:
            fd = os.open(path.name, _CREATE_FLAGS, 0o600, dir_fd=parent)
        except OSError as exc:
            raise FounderKeyStoreError("exclusive_create_refused") from exc
        created = True
        written = os.write(fd, pem)
        if written != len(pem):
            raise FounderKeyStoreError("key_store_incomplete")
        info = os.fstat(fd)
        if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise FounderKeyStoreError("permission_refused")
        os.fsync(fd)
    except Exception:
        if created:
            try:
                os.unlink(path.name, dir_fd=parent)
            except OSError:
                pass
        raise
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)
    try:
        described = describe_encrypted_private_key(path.read_bytes())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if described["iterations"] != PBKDF2_ITERATIONS or described["kdf"] != "PBKDF2-HMAC-SHA256" or described["cipher"] != "AES-256-CBC":
        path.unlink(missing_ok=True)
        raise FounderKeyStoreError("algorithm_not_verified")
    _confirm_roundtrip(path, password, public)
    described["mode"] = 0o600
    described["nofollow"] = True
    described["exclusive"] = True
    return described


def _confirm_roundtrip(path: Path, password: bytes, public: bytes) -> None:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key

    try:
        loaded = load_pem_private_key(path.read_bytes(), password=password)
        confirmed = loaded.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise FounderKeyStoreError("key_roundtrip_failed") from exc
    if confirmed != public:
        path.unlink(missing_ok=True)
        raise FounderKeyStoreError("key_roundtrip_failed")
