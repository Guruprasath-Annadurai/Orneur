"""Phase 21B.4.4 SandboxBackend abstraction tests."""
from __future__ import annotations

import pytest

from orca.eval.sandbox_backend import DockerSandboxBackend, get_default_backend
from orca.eval.sandbox_contract import SandboxContract
from orca.eval.sandbox_docker import is_docker_available

requires_docker = pytest.mark.skipif(not is_docker_available(), reason="Docker is not available in this environment")


def test_default_backend_is_docker():
    backend = get_default_backend()
    assert isinstance(backend, DockerSandboxBackend)


def test_docker_backend_contract_is_a_sandbox_contract():
    backend = DockerSandboxBackend()
    contract = backend.contract()
    assert isinstance(contract, SandboxContract)
    assert contract.execution_backend == "docker"


@requires_docker
def test_docker_backend_run_executes_valid_code():
    backend = DockerSandboxBackend()
    code = "def add(a, b):\n    return a + b\n"
    result = backend.run(code, "add", (2, 3))
    assert result.ok is True
    assert result.fn_result == 5


def test_genesis_suite_score_unit_test_accepts_injected_backend():
    from orca.eval.genesis_suite import EvalTask, score_unit_test

    class _FakeResult:
        ok = True
        fn_result = 4
        error = None

    class _FakeBackend:
        def run(self, candidate_code, fn_name, args, *, timeout_seconds=None):
            return _FakeResult()

        def contract(self):
            return None

    task = EvalTask(
        task_id="fake-001", category=1, prompt="add two numbers",
        scoring_type="unit_test", deterministic=True, unit_test_fn_name="add",
        unit_test_cases=(((2, 2), 4),),
    )
    outcome = score_unit_test(task, "```python\ndef add(a, b):\n    return a + b\n```", backend=_FakeBackend())
    assert outcome["passed"] is True
    assert outcome["cases_passed"] == 1
