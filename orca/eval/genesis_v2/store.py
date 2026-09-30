"""Private-corpus storage boundary. The default is NoStore: with nothing configured, every read/write raises — privacy is never faked.

Backends: an encrypted artifact (AES-256-GCM; key from the environment, path OUTSIDE the repository) and validated descriptors for a separate
private GitHub repository / private object store (network transport is deliberately not implemented here: the owner supplies it).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orca.eval.genesis_v2 import spec

PUBLIC_REPO_SLUG = "Guruprasath-Annadurai/Orneur"
KINDS = ("PRIVATE_GITHUB_REPO", "PRIVATE_OBJECT_STORE", "ENCRYPTED_ARTIFACT")


class PrivateStorageNotConfigured(RuntimeError):
    pass


class PrivateStorageViolation(ValueError):
    pass


class PrivateStorageIntegrityError(RuntimeError):
    """Authentication/consistency failure while reading a private corpus. Always fails closed; never carries key or plaintext material."""


class PrivateCorpusStore(Protocol):
    def describe(self) -> dict: ...
    def write_corpus(self, corpus_id: str, splits: dict) -> str: ...
    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes: ...


class NoStore:
    """Default. Nothing configured => nothing can be stored or read."""
    def describe(self) -> dict:
        return {"kind": "NONE", "configured": False}

    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        raise PrivateStorageNotConfigured("no private storage boundary is configured; refusing to write a private corpus")

    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        raise PrivateStorageNotConfigured("no private storage boundary is configured; refusing to read a private split")


def _repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        return Path(out).resolve()
    except Exception:
        return Path(__file__).resolve().parents[3]


def _inside_repo(path: Path, root: Path | None = None) -> bool:
    root = (root or _repo_root()).resolve()
    p = path.resolve()
    return p == root or root in p.parents


MAGIC = b"GCE2ENC1"
_CORPUS_ID = re.compile(r"^gce2c-[0-9a-f]{16,64}$")


def corpus_digest_of(split_digests: dict) -> str:
    """Corpus-level digest: SHA256 over the canonical map of per-split plaintext digests (both private splits are mandatory)."""
    if set(split_digests) != set(spec.PRIVATE_SPLITS):
        raise PrivateStorageViolation("a corpus digest requires exactly the private splits " + str(spec.PRIVATE_SPLITS))
    return hashlib.sha256(json.dumps(split_digests, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EncryptedFileStore:
    """Authenticated encrypted artifact backend (AES-256-GCM).

    Layout: <dir>/<corpus_id>/{SCREEN.enc, QUALIFICATION_HOLDOUT.enc, SEAL.enc}. Each file = MAGIC | header_len(4) | header(JSON) | nonce(12) | ciphertext+tag.
    The header (eval_version, corpus_id, split, plaintext sha256) is bound as AEAD associated data, so any header edit, file swap between splits or
    corpora, truncation or bit flip fails authentication. The SEAL (written LAST) authenticates the corpus digest; a corpus without a valid SEAL
    is a partial write and is never readable. Ciphertext is written to an exclusive temp file (no plaintext ever touches disk), fsynced, then
    published with link() so an existing artifact can never be overwritten (write-once). Directories 0700, files 0400.
    Key material lives only in the AESGCM object: the store refuses to be pickled/copied and its repr shows no secrets.
    Backup/recovery policy: see GENESIS_CAPABILITY_EVAL_V2_STORAGE_POLICY.md (ciphertext-only backups via export_backup; key held separately; key loss => fresh corpus version).
    """

    def __init__(self, directory: Path, key: bytes, *, repo_root: Path | None = None):
        if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
            raise PrivateStorageViolation("encryption key must be exactly 32 bytes")
        if len(set(key)) < 12:
            raise PrivateStorageViolation("encryption key has too little entropy")
        directory = Path(directory)
        if _inside_repo(directory, repo_root):
            raise PrivateStorageViolation("encrypted private artifacts must live OUTSIDE the repository working tree")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # declared in the 'qualification' extra
        except Exception as e:
            raise PrivateStorageNotConfigured("the 'cryptography' package (pip install '.[qualification]') is required for the encrypted artifact store") from e
        self._aead = AESGCM(bytes(key))
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._dir, 0o700)

    def __repr__(self) -> str:
        return f"EncryptedFileStore(dir={self._dir.name!r}, key=<redacted>)"

    def __getstate__(self):
        raise TypeError("EncryptedFileStore holds key material and must not be serialized")

    def describe(self) -> dict:
        return {"kind": "ENCRYPTED_ARTIFACT", "configured": True, "cipher": "AES-256-GCM", "key_in_repository": False, "write_once": True}

    # -- internals -------------------------------------------------------------------------------------------------------------------
    def _cdir(self, corpus_id: str) -> Path:
        if not _CORPUS_ID.match(corpus_id):
            raise PrivateStorageViolation("corpus_id must look like gce2c-<hex>")
        return self._dir / corpus_id

    def _seal_blob(self, header: dict, payload: bytes) -> bytes:
        h = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        nonce = os.urandom(12)
        return MAGIC + struct.pack(">I", len(h)) + h + nonce + self._aead.encrypt(nonce, payload, MAGIC + h)

    def _open_blob(self, blob: bytes) -> tuple:
        try:
            if blob[:8] != MAGIC:
                raise ValueError
            (n,) = struct.unpack(">I", blob[8:12])
            h = blob[12:12 + n]
            nonce = blob[12 + n:24 + n]
            if len(h) != n or len(nonce) != 12:
                raise ValueError
            header = json.loads(h)
            return header, self._aead.decrypt(nonce, blob[24 + n:], MAGIC + h)
        except Exception:
            raise PrivateStorageIntegrityError("private artifact failed authentication or is malformed (fail closed)") from None

    def _publish(self, path: Path, blob: bytes) -> None:
        tmp = path.with_name(f".tmp-{os.urandom(8).hex()}")
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)          # ciphertext only
                f.flush()
                os.fsync(f.fileno())
            os.link(tmp, path)         # atomic, fails if the target exists: never overwrites
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    # -- API -------------------------------------------------------------------------------------------------------------------------
    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        """Encrypt and store both private splits, then SEAL. Returns the corpus digest. Refuses to overwrite anything."""
        if set(splits) != set(spec.PRIVATE_SPLITS) or not all(isinstance(v, (bytes, bytearray)) for v in splits.values()):
            raise PrivateStorageViolation("write_corpus needs bytes for exactly " + str(spec.PRIVATE_SPLITS))
        cdir = self._cdir(corpus_id)
        cdir.mkdir(mode=0o700, exist_ok=False)                # a corpus id can be used once
        digests = {s: hashlib.sha256(bytes(v)).hexdigest() for s, v in splits.items()}
        cdig = corpus_digest_of(digests)
        for s in spec.PRIVATE_SPLITS:
            hdr = {"eval_version": spec.EVAL_VERSION, "corpus_id": corpus_id, "split": s, "split_sha256": digests[s]}
            self._publish(cdir / f"{s}.enc", self._seal_blob(hdr, bytes(splits[s])))
        seal_hdr = {"eval_version": spec.EVAL_VERSION, "corpus_id": corpus_id, "split": "SEAL", "corpus_digest": cdig}
        self._publish(cdir / "SEAL.enc", self._seal_blob(seal_hdr, json.dumps(digests, sort_keys=True).encode()))
        return cdig

    def _verified_seal(self, corpus_id: str, expected_corpus_digest: str) -> dict:
        cdir = self._cdir(corpus_id)
        try:
            header, payload = self._open_blob((cdir / "SEAL.enc").read_bytes())
        except FileNotFoundError:
            raise PrivateStorageIntegrityError("corpus has no SEAL (partial or missing write)") from None
        digests = json.loads(payload)
        if (header.get("eval_version"), header.get("corpus_id"), header.get("split")) != (spec.EVAL_VERSION, corpus_id, "SEAL"):
            raise PrivateStorageIntegrityError("SEAL metadata mismatch")
        if header.get("corpus_digest") != corpus_digest_of(digests) or header.get("corpus_digest") != expected_corpus_digest:
            raise PrivateStorageIntegrityError("corpus digest mismatch")
        return digests

    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        if split not in spec.PRIVATE_SPLITS:
            raise PrivateStorageViolation(f"{split!r} is not a private split")
        digests = self._verified_seal(corpus_id, expected_corpus_digest)
        try:
            blob = (self._cdir(corpus_id) / f"{split}.enc").read_bytes()
        except FileNotFoundError:
            raise PrivateStorageIntegrityError("split artifact missing") from None
        header, plain = self._open_blob(blob)
        if (header.get("eval_version"), header.get("corpus_id"), header.get("split")) != (spec.EVAL_VERSION, corpus_id, split):
            raise PrivateStorageIntegrityError("split metadata mismatch")
        got = hashlib.sha256(plain).hexdigest()
        if got != header.get("split_sha256") or got != digests.get(split):
            raise PrivateStorageIntegrityError("split digest mismatch")
        return plain

    def stray_temp_files(self, corpus_id: str) -> list:
        """Interrupted writes leave only .tmp-* ciphertext; they are never readable as data. Report them for cleanup."""
        return sorted(p.name for p in self._cdir(corpus_id).glob(".tmp-*"))

    def export_backup(self, corpus_id: str, dest: Path, *, expected_corpus_digest: str) -> list:
        """Copy the VERIFIED ciphertext files verbatim (no decryption, no key needed in the backup location). dest must be outside the repository."""
        self._verified_seal(corpus_id, expected_corpus_digest)
        dest = Path(dest)
        if _inside_repo(dest):
            raise PrivateStorageViolation("backups must not be placed inside the repository")
        dest.mkdir(parents=True, exist_ok=True, mode=0o700)
        out = []
        for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"):
            shutil.copyfile(self._cdir(corpus_id) / name, dest / name)
            os.chmod(dest / name, 0o400)
            out.append(name)
        return out


MAGIC_ASYM = b"GCE2ENC2"


def generate_vault_keypair() -> tuple:
    """A NEW X25519 keypair for the write-only/read-only vault split: (private_key_bytes, public_key_bytes), each 32
    raw bytes. The public key is safe to hand to a generator identity -- it can encrypt but never decrypt anything
    with it. The private key must be held ONLY by a genuinely authorized reader identity (the qualification-runner /
    creation-time-verifier path through operational_boundary.py) and must never be given to a generator."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    sk = X25519PrivateKey.generate()
    priv = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return priv, pub


def _hkdf_key(shared_secret: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"orneur-genesis-v2-vault-envelope-v2").derive(shared_secret)


class EncryptedVaultWriter:
    """WRITE-ONLY vault capability: constructed from ONLY the vault's PUBLIC X25519 key -- there is no private key
    byte anywhere in this object's state (see `vars()` of any instance), and this class defines no method that could
    decrypt a blob. This is genuine cryptographic write/read isolation, not an API convention a caller could route
    around: even a caller with full access to this object's internals (every attribute, every method) has no path to
    plaintext, because the mathematical capability to derive the decryption key does not exist here.

    Each write generates a FRESH, one-time X25519 ephemeral keypair, ECDH's it against the vault's public key to
    derive a one-time AES-256-GCM key via HKDF, encrypts with it, stores the ephemeral PUBLIC key in the blob header
    (needed by a genuine reader to reproduce the same derivation with the vault PRIVATE key), and discards the
    ephemeral private key and derived AES key immediately after use -- this object never retains either."""

    def __init__(self, directory: Path, vault_public_key: bytes, *, repo_root: Path | None = None):
        if not isinstance(vault_public_key, (bytes, bytearray)) or len(vault_public_key) != 32:
            raise PrivateStorageViolation("vault_public_key must be exactly 32 bytes (X25519 public key)")
        directory = Path(directory)
        if _inside_repo(directory, repo_root):
            raise PrivateStorageViolation("encrypted private artifacts must live OUTSIDE the repository working tree")
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
            X25519PublicKey.from_public_bytes(bytes(vault_public_key))   # validate shape now, fail closed early
        except Exception as e:
            raise PrivateStorageNotConfigured("the 'cryptography' package (pip install '.[qualification]') is required for the encrypted artifact store") from e
        self._pub = bytes(vault_public_key)
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._dir, 0o700)

    def __repr__(self) -> str:
        return f"EncryptedVaultWriter(dir={self._dir.name!r}, capability=WRITE_ONLY, has_private_key=False)"

    def __getstate__(self):
        raise TypeError("EncryptedVaultWriter must not be serialized")

    def describe(self) -> dict:
        return {"kind": "ENCRYPTED_ARTIFACT", "configured": True, "cipher": "X25519+HKDF-SHA256+AES-256-GCM", "capability": "WRITE_ONLY", "write_once": True}

    def _cdir(self, corpus_id: str) -> Path:
        if not _CORPUS_ID.match(corpus_id):
            raise PrivateStorageViolation("corpus_id must look like gce2c-<hex>")
        return self._dir / corpus_id

    def _seal_blob(self, header: dict, payload: bytes) -> bytes:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives import serialization
        eph_sk = X25519PrivateKey.generate()
        eph_pub = eph_sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        shared = eph_sk.exchange(X25519PublicKey.from_public_bytes(self._pub))
        aes_key = _hkdf_key(shared)
        h = {**header, "ephemeral_public_key": eph_pub.hex()}
        hjson = json.dumps(h, sort_keys=True, separators=(",", ":")).encode()
        nonce = os.urandom(12)
        blob = MAGIC_ASYM + struct.pack(">I", len(hjson)) + hjson + nonce + AESGCM(aes_key).encrypt(nonce, payload, MAGIC_ASYM + hjson)
        del eph_sk, aes_key, shared   # not a memory-scrubbing guarantee, but nothing above stores these past this call
        return blob

    def _publish(self, path: Path, blob: bytes) -> None:
        tmp = path.with_name(f".tmp-{os.urandom(8).hex()}")
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.link(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        """Encrypt and store both private splits, then SEAL. Returns the corpus digest. Always requires exactly the
        two private splits together (an atomic corpus write) -- callers scoped to fewer classes never reach this
        method with a mismatched set; see operational_boundary.GeneratorWriteHandle."""
        if set(splits) != set(spec.PRIVATE_SPLITS) or not all(isinstance(v, (bytes, bytearray)) for v in splits.values()):
            raise PrivateStorageViolation("write_corpus needs bytes for exactly " + str(spec.PRIVATE_SPLITS))
        cdir = self._cdir(corpus_id)
        cdir.mkdir(mode=0o700, exist_ok=False)
        digests = {s: hashlib.sha256(bytes(v)).hexdigest() for s, v in splits.items()}
        cdig = corpus_digest_of(digests)
        for s in spec.PRIVATE_SPLITS:
            hdr = {"eval_version": spec.EVAL_VERSION, "corpus_id": corpus_id, "split": s, "split_sha256": digests[s]}
            self._publish(cdir / f"{s}.enc", self._seal_blob(hdr, bytes(splits[s])))
        seal_hdr = {"eval_version": spec.EVAL_VERSION, "corpus_id": corpus_id, "split": "SEAL", "corpus_digest": cdig}
        self._publish(cdir / "SEAL.enc", self._seal_blob(seal_hdr, json.dumps(digests, sort_keys=True).encode()))
        return cdig

    def stray_temp_files(self, corpus_id: str) -> list:
        return sorted(p.name for p in self._cdir(corpus_id).glob(".tmp-*"))


class EncryptedVaultReader:
    """READ capability: constructed from the vault's PRIVATE X25519 key. Only an entity with a genuine, ledger-gated
    read authorization (operational_boundary.require_private_split_access / authorized_manifest_verification_bytes)
    should ever hold one of these -- never a generator. Reproduces the SAME per-blob AES key an `EncryptedVaultWriter`
    derived, via ECDH(vault_private_key, ephemeral_public_key_from_header), so it can decrypt anything a writer for
    the SAME vault public key produced, without ever needing to see or reuse an ephemeral private key."""

    def __init__(self, directory: Path, vault_private_key: bytes, *, repo_root: Path | None = None):
        if not isinstance(vault_private_key, (bytes, bytearray)) or len(vault_private_key) != 32:
            raise PrivateStorageViolation("vault_private_key must be exactly 32 bytes (X25519 private key)")
        directory = Path(directory)
        if _inside_repo(directory, repo_root):
            raise PrivateStorageViolation("encrypted private artifacts must live OUTSIDE the repository working tree")
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            X25519PrivateKey.from_private_bytes(bytes(vault_private_key))   # validate shape now, fail closed early
        except Exception as e:
            raise PrivateStorageNotConfigured("the 'cryptography' package (pip install '.[qualification]') is required for the encrypted artifact store") from e
        self._priv = bytes(vault_private_key)
        self._dir = directory

    def __repr__(self) -> str:
        return f"EncryptedVaultReader(dir={self._dir.name!r}, capability=READ, key=<redacted>)"

    def __getstate__(self):
        raise TypeError("EncryptedVaultReader holds key material and must not be serialized")

    def describe(self) -> dict:
        return {"kind": "ENCRYPTED_ARTIFACT", "configured": True, "cipher": "X25519+HKDF-SHA256+AES-256-GCM", "capability": "READ", "write_once": True}

    def _cdir(self, corpus_id: str) -> Path:
        if not _CORPUS_ID.match(corpus_id):
            raise PrivateStorageViolation("corpus_id must look like gce2c-<hex>")
        return self._dir / corpus_id

    def _open_blob(self, blob: bytes) -> tuple:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        try:
            if blob[:8] != MAGIC_ASYM:
                raise ValueError
            (n,) = struct.unpack(">I", blob[8:12])
            h = blob[12:12 + n]
            nonce = blob[12 + n:24 + n]
            if len(h) != n or len(nonce) != 12:
                raise ValueError
            header = json.loads(h)
            eph_pub = bytes.fromhex(header["ephemeral_public_key"])
            sk = X25519PrivateKey.from_private_bytes(self._priv)
            shared = sk.exchange(X25519PublicKey.from_public_bytes(eph_pub))
            aes_key = _hkdf_key(shared)
            plain = AESGCM(aes_key).decrypt(nonce, blob[24 + n:], MAGIC_ASYM + h)
            return header, plain
        except Exception:
            raise PrivateStorageIntegrityError("private artifact failed authentication or is malformed (fail closed)") from None

    def _verified_seal(self, corpus_id: str, expected_corpus_digest: str) -> dict:
        cdir = self._cdir(corpus_id)
        try:
            header, payload = self._open_blob((cdir / "SEAL.enc").read_bytes())
        except FileNotFoundError:
            raise PrivateStorageIntegrityError("corpus has no SEAL (partial or missing write)") from None
        digests = json.loads(payload)
        if (header.get("eval_version"), header.get("corpus_id"), header.get("split")) != (spec.EVAL_VERSION, corpus_id, "SEAL"):
            raise PrivateStorageIntegrityError("SEAL metadata mismatch")
        if header.get("corpus_digest") != corpus_digest_of(digests) or header.get("corpus_digest") != expected_corpus_digest:
            raise PrivateStorageIntegrityError("corpus digest mismatch")
        return digests

    def read_split(self, corpus_id: str, split: str, *, expected_corpus_digest: str) -> bytes:
        if split not in spec.PRIVATE_SPLITS:
            raise PrivateStorageViolation(f"{split!r} is not a private split")
        digests = self._verified_seal(corpus_id, expected_corpus_digest)
        try:
            blob = (self._cdir(corpus_id) / f"{split}.enc").read_bytes()
        except FileNotFoundError:
            raise PrivateStorageIntegrityError("split artifact missing") from None
        header, plain = self._open_blob(blob)
        if (header.get("eval_version"), header.get("corpus_id"), header.get("split")) != (spec.EVAL_VERSION, corpus_id, split):
            raise PrivateStorageIntegrityError("split metadata mismatch")
        got = hashlib.sha256(plain).hexdigest()
        if got != header.get("split_sha256") or got != digests.get(split):
            raise PrivateStorageIntegrityError("split digest mismatch")
        return plain

    def export_backup(self, corpus_id: str, dest: Path, *, expected_corpus_digest: str) -> list:
        """Copy the VERIFIED ciphertext files verbatim (no decryption performed to export; dest must be outside the repository)."""
        self._verified_seal(corpus_id, expected_corpus_digest)
        dest = Path(dest)
        if _inside_repo(dest):
            raise PrivateStorageViolation("backups must not be placed inside the repository")
        dest.mkdir(parents=True, exist_ok=True, mode=0o700)
        out = []
        for name in ("SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"):
            shutil.copyfile(self._cdir(corpus_id) / name, dest / name)
            os.chmod(dest / name, 0o400)
            out.append(name)
        return out


@dataclass(frozen=True)
class PrivateStoreConfig:
    kind: str
    location: str            # e.g. "owner/private-repo" or "s3://bucket/prefix"
    credential_env: str      # NAME of the env var holding a least-privilege credential; the value is never stored here

    def problems(self, public_repo: str = PUBLIC_REPO_SLUG) -> list:
        out = []
        if self.kind not in KINDS:
            out.append(f"kind must be one of {KINDS}")
        if not self.location or self.location.startswith("http://"):
            out.append("location missing or insecure")
        if self.location.strip().lower().rstrip("/").removesuffix(".git").endswith(public_repo.lower()):
            out.append("the private store must NOT be the public ORNEUR repository")
        if not self.credential_env or not self.credential_env.isidentifier():
            out.append("credential_env must be an environment variable NAME")
        return out


def owner_setup_preflight(env: dict | None = None, *, public_repo: str = PUBLIC_REPO_SLUG) -> dict:
    """Report exactly what the owner must set up. Never prints values; never invents anything."""
    env = os.environ if env is None else env
    missing = []
    store = env.get(spec.STORE_ENV, "")
    if not store:
        missing.append({"item": spec.STORE_ENV, "need": "'<KIND>:<location>' naming a PRIVATE GitHub repo / private object store / encrypted artifact location outside the repo"})
    else:
        kind, _, loc = store.partition(":")
        cfg = PrivateStoreConfig(kind, loc, spec.STORE_TOKEN_ENV)
        for p in cfg.problems(public_repo):
            missing.append({"item": spec.STORE_ENV, "need": p})
        if kind != "ENCRYPTED_ARTIFACT" and not env.get(spec.STORE_TOKEN_ENV):
            missing.append({"item": spec.STORE_TOKEN_ENV, "need": "least-privilege read credential for the private store, available only to the qualification runner"})
    if not env.get(spec.SECRET_ENV):
        missing.append({"item": spec.SECRET_ENV, "need": f">= {spec.MIN_SECRET_BYTES} cryptographically random bytes (hex/base64), generated once on a trusted machine and kept in a secret manager; never in git, CI logs or source"})
    else:
        from orca.eval.genesis_v2 import secret as _s
        try:
            _s.load_secret_from_env(env)
        except _s.SecretEntropyError as e:
            missing.append({"item": spec.SECRET_ENV, "need": f"present but invalid: {e}"})
    if store.startswith("ENCRYPTED_ARTIFACT") and not env.get(spec.ENC_KEY_ENV):
        missing.append({"item": spec.ENC_KEY_ENV, "need": "32-byte AES key from a secret manager (never committed)"})
    return {"status": "PRIVATE_STORAGE_CONFIGURED_UNVERIFIED" if not missing else "PRIVATE_STORAGE_NOT_CONFIGURED",
            "missing": missing, "note": "configuration presence is not proof of privacy; visibility must be independently verified by the owner"}
