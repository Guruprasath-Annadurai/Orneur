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
