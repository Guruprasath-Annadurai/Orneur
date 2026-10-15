"""Workstream A -- authentication secret handling: secure by default, deterministic across restarts, one source of truth.

Defects reproduced on the integration candidate (cd6af2a):
  * with `ORNEUR_AUTH_SECRET` unset, session tokens were signed with a constant that is PUBLIC in this repository (anyone could forge an owner token);
    only a deployment that ALSO remembered `ORNEUR_PUBLIC_EDGE=1` was protected, and only when a token was first used (startup succeeded);
  * `orca/auth/tokens.py` froze the secret at import while `orca/auth/crypto.py` re-read it per call, with two different built-in defaults;
  * an explicit but trivially weak secret ("x") was accepted everywhere.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest

DEV_CONSTANTS = ("orneur-auth-dev-secret-CHANGE-THIS-IN-PRODUCTION", "dev-secret-change-me")
STRONG = "q7Zk2mXp9LvT4rWb8NcY1dFgHs6JtU3e"      # 32 chars, 20+ distinct


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "ornhome"
    h.mkdir(mode=0o700)
    for k in ("ORNEUR_AUTH_SECRET", "ORCA_AUTH_SECRET", "ORNEUR_PUBLIC_EDGE", "ORCA_PUBLIC_EDGE", "ORNEUR_DEPLOYMENT_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ORNEUR_HOME", str(h))
    monkeypatch.delenv("ORCA_HOME", raising=False)
    from orca.auth import secret
    secret._reset_cache_for_tests()
    return h


def _forge(secret_bytes: bytes, payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return body + "." + hmac.new(secret_bytes, body.encode(), hashlib.sha256).hexdigest()


# ── unset secret on a private install ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("const", DEV_CONSTANTS)
def test_a_token_forged_with_a_published_constant_is_rejected_on_a_default_install(home, const):
    from orca.auth.crypto import verify_token
    forged = _forge(const.encode(), {"sub": "x", "role": "owner", "type": "session", "iat": time.time(), "exp": int(time.time()) + 3600})
    assert verify_token(forged) is None


@pytest.mark.parametrize("const", DEV_CONSTANTS)
def test_reset_and_verification_tokens_cannot_be_forged_with_the_published_constants_either(home, const):
    from orca.auth import tokens
    payload = {"sub": "u", "email": "a@b.co", "type": "reset", "iat": time.time(), "exp": int(time.time()) + 3600}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    forged = body + "." + hmac.new(const.encode(), body.encode(), hashlib.sha256).hexdigest()
    assert tokens.verify_token(forged, "reset") is None


def test_the_generated_secret_is_persisted_private_and_stable_across_restarts(home):
    from orca.auth import secret
    first = secret.resolve_auth_secret()
    p = home / "auth_secret"
    assert p.is_file() and stat.S_IMODE(p.stat().st_mode) == 0o600 and len(first) >= 32
    secret._reset_cache_for_tests()                                      # a process restart
    assert secret.resolve_auth_secret() == first
    from orca.auth.crypto import create_token, verify_token
    t = create_token({"sub": "u"})
    secret._reset_cache_for_tests()
    assert verify_token(t)["sub"] == "u"                                 # a token issued before the restart still verifies


def test_two_installs_get_different_secrets(home, tmp_path, monkeypatch):
    from orca.auth import secret
    a = secret.resolve_auth_secret()
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    monkeypatch.setenv("ORNEUR_HOME", str(other))
    secret._reset_cache_for_tests()
    assert secret.resolve_auth_secret() != a


def test_concurrent_first_use_converges_on_one_secret(home):
    from orca.auth import secret
    out, errs = [], []

    def go():
        try:
            secret._reset_cache_for_tests()
            out.append(secret.resolve_auth_secret())
        except Exception as e:                                           # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=go) for _ in range(16)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs and len(set(out)) == 1 and len(out) == 16


def test_a_corrupt_or_short_secret_file_is_refused_not_silently_regenerated(home):
    from orca.auth import secret
    (home / "auth_secret").write_text("tooshort\n")
    os.chmod(home / "auth_secret", 0o600)
    secret._reset_cache_for_tests()
    with pytest.raises(secret.AuthSecretError):
        secret.resolve_auth_secret()                                     # regenerating would silently sign every user out; an operator must decide


def test_a_symlinked_secret_file_is_refused(home, tmp_path):
    from orca.auth import secret
    target = tmp_path / "elsewhere"
    target.write_text("a" * 64 + "\n")
    os.symlink(target, home / "auth_secret")
    secret._reset_cache_for_tests()
    with pytest.raises(secret.AuthSecretError):
        secret.resolve_auth_secret()


def test_a_group_readable_secret_file_is_tightened(home):
    from orca.auth import secret
    secret.resolve_auth_secret()
    os.chmod(home / "auth_secret", 0o644)
    secret._reset_cache_for_tests()
    secret.resolve_auth_secret()
    assert stat.S_IMODE((home / "auth_secret").stat().st_mode) == 0o600


# ── explicit secret ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_explicit_secret_is_used_and_nothing_is_written_to_disk(home, monkeypatch):
    from orca.auth import secret
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", STRONG)
    secret._reset_cache_for_tests()
    assert secret.resolve_auth_secret() == STRONG.encode() and not (home / "auth_secret").exists()


def test_tokens_and_crypto_use_the_same_secret_and_follow_the_environment(home, monkeypatch):
    """The module-level freeze in tokens.py meant the two token families could be signed with different secrets."""
    from orca.auth import crypto, secret, tokens
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", STRONG)
    secret._reset_cache_for_tests()
    t1 = tokens.make_reset_token("u", "a@b.co")
    c1 = crypto.create_token({"sub": "u"})
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", STRONG[::-1])                # rotated
    secret._reset_cache_for_tests()
    assert tokens.verify_token(t1, "reset") is None and crypto.verify_token(c1) is None
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", STRONG)
    secret._reset_cache_for_tests()
    assert tokens.verify_token(t1, "reset") is not None and crypto.verify_token(c1) is not None


@pytest.mark.parametrize("bad", ["x", "short-secret", "a" * 64, "abababababababababababababababab", *DEV_CONSTANTS])
def test_a_weak_or_default_explicit_secret_is_refused_in_production(home, monkeypatch, bad):
    from orca.auth import secret
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", bad)
    secret._reset_cache_for_tests()
    with pytest.raises(secret.AuthSecretError):
        secret.resolve_auth_secret()
    with pytest.raises(secret.AuthSecretError):
        secret.validate_auth_secret_config()


def test_production_never_falls_back_to_a_local_file_or_a_constant(home, monkeypatch):
    from orca.auth import secret
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    secret._reset_cache_for_tests()
    with pytest.raises(secret.AuthSecretError):
        secret.resolve_auth_secret()
    assert not (home / "auth_secret").exists()                            # a per-instance file would give each replica a different secret


def test_a_distributed_deployment_counts_as_production(home, monkeypatch):
    from orca.auth import secret
    monkeypatch.setenv("ORNEUR_DEPLOYMENT_PROFILE", "DISTRIBUTED")
    secret._reset_cache_for_tests()
    assert secret.is_production_like() is True
    with pytest.raises(secret.AuthSecretError):
        secret.resolve_auth_secret()


def test_startup_validation_reports_the_source_without_the_secret(home, monkeypatch):
    from orca.auth import secret
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", STRONG)
    secret._reset_cache_for_tests()
    summary = secret.validate_auth_secret_config()
    assert summary == {"source": "environment", "production_like": True, "bits_estimate_ok": True} and STRONG not in json.dumps(summary)
