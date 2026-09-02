"""
Phase 7.1 spec §25-26: `orca.gateway.wiring.brain_for_tier_resolution()`
now persists a truthful `ModelDeployment` record to disk (once per unique
deployment_id, not on every call) so Model Society's disk-based
`list_deployments()` can actually see production deployment state --
closing the "deployment-health filtering is best-effort" gap Phase 7
disclosed. Genesis's legacy checkpoint gets the honest
`LEGACY_PRODUCTION_SERVING` lifecycle classification, never bare
`EXPERIMENTAL` (which would make Model Society reject it in production --
a real regression this test guards against directly).
"""
from __future__ import annotations

from dataclasses import dataclass

import orca.gateway.wiring as wiring_mod
from orca.gateway.deployment import list_deployments
from orca.registry.model_spec import LifecycleState
from orca.society.lifecycle import LEGACY_PRODUCTION_SERVING


@dataclass
class _FakeResolution:
    tier: str
    backend: str
    model: str
    data_left_infrastructure: bool = False


def test_genesis_deployment_gets_legacy_production_serving_not_experimental(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)
    wiring_mod.reset_for_tests()

    wiring_mod.brain_for_tier_resolution(_FakeResolution(tier="nano", backend="ollama", model="orca-nano-v7"))

    records = list_deployments(model_id="orneur-genesis")
    assert len(records) == 1
    assert records[0].lifecycle == LEGACY_PRODUCTION_SERVING
    assert records[0].lifecycle != LifecycleState.EXPERIMENTAL.value
    assert records[0].model_version == "orca-nano-v7"  # exact checkpoint, never a bare family alias


def test_novus_deployment_still_gets_real_experimental_lifecycle(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)
    wiring_mod.reset_for_tests()

    wiring_mod.brain_for_tier_resolution(_FakeResolution(tier="core", backend="ollama", model="orca-core-combined-v2"))

    records = list_deployments(model_id="orneur-novus")
    assert len(records) == 1
    assert records[0].lifecycle == LifecycleState.EXPERIMENTAL.value


def test_deployment_is_persisted_once_not_on_every_call(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)
    wiring_mod.reset_for_tests()

    resolution = _FakeResolution(tier="nano", backend="ollama", model="orca-nano-v7")
    wiring_mod.brain_for_tier_resolution(resolution)
    saved_at_first = (tmp_path / "ollama-orca-nano-v7.json").stat().st_mtime

    wiring_mod.brain_for_tier_resolution(resolution)
    wiring_mod.brain_for_tier_resolution(resolution)
    saved_at_third = (tmp_path / "ollama-orca-nano-v7.json").stat().st_mtime

    assert saved_at_first == saved_at_third  # not rewritten on repeated calls


def test_persisted_genesis_deployment_is_routable_in_production_by_society(tmp_path, monkeypatch):
    """The real regression this whole change guards against: once a disk
    record exists, Model Society's router must NOT start rejecting
    Genesis in production (allow_experimental=False) because of it."""
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)
    wiring_mod.reset_for_tests()

    wiring_mod.brain_for_tier_resolution(_FakeResolution(tier="nano", backend="ollama", model="orca-nano-v7"))

    from orca.society.contracts import CognitiveRole, RoutingRequest
    from orca.society.router import route

    decision = route(RoutingRequest(role=CognitiveRole.CONSTRUCTOR, allow_experimental=False))
    assert decision.selected_model_id == "orneur-genesis"
