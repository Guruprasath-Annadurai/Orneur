"""
Tests for orca/serve/registry.py's resolve_tier_backend() — the enforcement
point for Orca's "bring your own frontier model" design (see
docs/STARTUP_PLAN.md §2, orca/brain/backends.py).

Covers the real, code-enforced property this exists for: when
CONFIG.backends.data_sovereignty_lock is set, NO tier can ever resolve to
a non-Ollama backend, regardless of what's configured — a locked
deployment's "your data never leaves your infrastructure" promise is an
enforced fact here, not documentation.
"""
from __future__ import annotations

import pytest

from orca.serve import registry


@pytest.fixture(autouse=True)
def _reset_tags_cache():
    registry._tags_cache = None
    yield
    registry._tags_cache = None


def _configure(monkeypatch, **overrides):
    # Patch the CONFIG object registry.py actually holds a reference to
    # (`registry.CONFIG`), not a fresh `from orca.config import CONFIG` —
    # another test file's `isolated_home` fixture (tests/conftest.py) does
    # `importlib.reload(config)`, which rebinds `orca.config.CONFIG` to a
    # NEW object. registry.py imported CONFIG by reference at its own
    # import time and never sees that reload, so a fresh import here would
    # silently mutate a different, disconnected object whenever this test
    # runs after any test using that fixture — a real cross-test-file
    # isolation gap, not a hypothetical one (this exact test suite failed
    # only when run as part of the full suite, never in isolation).
    CONFIG = registry.CONFIG
    defaults = dict(
        model_nano="orca-nano", model_core="orca-core", model_ultra="orca-ultra",
        backend_nano="ollama", backend_core="ollama", backend_ultra="ollama",
        openai_model_core="gpt-4o", openai_model_ultra="gpt-4o",
        anthropic_model_core="claude-sonnet-4-6", anthropic_model_ultra="claude-opus-4-8",
        openai_api_key="", anthropic_api_key="",
        data_sovereignty_lock=False,
    )
    defaults.update(overrides)
    for key in ("model_nano", "model_core", "model_ultra"):
        monkeypatch.setattr(CONFIG.ollama, key, defaults[key])
    for key in (
        "backend_nano", "backend_core", "backend_ultra",
        "openai_model_core", "openai_model_ultra",
        "anthropic_model_core", "anthropic_model_ultra",
        "openai_api_key", "anthropic_api_key", "data_sovereignty_lock",
    ):
        monkeypatch.setattr(CONFIG.backends, key, defaults[key])


def test_resolves_ollama_when_configured_and_installed(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-core:latest"])

    result = registry.resolve_tier_backend("core")

    assert result.backend == "ollama"
    assert result.model == "orca-core"
    assert result.data_left_infrastructure is False
    assert result.sovereignty_overridden is False


def test_resolves_openai_when_configured_and_api_key_present(monkeypatch):
    _configure(monkeypatch, backend_ultra="openai", openai_api_key="sk-fake")
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: [])

    result = registry.resolve_tier_backend("ultra")

    assert result.backend == "openai"
    assert result.model == "gpt-4o"
    assert result.data_left_infrastructure is True


def test_resolves_anthropic_when_configured_and_api_key_present(monkeypatch):
    _configure(monkeypatch, backend_ultra="anthropic", anthropic_api_key="sk-ant-fake")
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: [])

    result = registry.resolve_tier_backend("ultra")

    assert result.backend == "anthropic"
    assert result.model == "claude-opus-4-8"
    assert result.data_left_infrastructure is True


class TestDataSovereigntyLock:
    def test_lock_forces_ollama_even_when_frontier_configured(self, monkeypatch):
        _configure(
            monkeypatch, backend_ultra="anthropic", anthropic_api_key="sk-ant-fake",
            data_sovereignty_lock=True,
        )
        monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-ultra:latest"])

        result = registry.resolve_tier_backend("ultra")

        assert result.backend == "ollama"
        assert result.data_left_infrastructure is False
        assert result.sovereignty_overridden is True

    def test_lock_override_callback_fires(self, monkeypatch):
        _configure(
            monkeypatch, backend_core="openai", openai_api_key="sk-fake",
            data_sovereignty_lock=True,
        )
        monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-core:latest"])

        calls = []
        registry.resolve_tier_backend(
            "core", on_sovereignty_override=lambda tier, backend: calls.append((tier, backend))
        )
        assert calls == [("core", "openai")]

    def test_lock_never_returns_a_frontier_backend_across_full_fallback_chain(self, monkeypatch):
        """Even when stepping down through ultra->core->nano, the lock must
        hold at every step — this is the real guarantee, not just the
        first check."""
        _configure(
            monkeypatch,
            backend_ultra="anthropic", backend_core="openai", backend_nano="ollama",
            anthropic_api_key="sk-ant-fake", openai_api_key="sk-fake",
            data_sovereignty_lock=True,
        )
        # Only nano's ollama model is installed — ultra and core steps must
        # each be force-checked as ollama-only (and fail, since their ollama
        # models aren't installed) before falling all the way to nano.
        monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-nano:latest"])

        result = registry.resolve_tier_backend("ultra")

        assert result.backend == "ollama"
        assert result.model == "orca-nano"
        assert result.data_left_infrastructure is False

    def test_lock_with_no_ollama_model_anywhere_raises_rather_than_leaking_to_frontier(self, monkeypatch):
        _configure(
            monkeypatch, backend_ultra="anthropic", anthropic_api_key="sk-ant-fake",
            data_sovereignty_lock=True,
        )
        monkeypatch.setattr(registry, "_list_installed_models", lambda host: [])

        with pytest.raises(RuntimeError, match="sovereignty lock"):
            registry.resolve_tier_backend("ultra")


def test_frontier_unavailable_falls_back_through_chain_to_ollama(monkeypatch):
    """ultra configured for openai but no API key set -> should NOT silently
    error, should step down through core/nano to find a working ollama model."""
    _configure(monkeypatch, backend_ultra="openai", openai_api_key="")
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-nano:latest"])

    result = registry.resolve_tier_backend("ultra")

    assert result.backend == "ollama"
    assert result.model == "orca-nano"


def test_fallback_callback_fires_with_backend_qualified_model_name(monkeypatch):
    # ultra wants openai but has no key -> steps down to core, which IS
    # configured for openai and DOES have a key -> should resolve there,
    # firing on_fallback with a "backend:model" qualified resolved-name.
    _configure(
        monkeypatch, backend_ultra="openai", openai_api_key="sk-fake",
        backend_core="openai",
    )
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: [])

    # Simulate ultra's key being unset by temporarily giving it no key via a
    # per-tier override isn't supported by config (one shared key) — instead
    # exercise the ollama-unavailable-for-ultra-then-available-for-core path
    # using distinct backends so the step-down is real and observable.
    monkeypatch.setattr(registry.CONFIG.backends, "backend_ultra", "anthropic")
    monkeypatch.setattr(registry.CONFIG.backends, "anthropic_api_key", "")  # ultra's backend unavailable

    calls = []
    result = registry.resolve_tier_backend(
        "ultra", on_fallback=lambda tier, requested, resolved: calls.append((tier, requested, resolved))
    )

    assert result.backend == "openai"
    assert result.model == "gpt-4o"
    assert len(calls) == 1
    assert calls[0][0] == "ultra"
    assert calls[0][2] == "openai:gpt-4o"


def test_raises_when_nothing_in_the_whole_chain_works(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: [])

    with pytest.raises(RuntimeError, match="No usable backend found"):
        registry.resolve_tier_backend("ultra")


def test_orca_prefixed_tier_name_normalizes(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-nano:latest"])

    result = registry.resolve_tier_backend("orca-nano")
    assert result.backend == "ollama"
    assert result.model == "orca-nano"
