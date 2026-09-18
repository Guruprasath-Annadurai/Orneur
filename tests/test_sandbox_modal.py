"""
Phase 21B.4.6 ModalSandboxBackend tests -- entirely mocked at the
`modal.Sandbox.create` boundary via the `sandbox_factory` injection
seam. These prove the ADAPTER correctly requests ORNEUR's security
contract (network blocked, CPU/memory hard limits, bounded timeout, no
secrets, no volumes) in Modal's own parameter names. They are NOT
evidence that Modal's live security boundary has been independently
verified -- no real Modal account or package is required or used
anywhere in this file.
"""
from __future__ import annotations

import json

import pytest

from orca.eval.sandbox_backend import ModalSandboxBackend
from orca.eval.sandbox_docker import SandboxBackendUnavailable
from orca.eval.sandbox_modal import (
    DEFAULT_CPU_LIMIT,
    DEFAULT_CPU_REQUEST,
    DEFAULT_MEMORY_LIMIT_MIB,
    DEFAULT_MEMORY_REQUEST_MIB,
    current_modal_contract,
    run_sandboxed_modal,
)


class _FakeSandbox:
    def __init__(self, stdout_text: str, stderr_text: str = ""):
        self._stdout_text = stdout_text
        self._stderr_text = stderr_text
        self.terminated = False

    def wait(self):
        return 0

    @property
    def stdout(self):
        class _R:
            def read(_self):
                return self._stdout_text

        return _R()

    @property
    def stderr(self):
        class _R:
            def read(_self):
                return self._stderr_text

        return _R()

    def terminate(self):
        self.terminated = True


def _ok_factory(fn_result=5):
    captured = {}
    payload = json.dumps({"ok": True, "fn_result": fn_result})
    sb = _FakeSandbox(stdout_text=payload)

    def factory(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["sandbox"] = sb
        return sb

    return factory, captured


# ── security contract is correctly requested ────────────────────────


def test_run_requests_full_network_block():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def add(a,b):\n return a+b", "add", (2, 3), sandbox_factory=factory)
    assert captured["kwargs"]["block_network"] is True


def test_run_requests_hard_cpu_limit():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory, cpu_limit=2.0)
    assert captured["kwargs"]["cpu"] == (DEFAULT_CPU_REQUEST, 2.0)


def test_run_requests_hard_memory_limit():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory, memory_limit_mib=512)
    assert captured["kwargs"]["memory"] == (DEFAULT_MEMORY_REQUEST_MIB, 512)


def test_memory_request_never_goes_below_modal_minimum():
    # Live-verified Phase 21B.4.7A: Modal rejects memory requests below
    # 128 MiB with InvalidError("Function memory request out of bounds.
    # Must be between 128 and 344064 MiB."). The default MUST be >= 128,
    # and a caller passing a limit below that must fail closed with a
    # clear ORNEUR-level error, not an opaque provider exception.
    assert DEFAULT_MEMORY_REQUEST_MIB >= 128
    with pytest.raises(SandboxBackendUnavailable):
        run_sandboxed_modal("def f():\n return 1", "f", (), memory_limit_mib=64, sandbox_factory=lambda *a, **k: None)


def test_run_requests_bounded_timeout_and_idle_timeout():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory, timeout_seconds=20.0)
    assert captured["kwargs"]["timeout"] == 22  # +2s grace margin, above Modal's 10s minimum
    assert captured["kwargs"]["idle_timeout"] == pytest.approx(10, abs=0)


def test_timeout_never_goes_below_modal_minimum():
    # Live-verified Phase 21B.4.7A: Modal rejects a Sandbox `timeout`
    # below 10 seconds with InvalidError("Timeout must be between 10s
    # and 86400s (inclusive)."). A caller requesting a short
    # timeout_seconds (e.g. 5.0, the exact value that failed live) must
    # still produce a valid, clamped `timeout` kwarg, not an unusable one.
    from orca.eval.sandbox_modal import MODAL_MIN_TIMEOUT_SECONDS

    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory, timeout_seconds=5.0)
    assert captured["kwargs"]["timeout"] == MODAL_MIN_TIMEOUT_SECONDS
    assert captured["kwargs"]["timeout"] >= MODAL_MIN_TIMEOUT_SECONDS


def test_run_injects_no_secrets():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert captured["kwargs"]["secrets"] is None


def test_run_mounts_no_volumes_or_network_filesystems():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert captured["kwargs"]["volumes"] == {}
    assert captured["kwargs"]["network_file_systems"] == {}


def test_run_passes_no_ambient_environment_variables():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert captured["kwargs"]["env"] == {}


# ── lifecycle: termination is guaranteed ────────────────────────────


def test_sandbox_terminated_after_success():
    factory, captured = _ok_factory()
    run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert captured["sandbox"].terminated is True


def test_sandbox_terminated_after_provider_exception():
    def factory(*args, **kwargs):
        raise RuntimeError("provider blew up")

    with pytest.raises(SandboxBackendUnavailable):
        run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)


def test_sandbox_terminated_even_if_wait_raises():
    sb = _FakeSandbox(stdout_text="")
    sb.wait = lambda: (_ for _ in ()).throw(RuntimeError("timed out"))

    def factory(*args, **kwargs):
        return sb

    with pytest.raises(SandboxBackendUnavailable):
        run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert sb.terminated is True


# ── result parsing fails closed ──────────────────────────────────────


def test_malformed_output_fails_closed_not_raises():
    sb = _FakeSandbox(stdout_text="not json at all")
    factory = lambda *a, **k: sb
    result = run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert result.ok is False
    assert "not valid JSON" in result.error


def test_empty_output_fails_closed_not_raises():
    sb = _FakeSandbox(stdout_text="")
    factory = lambda *a, **k: sb
    result = run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert result.ok is False
    assert "no parseable output" in result.error


def test_successful_result_is_parsed_correctly():
    factory, captured = _ok_factory(fn_result=42)
    result = run_sandboxed_modal("def f():\n return 42", "f", (), sandbox_factory=factory)
    assert result.ok is True
    assert result.fn_result == 42


def test_output_over_limit_is_truncated_and_flagged():
    huge_payload = json.dumps({"ok": True, "fn_result": "x" * 10}) + "\n" + "x" * (1_000_001)
    sb = _FakeSandbox(stdout_text=huge_payload)
    factory = lambda *a, **k: sb
    result = run_sandboxed_modal("def f():\n return 1", "f", (), sandbox_factory=factory)
    assert result.output_truncated is True


def test_provider_error_without_factory_and_no_modal_installed_fails_closed(monkeypatch):
    # Explicitly controls is_modal_available() rather than relying on the
    # ambient environment -- a dev machine that happens to have `modal`
    # installed and authenticated (e.g. for live Phase 21B.4.7A testing)
    # must not make this test pass for the wrong reason.
    monkeypatch.setattr("orca.eval.sandbox_modal.is_modal_available", lambda: False)
    with pytest.raises(SandboxBackendUnavailable):
        run_sandboxed_modal("def f():\n return 1", "f", ())


# ── ModalSandboxBackend (SandboxBackend protocol) ───────────────────


def test_modal_backend_run_delegates_to_run_sandboxed_modal(monkeypatch):
    from orca.eval.sandbox_docker import DockerSandboxResult

    calls = {}

    def fake_run_sandboxed_modal(candidate_code, fn_name, args, **kwargs):
        calls["args"] = (candidate_code, fn_name, args)
        return DockerSandboxResult(ok=True, fn_result=7)

    monkeypatch.setattr("orca.eval.sandbox_modal.run_sandboxed_modal", fake_run_sandboxed_modal)
    backend = ModalSandboxBackend()
    result = backend.run("def f():\n return 7", "f", ())
    assert result.ok is True
    assert result.fn_result == 7
    assert calls["args"] == ("def f():\n return 7", "f", ())


def test_modal_backend_contract_is_not_a_docker_contract():
    backend = ModalSandboxBackend()
    with pytest.raises(NotImplementedError):
        backend.contract()


# ── versioned contract record ────────────────────────────────────────


def test_current_modal_contract_has_required_fields():
    contract = current_modal_contract()
    assert contract.contract_version == "modal-v1"
    assert contract.secrets_injected is False
    assert contract.volumes_mounted == 0
    assert "gVisor" in contract.isolation_runtime


def test_modal_contract_id_is_deterministic():
    c1 = current_modal_contract()
    c2 = current_modal_contract()
    assert c1.contract_id() == c2.contract_id()


def test_modal_contract_id_changes_with_resource_limits():
    c1 = current_modal_contract(cpu_limit=1.0)
    c2 = current_modal_contract(cpu_limit=2.0)
    assert c1.contract_id() != c2.contract_id()
