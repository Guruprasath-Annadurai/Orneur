"""Secret entropy and derivation. Every private item seed/id/commitment salt is HMAC(secret, ...) — unreachable without the secret.

Nothing here stores or invents a secret: the owner supplies one from a secret manager. A public observer holding this whole repository
cannot derive any private seed, id or salt (index, version, commit SHA and constants are HMAC *inputs*, never the key).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets

from orca.eval.genesis_v2 import spec


class SecretEntropyError(ValueError):
    pass


def generate_secret() -> bytes:
    """For the OWNER to run on a trusted machine and place in a secret manager. Never call this in CI and never commit the result."""
    return secrets.token_bytes(spec.MIN_SECRET_BYTES)


def _decode(raw: str) -> bytes:
    raw = raw.strip()
    try:
        b = bytes.fromhex(raw)
        if len(raw) % 2 == 0:
            return b
    except ValueError:
        pass
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as e:
        raise SecretEntropyError("secret must be hex or base64") from e


def public_derivable_candidates(extra: tuple = ()) -> set:
    """Byte strings a public observer could compute from the repository; a secret equal to any of them is rejected."""
    base = [spec.EVAL_VERSION, spec.CORPUS_VERSION, spec.V1_EVAL_VERSION, "genesis-corpus/1.0.0", "orneur", "ORNEUR", "genesis", "secret", "0", "1"]
    base += list(extra)
    out: set = set()
    for s in base:
        b = s.encode() if isinstance(s, str) else bytes(s)
        out.add(b)
        for h in (hashlib.sha256, hashlib.sha512, hashlib.sha1, hashlib.md5):
            out.add(h(b).digest())
    for n in range(0, 4096):
        out.add(hashlib.sha256(str(n).encode()).digest())
    return out


def validate_secret(secret: bytes, *, public_inputs: tuple = ()) -> bytes:
    if not isinstance(secret, (bytes, bytearray)):
        raise SecretEntropyError("secret must be bytes")
    secret = bytes(secret)
    if len(secret) < spec.MIN_SECRET_BYTES:
        raise SecretEntropyError(f"secret must be at least {spec.MIN_SECRET_BYTES} bytes")
    if len(set(secret)) < max(12, len(secret) // 4):
        raise SecretEntropyError("secret has too little byte diversity to be cryptographically random")
    half = len(secret) // 2
    if secret[:half] == secret[half:2 * half]:
        raise SecretEntropyError("secret is a repeated block")
    d = (secret[1] - secret[0]) % 256
    if all((secret[i + 1] - secret[i]) % 256 == d for i in range(len(secret) - 1)):
        raise SecretEntropyError("secret is an arithmetic sequence")
    for t in ("genesis", "orneur", "capability", "corpus", "qualification", "holdout", *[x for x in public_inputs if isinstance(x, str)]):
        if len(t) >= 6 and t.lower().encode() in secret.lower():
            raise SecretEntropyError("secret embeds a public/predictable string")
    cands = public_derivable_candidates(public_inputs)
    if secret in cands or secret[:spec.MIN_SECRET_BYTES] in cands:
        raise SecretEntropyError("secret equals a value derivable from public information")
    return secret


def load_secret_from_env(env: dict | None = None, name: str = spec.SECRET_ENV, *, public_inputs: tuple = ()) -> bytes:
    env = os.environ if env is None else env
    raw = env.get(name)
    if not raw:
        raise SecretEntropyError(f"{name} is not set: no private corpus secret is available (nothing is invented)")
    return validate_secret(_decode(raw), public_inputs=public_inputs)


def _hm(secret: bytes, domain: str, *parts) -> bytes:
    msg = "\x1f".join([domain, *[str(p) for p in parts]]).encode()
    return hmac.new(secret, msg, hashlib.sha256).digest()


def derive_item_seed(secret: bytes, category: str, split: str, index: int) -> int:
    """Per-item generator seed. Depends on the secret; index/category/split are only domain-separation inputs."""
    validate_secret(secret)
    return int.from_bytes(_hm(secret, "genesis-v2/item-seed", spec.EVAL_VERSION, category, split, index), "big")


def derive_item_id(secret: bytes, category: str, split: str, index: int) -> str:
    """Opaque, non-content-derived, non-guessable item id (HMAC output; not an index or content hash)."""
    validate_secret(secret)
    return "gce2-" + _hm(secret, "genesis-v2/item-id", spec.EVAL_VERSION, category, split, index).hex()[:24]


def derive_commit_salt(secret: bytes, item_id: str) -> bytes:
    validate_secret(secret)
    return _hm(secret, "genesis-v2/commit-salt", item_id)


def commitment(secret: bytes, item_id: str, canonical_item: str) -> str:
    """Hiding+binding commitment: SHA256(domain || salt || canonical item). Salted with a secret-derived value because a bare hash of a
    templated, low-entropy item is dictionary-attackable."""
    salt = derive_commit_salt(secret, item_id)
    return hashlib.sha256(b"genesis-v2/commitment\x1f" + salt + b"\x1f" + canonical_item.encode()).hexdigest()
