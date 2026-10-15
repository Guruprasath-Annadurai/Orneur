"""The one place the authentication signing secret is resolved.

Policy (Workstream A):
  * ``ORNEUR_AUTH_SECRET`` set          -> that value, validated. In a production-like deployment it must be >= 32 characters, have enough distinct
                                          characters, and not be one of the development constants that are public in this repository.
  * unset, NOT production-like          -> a random 256-bit secret generated once and persisted to ``$ORNEUR_HOME/auth_secret`` (mode 0600, created
                                          atomically, symlinks and foreign owners refused). Unique per install, stable across restarts. The old behaviour
                                          (a constant published in the source) let anyone forge an owner token on a default install.
  * unset, production-like              -> refuse. A per-instance file would give each replica a different secret; a constant is forgeable.
"Production-like" = ``ORNEUR_PUBLIC_EDGE`` is set, or the deployment profile is DISTRIBUTED.

A corrupt/short secret file is an error, never silently regenerated: regenerating would sign every user out without the operator knowing.
"""
from __future__ import annotations

import os
import secrets as _secrets
import stat
import threading
from pathlib import Path

from orca.config import orneur_env

DEV_SECRETS = frozenset({"orneur-auth-dev-secret-CHANGE-THIS-IN-PRODUCTION", "dev-secret-change-me"})
MIN_PRODUCTION_LENGTH = 32
MIN_DISTINCT_CHARS = 12
_FILE_NAME = "auth_secret"
_FILE_HEX_LEN = 64


class AuthSecretError(RuntimeError):
    """Raised when no acceptable authentication secret is available. Never contains the secret."""


_lock = threading.Lock()
_cache: dict = {}


def _reset_cache_for_tests() -> None:
    with _lock:
        _cache.clear()


def _home() -> Path:
    return Path(orneur_env("HOME", str(Path.home() / ".orca"))).expanduser()


def is_production_like() -> bool:
    if orneur_env("PUBLIC_EDGE", "").strip().lower() in ("1", "true", "yes"):
        return True
    try:
        from orca.godmode.deployment_profile import get_profile

        return get_profile() == "DISTRIBUTED"
    except Exception:
        return False


def _strong_enough(value: str) -> bool:
    return value not in DEV_SECRETS and len(value) >= MIN_PRODUCTION_LENGTH and len(set(value)) >= MIN_DISTINCT_CHARS


def _read_secret_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as e:
        raise AuthSecretError(f"auth secret file {path.name} cannot be opened safely (symlink or permission problem)") from e
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise AuthSecretError("auth secret file is not a regular file")
        if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
            raise AuthSecretError("auth secret file is owned by another user")
        if stat.S_IMODE(st.st_mode) & 0o077:
            os.fchmod(fd, 0o600)                                     # tighten; we own it
        raw = os.read(fd, 4096).decode("ascii", "ignore").strip()
    finally:
        os.close(fd)
    if len(raw) < _FILE_HEX_LEN or any(c not in "0123456789abcdef" for c in raw):
        raise AuthSecretError("auth secret file is corrupt or too short; refusing to regenerate silently (that would sign every user out)")
    return raw.encode()


def _load_or_create_file_secret() -> bytes:
    home = _home()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = home / _FILE_NAME
    if os.path.lexists(final):
        return _read_secret_file(final)
    tmp = home / f".{_FILE_NAME}.{os.getpid()}.{_secrets.token_hex(4)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (_secrets.token_hex(_FILE_HEX_LEN // 2) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(tmp, final)                                          # atomic publish; fails if a concurrent starter won
    except FileExistsError:
        pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return _read_secret_file(final)


def resolve_auth_secret() -> bytes:
    explicit = orneur_env("AUTH_SECRET", "")
    prod = is_production_like()
    key = (explicit, str(_home()), prod)
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            return hit
        if explicit:
            if prod and not _strong_enough(explicit):
                raise AuthSecretError(
                    "ORNEUR_AUTH_SECRET is weak or a development constant in a production-like deployment "
                    f"(need >= {MIN_PRODUCTION_LENGTH} characters, >= {MIN_DISTINCT_CHARS} distinct, not a published default)"
                )
            if not prod and explicit in DEV_SECRETS:
                raise AuthSecretError("ORNEUR_AUTH_SECRET is set to a development constant that is public in this repository")
            value = explicit.encode()
        elif prod:
            raise AuthSecretError("ORNEUR_AUTH_SECRET must be set explicitly in a production-like deployment (no local fallback)")
        else:
            value = _load_or_create_file_secret()
        _cache.clear()
        _cache[key] = value
        return value


def validate_auth_secret_config() -> dict:
    """Startup check. Raises AuthSecretError; returns a secret-free summary."""
    value = resolve_auth_secret()
    explicit = bool(orneur_env("AUTH_SECRET", ""))
    return {"source": "environment" if explicit else "install_file", "production_like": is_production_like(), "bits_estimate_ok": len(value) >= MIN_PRODUCTION_LENGTH}
