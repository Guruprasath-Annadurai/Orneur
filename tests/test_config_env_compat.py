"""
ORCA_* -> ORNEUR_* environment variable compatibility (Phase 1, migration
stage D). ORNEUR_* must take precedence; legacy ORCA_* is a deprecated
fallback that must warn, never silently mask ORNEUR_*, and never appear
without a warning when it's the only one set.
"""
from __future__ import annotations

import warnings

from orca.config import orneur_env


def test_orneur_var_takes_precedence_over_legacy(monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", "/canonical/path")
    monkeypatch.setenv("ORCA_HOME", "/legacy/path")
    assert orneur_env("HOME") == "/canonical/path"


def test_legacy_var_is_accepted_as_fallback(monkeypatch):
    monkeypatch.delenv("ORNEUR_HOME", raising=False)
    monkeypatch.setenv("ORCA_HOME", "/legacy/path")
    assert orneur_env("HOME") == "/legacy/path"


def test_legacy_var_fallback_emits_deprecation_warning(monkeypatch):
    monkeypatch.delenv("ORNEUR_HOME", raising=False)
    monkeypatch.setenv("ORCA_HOME", "/legacy/path")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        orneur_env("HOME")
    assert any(issubclass(x.category, DeprecationWarning) for x in w)
    assert any("ORCA_HOME" in str(x.message) and "ORNEUR_HOME" in str(x.message) for x in w)


def test_canonical_var_alone_emits_no_deprecation_warning(monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", "/canonical/path")
    monkeypatch.delenv("ORCA_HOME", raising=False)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        orneur_env("HOME")
    assert not any(issubclass(x.category, DeprecationWarning) for x in w)


def test_default_used_when_neither_var_set(monkeypatch):
    monkeypatch.delenv("ORNEUR_HOME", raising=False)
    monkeypatch.delenv("ORCA_HOME", raising=False)
    assert orneur_env("HOME", default="/default/path") == "/default/path"


def test_deprecation_warning_never_includes_the_resolved_value(monkeypatch):
    """
    Regression guard for the secret-leakage requirement: several ORCA_* vars
    carry secrets (ORCA_AUTH_SECRET, ORCA_OPENAI_API_KEY, etc.) -- the
    warning message must reference variable NAMES only, never the value.
    """
    monkeypatch.delenv("ORNEUR_SECRET", raising=False)
    secret_value = "sk-super-secret-token-do-not-log-me"
    monkeypatch.setenv("ORCA_SECRET", secret_value)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = orneur_env("SECRET")
    assert result == secret_value  # the function must still return it correctly
    assert not any(secret_value in str(x.message) for x in w)  # but never log it
