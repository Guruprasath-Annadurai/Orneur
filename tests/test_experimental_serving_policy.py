"""
P0: an unpromoted (EXPERIMENTAL) self-hosted model must not silently reach the public.

Before: orca/gateway/wiring.py passed allow_experimental=True for every live request on every deployment, so whatever Ollama model happened to be
installed under a tier name -- including the NOT_PROMOTABLE Novus checkpoint -- was served, public or not.
Now: local/private deployments behave exactly as before; on a public edge (ORNEUR_PUBLIC_EDGE) an EXPERIMENTAL self-hosted model is refused by
the gateway. An environment flag (ORNEUR_ALLOW_EXPERIMENTAL_SERVING) is NOT evidence and no longer authorizes anything -- only a signed, scoped,
expiring public-serving grant does (tests/test_public_serving_authority.py). Frontier backends are unaffected.
"""
from __future__ import annotations

import json
import logging
import urllib.request

import pytest
from fastapi.testclient import TestClient

from orca.gateway import wiring
from orca.gateway.errors import ModelNotRoutableError
from orca.serve import api as api_module
from orca.serve.registry import TierResolution

NOVUS = TierResolution(tier="core", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)
GENESIS = TierResolution(tier="nano", backend="ollama", model="orca-nano-v7", data_left_infrastructure=False)
FRONTIER = TierResolution(tier="core", backend="openai", model="gpt-4o", data_left_infrastructure=True)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    for var in ("PUBLIC_EDGE", "ALLOW_EXPERIMENTAL_SERVING"):
        monkeypatch.delenv(f"ORNEUR_{var}", raising=False)
        monkeypatch.delenv(f"ORCA_{var}", raising=False)
    wiring.reset_for_tests()
    yield
    wiring.reset_for_tests()


def _resolve(brain):
    return brain._gateway.resolve_deployment(brain.model_id, brain.model_version, brain.allow_experimental)


def test_local_deployment_behaviour_is_unchanged():
    brain = wiring.brain_for_tier_resolution(NOVUS)
    assert brain.allow_experimental is True
    assert _resolve(brain).model_version == "orca-core-combined-v2"
    assert wiring.serving_policy()["public_edge"] is False


def test_public_edge_refuses_an_experimental_self_hosted_model(monkeypatch):
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    brain = wiring.brain_for_tier_resolution(NOVUS)
    assert brain.allow_experimental is False
    with pytest.raises(ModelNotRoutableError):
        _resolve(brain)
    pol = wiring.serving_policy()
    assert pol["public_edge"] is True and pol["experimental_self_hosted_models_served"] is False


def test_the_acknowledgement_flag_no_longer_authorizes_and_is_reported_as_ineffective(monkeypatch):
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "true")
    monkeypatch.setenv("ORNEUR_ALLOW_EXPERIMENTAL_SERVING", "yes")
    brain = wiring.brain_for_tier_resolution(NOVUS)
    assert brain.allow_experimental is False
    with pytest.raises(ModelNotRoutableError):
        _resolve(brain)
    pol = wiring.serving_policy()
    assert pol["operator_acknowledged_experimental_serving"] is True and pol["experimental_flag_has_authorizing_effect"] is False


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "enabled", "2", "1", "true", "yes"])
def test_no_value_of_the_flag_authorizes_the_public_edge(monkeypatch, value):
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    monkeypatch.setenv("ORNEUR_ALLOW_EXPERIMENTAL_SERVING", value)
    assert wiring.experimental_self_hosted_allowed() is False


def test_acknowledgement_alone_changes_nothing_off_the_public_edge(monkeypatch):
    monkeypatch.setenv("ORNEUR_ALLOW_EXPERIMENTAL_SERVING", "1")
    assert wiring.experimental_self_hosted_allowed() is True      # local dev stays allowed either way
    assert wiring.public_edge_enabled() is False


def test_frontier_backends_are_not_affected(monkeypatch):
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    brain = wiring.brain_for_tier_resolution(FRONTIER)
    assert brain.allow_experimental is True and _resolve(brain)


def test_legacy_genesis_remains_routable_on_the_public_edge_as_a_disclosed_decision(monkeypatch):
    """NOT changed here: the retired Qwen-7B Genesis artifact serves the nano tier as LEGACY_PRODUCTION_SERVING (Phase 7.1 decision). This test
    pins that fact so it cannot change silently; whether it should keep serving the public is a founder decision (see the PR description)."""
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    brain = wiring.brain_for_tier_resolution(GENESIS)
    assert _resolve(brain).lifecycle == "LEGACY_PRODUCTION_SERVING"


def test_api_models_reports_the_serving_policy(monkeypatch):
    class _Resp:
        def read(self):
            return json.dumps({"models": [{"name": "orca-core"}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=3: _Resp())
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    body = TestClient(api_module.app).get("/api/models").json()
    assert body["serving_policy"]["public_edge"] is True
    assert body["serving_policy"]["experimental_self_hosted_models_served"] is False
    assert {"nano", "core", "ultra", "persona_claims"} <= set(body)      # additive: existing keys intact
