"""Private-corpus storage boundary. The default is NoStore: with nothing configured, every read/write raises — privacy is never faked.

Backends: an encrypted artifact (AES-256-GCM; key from the environment, path OUTSIDE the repository) and validated descriptors for a separate
private GitHub repository / private object store (network transport is deliberately not implemented here: the owner supplies it).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
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


class PrivateCorpusStore(Protocol):
    def describe(self) -> dict: ...
    def write_split(self, split: str, payload: bytes) -> str: ...
    def read_split(self, split: str) -> bytes: ...


class NoStore:
    """Default. Nothing configured => nothing can be stored or read."""
    def describe(self) -> dict:
        return {"kind": "NONE", "configured": False}

    def write_split(self, split: str, payload: bytes) -> str:
        raise PrivateStorageNotConfigured("no private storage boundary is configured; refusing to write a private split")

    def read_split(self, split: str) -> bytes:
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


class EncryptedFileStore:
    """Authenticated encrypted artifact. Key material is supplied by the caller (from a secret manager), never read from the repo."""
    def __init__(self, directory: Path, key: bytes, *, repo_root: Path | None = None):
        if len(key) != 32:
            raise PrivateStorageViolation("encryption key must be exactly 32 bytes")
        if len(set(key)) < 12:
            raise PrivateStorageViolation("encryption key has too little entropy")
        directory = Path(directory)
        if _inside_repo(directory, repo_root):
            raise PrivateStorageViolation("encrypted private artifacts must live OUTSIDE the repository working tree")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # optional dependency; absent => storage unavailable
        except Exception as e:  # pragma: no cover - exercised only where cryptography is absent
            raise PrivateStorageNotConfigured("the 'cryptography' package is required for the encrypted artifact store") from e
        self._aead = AESGCM(key)
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def describe(self) -> dict:
        return {"kind": "ENCRYPTED_ARTIFACT", "configured": True, "cipher": "AES-256-GCM", "key_in_repository": False}

    def _path(self, split: str) -> Path:
        if split not in spec.PRIVATE_SPLITS:
            raise PrivateStorageViolation(f"{split!r} is not a private split")
        return self._dir / f"{split}.enc"

    def write_split(self, split: str, payload: bytes) -> str:
        path = self._path(split)
        nonce = os.urandom(12)
        aad = f"{spec.EVAL_VERSION}|{split}".encode()
        blob = nonce + self._aead.encrypt(nonce, payload, aad)
        with open(path, "xb") as f:   # write-once: an existing split is never overwritten
            f.write(blob)
        return hashlib.sha256(payload).hexdigest()

    def read_split(self, split: str) -> bytes:
        blob = self._path(split).read_bytes()
        aad = f"{spec.EVAL_VERSION}|{split}".encode()
        return self._aead.decrypt(blob[:12], blob[12:], aad)


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
