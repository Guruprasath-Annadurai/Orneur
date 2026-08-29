"""
Model alias resolution (orneur-novus:production / :candidate /
:experimental) must never let an unversioned bare alias bypass promotion
governance by silently falling through to a candidate/experimental
deployment -- naming a specific alias suffix IS the explicit policy
decision; a bare model_id is not.
"""
from __future__ import annotations

import pytest

from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.gateway.errors import ModelNotRoutableError
from orca.gateway.gateway import ModelGateway
from orca.registry.model_spec import LifecycleState
from tests.test_gateway_model_gateway import _FakeRuntime, _deployment, _req


@pytest.mark.asyncio
async def test_bare_alias_never_falls_back_to_candidate():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(deployment_id="d-candidate", lifecycle=LifecycleState.CANDIDATE.value))

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req(model_id="orneur-novus"))  # bare, no explicit policy


@pytest.mark.asyncio
async def test_explicit_candidate_alias_reaches_candidate_deployment():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(deployment_id="d-candidate", lifecycle=LifecycleState.CANDIDATE.value))

    response = await gw.generate(_req(model_id="orneur-novus:candidate"))
    assert response.output == "hello world"


@pytest.mark.asyncio
async def test_production_alias_prefers_production_over_candidate():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(deployment_id="d-candidate", lifecycle=LifecycleState.CANDIDATE.value))
    gw.register_deployment(_deployment(deployment_id="d-prod", lifecycle=LifecycleState.PRODUCTION.value))

    response = await gw.generate(_req(model_id="orneur-novus:production"))
    assert response.deployment_id == "d-prod"


@pytest.mark.asyncio
async def test_unknown_alias_suffix_rejected():
    gw = ModelGateway()
    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req(model_id="orneur-novus:nonsense"))


@pytest.mark.asyncio
async def test_experimental_alias_reaches_experimental_deployment_without_policy_flag():
    """Naming the alias explicitly is itself the policy decision -- no
    separate allow_experimental=True needed once ':experimental' is named."""
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(deployment_id="d-exp", lifecycle=LifecycleState.EXPERIMENTAL.value))

    response = await gw.generate(_req(model_id="orneur-novus:experimental"), allow_experimental=False)
    assert response.output == "hello world"
