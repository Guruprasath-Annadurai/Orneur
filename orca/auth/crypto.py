"""Password hashing + stateless token signing — zero external deps."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from orca.config import orneur_env


# ── Password hashing (PBKDF2-SHA256) ─────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:260000:{salt}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, iters, salt, dk_hex = stored.split(":")
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ── Token signing (HMAC-SHA256, no PyJWT dep) ────────────────────────────────

_DEV_SECRETS = frozenset({"orneur-auth-dev-secret-CHANGE-THIS-IN-PRODUCTION", "dev-secret-change-me"})


def assert_secret_usable(value: str) -> None:
    """G-006: the development defaults are public constants in this
    repository, so a deployment that forgot ``ORNEUR_AUTH_SECRET`` would sign
    -- and accept -- tokens anybody can forge (including an owner's). On a
    public edge (``ORNEUR_PUBLIC_EDGE``) refuse to sign or verify at all;
    local/private development keeps working with the default."""
    if value in _DEV_SECRETS and orneur_env("PUBLIC_EDGE", "").strip().lower() in ("1", "true", "yes"):
        raise RuntimeError(
            "ORNEUR_AUTH_SECRET is unset (or a development default) while ORNEUR_PUBLIC_EDGE is enabled; "
            "refusing to sign or verify session tokens"
        )


def _secret() -> bytes:
    value = orneur_env("AUTH_SECRET", "orneur-auth-dev-secret-CHANGE-THIS-IN-PRODUCTION")
    assert_secret_usable(value)
    return value.encode()


def create_token(payload: dict, expires_in: int = 86_400 * 30) -> str:
    now = time.time()
    p = {**payload, "iat": now, "exp": int(now) + expires_in}
    data = (
        base64.urlsafe_b64encode(json.dumps(p, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    sig = hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_token(token: str) -> dict | None:
    try:
        data, sig = token.rsplit(".", 1)
        expected = hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padding = (4 - len(data) % 4) % 4
        payload = json.loads(base64.urlsafe_b64decode(data + "=" * padding))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None
