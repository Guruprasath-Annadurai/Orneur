"""
Tests for orca/serve/registry.py's tier -> concrete-model resolution.

Covers the real bug this module fixes: OrcaBrain._resolve_model() only
falls back to a best-available open model when no model name is requested,
but the serving path always resolves a concrete name first — so a
misconfigured or not-yet-fine-tuned tier (e.g. ultra, before Aeternum
exists) previously hard-crashed instead of degrading gracefully.
"""
from __future__ import annotations

import pytest

from orca.serve import registry


@pytest.fixture(autouse=True)
def _reset_tags_cache():
    """Every test controls _list_installed_models directly — clear the
    module-level cache so one test's monkeypatch can't leak into another."""
    registry._tags_cache = None
    yield
    registry._tags_cache = None


def _configured(monkeypatch, nano="orca-nano", core="orca-core", ultra="orca-ultra"):
    from orca.config import CONFIG
    monkeypatch.setattr(CONFIG.ollama, "model_nano", nano)
    monkeypatch.setattr(CONFIG.ollama, "model_core", core)
    monkeypatch.setattr(CONFIG.ollama, "model_ultra", ultra)


def test_resolves_to_configured_model_when_installed(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-core:latest"])
    assert registry.resolve_tier_model("core") == "orca-core"


def test_ultra_falls_back_to_core_when_ultra_not_installed(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-core:latest"])
    calls = []
    result = registry.resolve_tier_model("ultra", on_fallback=lambda t, r, c: calls.append((t, r, c)))
    assert result == "orca-core"
    assert calls == [("ultra", "orca-ultra", "orca-core")]


def test_ultra_falls_back_to_nano_when_core_also_missing(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-nano:latest"])
    result = registry.resolve_tier_model("ultra")
    assert result == "orca-nano"


def test_nano_has_no_fallback_and_raises_if_missing(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: [])
    with pytest.raises(RuntimeError, match="No installed Ollama model found for tier 'nano'"):
        registry.resolve_tier_model("nano")


def test_core_never_falls_back_up_to_ultra(monkeypatch):
    # Only ultra is installed — core has no configured step-up path, so this
    # must raise rather than silently serving the (differently-tiered) ultra
    # model to a core request.
    _configured(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-ultra:latest"])
    with pytest.raises(RuntimeError):
        registry.resolve_tier_model("core")


def test_orca_prefixed_variant_name_normalizes(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-nano:latest"])
    assert registry.resolve_tier_model("orca-nano") == "orca-nano"


def test_none_variant_defaults_to_core(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(registry, "_list_installed_models", lambda host: ["orca-core:latest"])
    assert registry.resolve_tier_model(None) == "orca-core"


def test_tags_cache_avoids_repeated_calls(monkeypatch):
    _configured(monkeypatch)
    call_count = {"n": 0}

    def _fake_list(host):
        call_count["n"] += 1
        return ["orca-core:latest"]

    monkeypatch.setattr(registry, "_list_installed_models", _fake_list)
    # _list_installed_models itself isn't cached in this monkeypatch (we
    # replaced the whole function) — this test instead verifies the real
    # caching helper behaves correctly by calling it through the real
    # implementation path in a separate, more targeted test below.
    registry.resolve_tier_model("core")
    registry.resolve_tier_model("core")
    assert call_count["n"] == 2  # each resolve_tier_model call invokes it once; caching lives inside the real fn


def test_list_installed_models_caches_within_ttl(monkeypatch):
    calls = {"n": 0}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "orca-core:latest"}]}

    def _fake_get(url, timeout=5):
        calls["n"] += 1
        return _FakeResponse()

    monkeypatch.setattr(registry.httpx, "get", _fake_get)

    first = registry._list_installed_models("http://localhost:11434")
    second = registry._list_installed_models("http://localhost:11434")

    assert first == second == ["orca-core:latest"]
    assert calls["n"] == 1  # second call served from cache, no new HTTP request


def test_list_installed_models_returns_empty_on_connection_failure(monkeypatch):
    def _fake_get(url, timeout=5):
        raise ConnectionError("ollama not running")

    monkeypatch.setattr(registry.httpx, "get", _fake_get)
    assert registry._list_installed_models("http://localhost:11434") == []
