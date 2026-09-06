"""
Tests for orca/serve/routing.py — cost-aware per-query escalation (see
docs/DEVELOPMENT_PHASES.md Phase 3). Real properties under test:

  - escalation NEVER fires unless the operator explicitly opted in
    (cost_aware_escalation_enabled), even if a frontier API key is present
  - the data-sovereignty lock always wins, regardless of the opt-in flag
  - a tier already resolved to a non-Ollama backend is never touched
  - only queries classified as time-sensitive or long+complex escalate
    when escalation is otherwise available
"""
from __future__ import annotations

import pytest

from orca.serve.registry import TierResolution
from orca.serve import routing
from orca.serve.routing import classify_query, decide_route, escalation_available, reset_daily_cap_counter


@pytest.fixture(autouse=True)
def _clear_daily_cap_counter():
    reset_daily_cap_counter()
    yield
    reset_daily_cap_counter()


def _ollama_resolution(tier="core"):
    return TierResolution(tier=tier, backend="ollama", model="orca-core", data_left_infrastructure=False)


def _frontier_resolution(tier="core", backend="openai"):
    return TierResolution(tier=tier, backend=backend, model="gpt-4o", data_left_infrastructure=True)


# ── classify_query ──────────────────────────────────────────────────────────

def test_classify_query_detects_time_sensitive_language():
    c = classify_query("What's the latest news on the stock price today?")
    assert c.is_time_sensitive is True
    assert c.suggests_escalation is True


def test_classify_query_short_simple_query_does_not_suggest_escalation():
    c = classify_query("What is 2+2?")
    assert c.is_time_sensitive is False
    assert c.suggests_escalation is False


def test_classify_query_long_complex_query_suggests_escalation():
    msg = (
        "Compare and analyze the trade-offs between microservices and a monolith "
        "architecture in depth, considering deployment complexity, team ownership "
        "boundaries, operational overhead, and long-term maintainability step by step."
    )
    c = classify_query(msg)
    assert c.is_complex is True
    assert c.word_count > 25
    assert c.suggests_escalation is True


def test_classify_query_short_complex_language_does_not_escalate_alone():
    # "compare" alone on a short query shouldn't be enough — needs length too.
    c = classify_query("compare apples and oranges")
    assert c.is_complex is True
    assert c.suggests_escalation is False


# ── escalation_available (config gating) ────────────────────────────────────

def test_escalation_unavailable_when_not_opted_in(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", False)
    available, reason = escalation_available()
    assert available is False
    assert "not enabled" in reason


def test_escalation_unavailable_when_sovereignty_locked(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", True)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "sk-fake")
    available, reason = escalation_available()
    assert available is False
    assert "sovereignty lock" in reason


def test_escalation_unavailable_without_api_key(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", False)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "")
    available, reason = escalation_available()
    assert available is False
    assert "no API key" in reason


def test_escalation_available_when_fully_configured(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", False)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "sk-fake")
    available, reason = escalation_available()
    assert available is True


# ── decide_route ─────────────────────────────────────────────────────────────

def test_decide_route_never_escalates_when_not_opted_in(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", False)
    base = _ollama_resolution()
    resolution, decision = decide_route(base, "What's the latest breaking news today?")
    assert decision.escalated is False
    assert resolution is base


def test_decide_route_escalates_when_available_and_query_qualifies(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", False)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "sk-fake")
    monkeypatch.setattr(CONFIG.backends, "openai_model_core", "gpt-4o")

    base = _ollama_resolution(tier="core")
    resolution, decision = decide_route(base, "What's the latest breaking news today?")

    assert decision.escalated is True
    assert resolution.backend == "openai"
    assert resolution.data_left_infrastructure is True


def test_decide_route_stays_self_hosted_for_simple_query_even_when_available(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", False)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "sk-fake")

    base = _ollama_resolution()
    resolution, decision = decide_route(base, "What is 2+2?")

    assert decision.escalated is False
    assert resolution is base


def test_decide_route_never_touches_an_already_frontier_resolution(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", False)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "anthropic")
    monkeypatch.setattr(CONFIG.backends, "anthropic_api_key", "sk-fake")

    base = _frontier_resolution(backend="openai")
    resolution, decision = decide_route(base, "What's the latest breaking news today?")

    assert decision.escalated is False
    assert resolution is base


def test_decide_route_respects_sovereignty_lock_even_if_query_qualifies(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", True)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "sk-fake")

    base = _ollama_resolution()
    resolution, decision = decide_route(base, "What's the latest breaking news today?")

    assert decision.escalated is False
    assert resolution is base


# ── daily escalation cap (safety valve even when opted in) ──────────────────

def test_decide_route_stops_escalating_once_daily_cap_is_reached(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", False)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "sk-fake")
    monkeypatch.setattr(CONFIG.backends, "escalation_daily_cap", 2)

    base = _ollama_resolution()
    query = "What's the latest breaking news today?"

    _, d1 = decide_route(base, query)
    _, d2 = decide_route(base, query)
    _, d3 = decide_route(base, query)

    assert d1.escalated is True
    assert d2.escalated is True
    assert d3.escalated is False
    assert "daily cap" in d3.reason


def test_decide_route_uses_conservative_default_cap_when_unset(monkeypatch):
    CONFIG = routing.CONFIG
    monkeypatch.setattr(CONFIG.backends, "cost_aware_escalation_enabled", True)
    monkeypatch.setattr(CONFIG.backends, "data_sovereignty_lock", False)
    monkeypatch.setattr(CONFIG.backends, "escalation_backend", "openai")
    monkeypatch.setattr(CONFIG.backends, "openai_api_key", "sk-fake")
    monkeypatch.setattr(CONFIG.backends, "escalation_daily_cap", 0)  # "not set"

    base = _ollama_resolution()
    _, decision = decide_route(base, "What's the latest breaking news today?")

    # Should still escalate (well under the default cap) — 0 must not mean
    # "unlimited", but it also must not mean "zero allowed."
    assert decision.escalated is True
