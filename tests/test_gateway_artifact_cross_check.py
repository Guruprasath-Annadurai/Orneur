"""
ModelDeployment's own lifecycle/health/warmup state is a SEPARATE system
from Phase 1's checkpoint registry (orca/registry/checkpoint.py) --
routing must refuse a deployment whose underlying artifact is registered
as MISSING/CORRUPT there, even if the deployment's own fields optimistically
say PRODUCTION/READY/warmed-up. This is exactly the real-world scenario
this project hit: orca-core-dpo's Ollama artifact was removed from local
disk in Phase 0.5 -- a deployment record referencing that same artifact_id
must not be routable regardless of what the deployment record itself claims.
"""
from __future__ import annotations

import pytest

from orca.gateway.errors import ModelNotRoutableError
from orca.gateway.gateway import ModelGateway
from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord
from tests.test_gateway_model_gateway import _FakeRuntime, _deployment, _req


@pytest.fixture
def isolated_checkpoint_dir(tmp_path, monkeypatch):
    import orca.registry.checkpoint as checkpoint_mod
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", tmp_path)
    return tmp_path


def _register_checkpoint(artifact_id: str, availability: str) -> None:
    rec = CheckpointRecord(
        checkpoint_id=artifact_id, model_id="orneur-novus", run_id="r", step_or_epoch="e",
        base_model="x", dataset_manifest_ids=[], training_config_summary="x",
        optimizer_state_available=False, scheduler_state_available=False,
        tokenizer_identity="x", artifact_path="na", artifact_checksum="na",
        availability=availability,
    )
    rec.save()


@pytest.mark.asyncio
async def test_deployment_refused_when_checkpoint_registry_says_missing(isolated_checkpoint_dir):
    """The real orca-core-dpo scenario: deployment record looks fine, but
    the checkpoint registry knows the artifact is actually gone."""
    _register_checkpoint("fake-checkpoint", ArtifactAvailability.MISSING.value)

    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())  # artifact_id="fake-checkpoint" per _deployment()'s defaults

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())
    assert runtime.calls == 0


@pytest.mark.asyncio
async def test_deployment_refused_when_checkpoint_registry_says_corrupt(isolated_checkpoint_dir):
    _register_checkpoint("fake-checkpoint", ArtifactAvailability.CORRUPT.value)

    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_deployment_routable_when_checkpoint_registry_says_local(isolated_checkpoint_dir):
    _register_checkpoint("fake-checkpoint", ArtifactAvailability.LOCAL.value)

    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())

    response = await gw.generate(_req())
    assert response.output == "hello world"


@pytest.mark.asyncio
async def test_deployment_routable_when_no_checkpoint_record_exists_at_all(isolated_checkpoint_dir):
    """Fails open: a deployment whose artifact was never registered with
    Phase 1's registry (e.g. every test double in this suite) must not be
    treated as 'missing' -- that would be a false-negative safety check,
    not a real one."""
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())  # no CheckpointRecord registered for "fake-checkpoint"

    response = await gw.generate(_req())
    assert response.output == "hello world"
