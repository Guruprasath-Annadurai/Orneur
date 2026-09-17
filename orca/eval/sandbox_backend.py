"""
Phase 21B.4.4 (spec sections 6-7) -- SandboxBackend: the security
CONTRACT untrusted, model-generated code must run inside, independent
of any specific mechanism. The real requirement Genesis evaluation has
never been "must call the `docker` binary" -- it is "untrusted code
must execute inside an independently enforced isolation boundary" that
provably closes filesystem/network/process/environment escape, exactly
as Phase 21B.4.1 empirically verified for `docker run`. This module
makes that boundary swappable without weakening it: `genesis_suite.py`
depends on `SandboxBackend`, not on the literal Docker CLI.

`DockerSandboxBackend` is the only implementation in this codebase
today, wrapping the exact, already-verified `orca.eval.sandbox_docker`
module -- no behavior changes, no security regression. A future
backend (a remote-VM worker, a provider-managed container isolation
service, a microVM) may be added later, but ONLY after its own
isolation properties are verified the same way Phase 21B.4.1 verified
Docker's -- live reproduction of the exact attack classes (filesystem
escape, network escape, ctypes/raw-libc escape, process/resource
exhaustion), never assumed from a vendor's marketing description. No
such backend has been added or verified this phase; this module exists
so one CAN be, without touching `genesis_suite.py` again when it is.
"""
from __future__ import annotations

from typing import Any, Protocol

from orca.eval.sandbox_contract import SandboxContract, current_docker_contract
from orca.eval.sandbox_docker import (
    DockerSandboxResult,
    SandboxBackendUnavailable,
    run_sandboxed_docker,
)


class SandboxBackend(Protocol):
    """The security contract every backend must satisfy (spec section
    7): no host filesystem/repository/secret access, no network unless
    explicitly permitted, CPU/memory/PID/timeout/output limits, an
    ephemeral filesystem destroyed after execution, a versioned,
    inspectable contract, and an auditable result. A backend that
    cannot make all of these true should raise SandboxBackendUnavailable
    rather than silently running with a weaker guarantee."""

    def run(self, candidate_code: str, fn_name: str, args: tuple, *, timeout_seconds: float | None = None) -> DockerSandboxResult:
        """Execute `fn_name(*args)` from `candidate_code` inside the
        isolation boundary and return a structured result. Must raise
        SandboxBackendUnavailable (never silently degrade) if the
        boundary cannot be established."""
        ...

    def contract(self) -> SandboxContract:
        """Return this backend's current, live-resolved isolation
        contract (see orca.eval.sandbox_contract.SandboxContract) --
        callers persist this alongside results for reproducibility and
        drift detection."""
        ...


class DockerSandboxBackend:
    """The only SandboxBackend implementation verified in this
    codebase -- a thin wrapper over orca.eval.sandbox_docker, which
    Phase 21B.4.1 empirically confirmed closes the filesystem, network,
    and raw-libc escape classes that the earlier subprocess-only
    sandbox did not."""

    def run(self, candidate_code: str, fn_name: str, args: tuple, *, timeout_seconds: float | None = None) -> DockerSandboxResult:
        kwargs: dict[str, Any] = {}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        return run_sandboxed_docker(candidate_code, fn_name, args, **kwargs)

    def contract(self) -> SandboxContract:
        return current_docker_contract()


def get_default_backend() -> SandboxBackend:
    """The backend genesis_suite.py uses when none is explicitly
    injected -- Docker today. Changing this default to a different
    verified backend is the intended extension point; nothing else in
    the evaluation pipeline should need to change."""
    return DockerSandboxBackend()


__all__ = [
    "SandboxBackend",
    "DockerSandboxBackend",
    "SandboxBackendUnavailable",
    "get_default_backend",
]
