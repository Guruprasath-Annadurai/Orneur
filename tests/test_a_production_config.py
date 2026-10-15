"""Workstream A -- production configuration validation fails closed at startup."""
from __future__ import annotations

import json

import pytest

STRONG = "q7Zk2mXp9LvT4rWb8NcY1dFgHs6JtU3e"
GOOD = {
    "ORNEUR_PUBLIC_EDGE": "1", "ORNEUR_AUTH_SECRET": STRONG, "ORNEUR_ALLOWED_ORIGINS": "https://app.example.com",
    "ORNEUR_TRUSTED_HOSTS": "app.example.com", "ORNEUR_METRICS_TOKEN": "m" * 40, "ORNEUR_REDIS_URL": "redis://r:6379/0",
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in list(GOOD) + ["ORNEUR_ALLOW_UNSIGNED_WEBHOOKS", "ORNEUR_LOG_EXCEPTION_DETAIL", "ORNEUR_DEPLOYMENT_PROFILE", "ORNEUR_DATABASE_URL", "ORCA_HOME",
                          "ORCA_PUBLIC_EDGE", "ORCA_AUTH_SECRET", "ORCA_ALLOWED_ORIGINS", "ORCA_TRUSTED_HOSTS"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ORNEUR_HOME", str(tmp_path / "h"))
    from orca.auth import secret
    secret._reset_cache_for_tests()

    def apply(**over):
        for k, v in {**GOOD, **over}.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        secret._reset_cache_for_tests()
    return apply


def _codes(findings, sev=None):
    return sorted(f.code for f in findings if sev is None or f.severity == sev)


def test_a_correct_public_configuration_has_no_errors(env, isolated_home):
    from orca.serve.config_validation import validate_production_config
    env()
    assert _codes(validate_production_config(), "ERROR") == []


@pytest.mark.parametrize("over,code", [
    ({"ORNEUR_AUTH_SECRET": None}, "AUTH_SECRET"),
    ({"ORNEUR_AUTH_SECRET": "orneur-auth-dev-secret-CHANGE-THIS-IN-PRODUCTION"}, "AUTH_SECRET"),
    ({"ORNEUR_AUTH_SECRET": "short"}, "AUTH_SECRET"),
    ({"ORNEUR_ALLOWED_ORIGINS": "*"}, "ALLOWED_ORIGINS"),
    ({"ORNEUR_TRUSTED_HOSTS": None}, "TRUSTED_HOSTS"),
    ({"ORNEUR_TRUSTED_HOSTS": "*"}, "TRUSTED_HOSTS"),
    ({"ORNEUR_ALLOW_UNSIGNED_WEBHOOKS": "1"}, "UNSIGNED_WEBHOOKS"),
    ({"ORNEUR_LOG_EXCEPTION_DETAIL": "1"}, "EXCEPTION_DETAIL_LOGGING"),
])
def test_each_unsafe_public_setting_aborts_startup(env, isolated_home, over, code):
    from orca.serve.config_validation import ProductionConfigError, validate_production_config
    env(**over)
    with pytest.raises(ProductionConfigError) as e:
        validate_production_config()
    assert code in str(e.value)


def test_error_messages_never_contain_secret_values(env, isolated_home):
    from orca.serve.config_validation import ProductionConfigError, validate_production_config
    env(ORNEUR_AUTH_SECRET="weak-secret-value-1", ORNEUR_METRICS_TOKEN="t" * 10)
    # weak (too few distinct chars) so it is rejected; the secret text itself must not appear
    with pytest.raises(ProductionConfigError) as e:
        validate_production_config()
    assert "weak-secret-value" not in str(e.value)


def test_warnings_are_reported_but_do_not_abort(env, isolated_home):
    from orca.serve.config_validation import summary, validate_production_config
    env(ORNEUR_METRICS_TOKEN=None, ORNEUR_REDIS_URL=None)
    s = summary(validate_production_config())
    assert not s["errors"] and {"METRICS_TOKEN", "RATE_LIMIT_STORE", "DATABASE", "OWNER_NOT_INITIALIZED"} <= set(s["warnings"])


def test_a_private_install_is_not_blocked(env, isolated_home, monkeypatch):
    from orca.serve.config_validation import validate_production_config
    env(ORNEUR_PUBLIC_EDGE=None, ORNEUR_AUTH_SECRET=None, ORNEUR_ALLOWED_ORIGINS=None, ORNEUR_TRUSTED_HOSTS=None)
    assert _codes(validate_production_config(), "ERROR") == []


def test_importing_the_server_on_a_misconfigured_public_edge_fails_in_a_fresh_process(tmp_path):
    """End to end: the real server module must refuse to import (i.e. to start) with a forgeable configuration."""
    import os
    import subprocess
    import sys
    envp = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    envp.update({"ORNEUR_HOME": str(tmp_path / "h"), "ORNEUR_PUBLIC_EDGE": "1", "ORNEUR_ALLOWED_ORIGINS": "https://a.example.com", "ORNEUR_TRUSTED_HOSTS": "a.example.com"})
    r = subprocess.run([sys.executable, "-c", "import orca.serve.api"], env=envp, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "AUTH_SECRET" in (r.stderr + r.stdout)
    envp["ORNEUR_AUTH_SECRET"] = STRONG
    ok = subprocess.run([sys.executable, "-c", "import orca.serve.api"], env=envp, capture_output=True, text=True, timeout=120)
    assert ok.returncode == 0, ok.stderr[-400:]
