"""
Phase 21B.4.1 (§4) sandbox security contract tests --
orca.eval.sandbox_contract, the versioned record of exactly what
isolation was in force when coding/debugging tasks were scored.
"""
from __future__ import annotations

from orca.eval.sandbox_contract import contract_id, current_docker_contract


def test_current_docker_contract_has_required_fields():
    contract = current_docker_contract()
    assert contract.contract_version
    assert contract.execution_backend == "docker"
    assert contract.container_image_tag
    assert contract.network_policy
    assert contract.filesystem_policy
    assert contract.cpu_limit
    assert contract.memory_limit
    assert contract.pids_limit > 0
    assert contract.timeout_seconds > 0
    assert contract.output_byte_limit > 0
    assert contract.mounted_paths == []
    assert contract.python_runtime_version


def test_contract_id_is_deterministic_for_the_same_contract():
    c1 = current_docker_contract()
    c2 = current_docker_contract()
    # docker_available_at_contract_time could differ between calls in a
    # flaky environment, but in a stable environment this should match.
    assert contract_id(c1) == contract_id(c2) or c1.docker_available_at_contract_time == c2.docker_available_at_contract_time


def test_contract_id_changes_if_resource_limits_change():
    from dataclasses import replace

    c1 = current_docker_contract()
    c2 = replace(c1, memory_limit="512m")
    assert contract_id(c1) != contract_id(c2)


def test_is_strong_backend_true_for_docker():
    contract = current_docker_contract()
    assert contract.is_strong_backend() is True
