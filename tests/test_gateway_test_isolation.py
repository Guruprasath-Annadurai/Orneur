"""
Regression test for the Phase 7.1 finding (spec §29-30): a
`tests/test_gateway_*.py` test must never write into the developer's real
`~/.orca/registry/deployments/`. The autouse `_isolate_gateway_registry_dirs`
fixture in `tests/conftest.py` is the fix -- this test proves it actually
takes effect for the exact call chain that leaked
(`ModelDeployment.request_drain()` -> `.save()`).
"""
from __future__ import annotations

from pathlib import Path

import orca.gateway.deployment as deployment_mod
from orca.gateway.deployment import ModelDeployment
from orca.registry.model_spec import LifecycleState


def test_deployment_dir_is_isolated_for_this_module(tmp_path):
    """The autouse fixture (tests/conftest.py, scoped to test_gateway*
    modules) must have repointed DEPLOYMENT_DIR to THIS test's own
    tmp_path before the test body runs -- proving it is not the real
    ~/.orca directory."""
    assert deployment_mod.DEPLOYMENT_DIR == tmp_path
    assert Path.home() / ".orca" not in deployment_mod.DEPLOYMENT_DIR.parents


def test_request_drain_never_writes_to_real_home(tmp_path):
    dep = ModelDeployment(
        deployment_id="isolation-check", model_id="orneur-genesis", model_version="v",
        artifact_id="v", runtime="fake", runtime_endpoint="fake://local", hardware_profile="test",
        lifecycle=LifecycleState.EXPERIMENTAL.value, warmup_completed=True,
    )
    dep.request_drain()  # calls .save() -- must land under this test's isolated tmp_path
    written = deployment_mod.DEPLOYMENT_DIR / "isolation-check.json"
    assert written.exists()
    assert written.is_relative_to(tmp_path)
    assert not written.is_relative_to(Path.home() / ".orca")
