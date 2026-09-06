"""
Tests for GET /api/models — specifically the resolved_model/fallback_active
fields added on top of the raw availability check.

Covers the real gap this fixes: the endpoint used to report only whether the
CONFIGURED model name was installed, not what actually gets served once the
registry's step-down fallback applies — so an unconfigured/not-yet-trained
ultra tier looked like a hard failure here even when requests to it were
silently (and correctly) falling back to core.
"""
from __future__ import annotations

import json
import urllib.request
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orca.serve import api as api_module


@pytest.fixture
def client():
    return TestClient(api_module.app)


def _mock_ollama_tags(monkeypatch, installed_models: list[str]):
    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=3):
        return _FakeResponse({"models": [{"name": m} for m in installed_models]})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)


def test_reports_no_fallback_when_all_tiers_installed(client, monkeypatch):
    monkeypatch.setattr(api_module.CONFIG.ollama, "model_nano", "orca-nano")
    monkeypatch.setattr(api_module.CONFIG.ollama, "model_core", "orca-core")
    monkeypatch.setattr(api_module.CONFIG.ollama, "model_ultra", "orca-ultra")
    _mock_ollama_tags(monkeypatch, ["orca-nano:latest", "orca-core:latest", "orca-ultra:latest"])
    monkeypatch.setattr(
        api_module, "resolve_tier_model",
        lambda tier, host=None: {"nano": "orca-nano", "core": "orca-core", "ultra": "orca-ultra"}[tier],
    )

    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()

    for tier in ("nano", "core", "ultra"):
        assert data[tier]["available"] is True
        assert data[tier]["fallback_active"] is False
        assert data[tier]["resolved_model"] == data[tier]["model"]


def test_reports_fallback_active_when_ultra_not_installed(client, monkeypatch):
    monkeypatch.setattr(api_module.CONFIG.ollama, "model_nano", "orca-nano")
    monkeypatch.setattr(api_module.CONFIG.ollama, "model_core", "orca-core")
    monkeypatch.setattr(api_module.CONFIG.ollama, "model_ultra", "orca-ultra")
    _mock_ollama_tags(monkeypatch, ["orca-nano:latest", "orca-core:latest"])

    def _fake_resolve(tier, host=None):
        if tier == "ultra":
            return "orca-core"  # stepped down
        return {"nano": "orca-nano", "core": "orca-core"}[tier]

    monkeypatch.setattr(api_module, "resolve_tier_model", _fake_resolve)

    resp = client.get("/api/models")
    data = resp.json()

    assert data["ultra"]["available"] is False
    assert data["ultra"]["resolved_model"] == "orca-core"
    assert data["ultra"]["fallback_active"] is True
    assert data["core"]["fallback_active"] is False


def test_reports_resolved_model_none_when_nothing_available(client, monkeypatch):
    monkeypatch.setattr(api_module.CONFIG.ollama, "model_nano", "orca-nano")
    _mock_ollama_tags(monkeypatch, [])

    def _fake_resolve(tier, host=None):
        raise RuntimeError("nothing installed")

    monkeypatch.setattr(api_module, "resolve_tier_model", _fake_resolve)

    resp = client.get("/api/models")
    data = resp.json()

    assert data["nano"]["resolved_model"] is None
    assert data["nano"]["fallback_active"] is False


def test_persona_claims_surfaced_per_tier(client, monkeypatch):
    """
    The actual gap this closes: orca/personas.py's runtime persona-demotion
    gate had no externally-visible signal on GET /api/models — a client had
    no way to know a tier's self-description is currently demoted without
    reading raw eval/redteam JSON off disk. This is the one place a real
    buyer or an admin UI actually looks.
    """
    _mock_ollama_tags(monkeypatch, [])
    monkeypatch.setattr(api_module, "resolve_tier_model", lambda tier, host=None: None)
    monkeypatch.setattr(api_module, "resolve_tier_backend", lambda tier, host=None: MagicMock(
        backend="ollama", model="orca-nano", data_left_infrastructure=False, sovereignty_overridden=False,
    ))

    def _fake_gate(tier):
        return {"nano": (False, "jailbreak block rate 0.0% is below the 90.0% required"),
                "core": (False, "accuracy 66% is below the 70% required"),
                "ultra": (False, "No accuracy eval on record")}[tier]

    monkeypatch.setattr(api_module, "check_persona_claim_allowed", _fake_gate)

    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()

    assert "persona_claims" in data
    for tier in ("nano", "core", "ultra"):
        assert data["persona_claims"][tier]["approved"] is False
        assert isinstance(data["persona_claims"][tier]["reason"], str) and data["persona_claims"][tier]["reason"]


def test_persona_claims_reports_approved_when_gate_clears(client, monkeypatch):
    _mock_ollama_tags(monkeypatch, [])
    monkeypatch.setattr(api_module, "resolve_tier_model", lambda tier, host=None: None)
    monkeypatch.setattr(api_module, "resolve_tier_backend", lambda tier, host=None: MagicMock(
        backend="ollama", model="orca-nano", data_left_infrastructure=False, sovereignty_overridden=False,
    ))
    monkeypatch.setattr(api_module, "check_persona_claim_allowed", lambda tier: (True, "both thresholds cleared"))

    resp = client.get("/api/models")
    data = resp.json()

    assert data["persona_claims"]["nano"]["approved"] is True
    assert data["persona_claims"]["core"]["approved"] is True
