"""
Modal-backed implementation of the SandboxBackend contract (Phase
21B.4.6). Genesis's evaluator has never required literally `docker
run` -- it requires an independently-enforced isolation boundary
(orca.eval.sandbox_backend.SandboxBackend). This module translates
that same security contract (no host/repo/secret access, no network
unless explicitly permitted, bounded CPU/memory/time/output, an
ephemeral filesystem destroyed after execution) into Modal's Sandbox
primitives, live-verified against Modal's own current documentation
(https://modal.com/docs/reference/modal.Sandbox,
https://modal.com/docs/guide/sandbox-networking,
https://modal.com/docs/guide/sandbox-resources -- fetched 2026-09-18,
not reused from memory or from a vendor's marketing description).

Modal Sandboxes run on gVisor (Google's syscall-intercepting container
runtime), a real, independently-known isolation mechanism -- not a
Python-level guard, and not a weaker substitute for Docker's kernel
boundary. Per Modal's own docs: "Sandboxes are built to be
secure-by-default... not authorized to access other resources in your
Modal workspace the way that Modal Functions are by default."

IMPORTANT, stated per this project's own discipline (Phase 21B.4.4/
21B.4.5): the tests in tests/test_sandbox_modal.py mock the Modal API
boundary and are evidence the ADAPTER correctly REQUESTS the right
security parameters (block_network=True, hard CPU/memory limits, a
bounded timeout, no secrets, no volumes). They are NOT evidence that
Modal's live security boundary has been independently verified the
way Docker's was in Phase 21B.4.1 (live reproduction of the exact
filesystem/network/ctypes escape classes against a REAL running
sandbox). No such live adversarial re-verification has been performed
against a real Modal account as of this module's creation --
`orca.eval.sandbox_backend.get_default_backend()` still returns
`DockerSandboxBackend`, not this class, until that live verification
happens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from orca.eval.sandbox_docker import (
    MAX_OUTPUT_BYTES,
    DockerSandboxResult,
    SandboxBackendUnavailable,
    _CHILD_RUNNER_TEMPLATE,
)

MODAL_SANDBOX_CONTRACT_VERSION = "modal-v1"
MODAL_SANDBOX_IMAGE_TAG = "python:3.11-slim"

# Live-verified Phase 21B.4.7A: Modal rejects a Sandbox `timeout` outside
# [10, 86400] seconds with InvalidError("Timeout must be between 10s and
# 86400s (inclusive)."). DEFAULT_TIMEOUT_SECONDS=8.0 (+2s grace margin =
# 10, exactly the minimum) happens to be fine on its own, but any caller
# requesting a shorter timeout_seconds (e.g. 5.0, tested live) produced an
# unusable value -- another genuine bug found and fixed via live
# adversarial testing, not a hypothetical.
MODAL_MIN_TIMEOUT_SECONDS = 10
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_IDLE_TIMEOUT_SECONDS = 10
DEFAULT_CPU_LIMIT = 1.0        # fractional CPU cores, hard limit
DEFAULT_CPU_REQUEST = 0.125    # Modal's own documented minimum request per container
DEFAULT_MEMORY_LIMIT_MIB = 256
# Live-verified Phase 21B.4.7A against a real Modal Sandbox: Modal rejects
# memory requests below 128 MiB with InvalidError("Function memory request
# out of bounds. Must be between 128 and 344064 MiB."). The original 64
# MiB default was never live-tested and would have failed closed on every
# real invocation -- this is a genuine bug found and fixed via live
# adversarial testing, not a hypothetical. See tests/test_sandbox_modal.py's
# test_memory_request_never_goes_below_modal_minimum for the regression test.
DEFAULT_MEMORY_REQUEST_MIB = 128


@dataclass(frozen=True)
class ModalSandboxContract:
    """Modal's equivalent of orca.eval.sandbox_contract.SandboxContract
    -- a versioned, inspectable record of exactly which isolation
    parameters this backend requested, for persistence alongside
    results and drift detection. Deliberately a separate, smaller type
    rather than forcing Modal's parameter shape into Docker's contract
    fields, which don't map 1:1 (e.g. Modal has no equivalent of
    --cap-drop/--security-opt; gVisor's syscall interception is a
    structurally different mechanism)."""

    contract_version: str
    image_tag: str
    network_policy: str
    filesystem_policy: str
    cpu_request: float
    cpu_limit: float
    memory_request_mib: int
    memory_limit_mib: int
    timeout_seconds: float
    idle_timeout_seconds: int
    output_byte_limit: int
    secrets_injected: bool
    volumes_mounted: int
    isolation_runtime: str

    def contract_id(self) -> str:
        import hashlib

        canonical = json.dumps(
            {k: v for k, v in self.__dict__.items()}, sort_keys=True, default=str,
        )
        return f"{self.contract_version}-{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


def current_modal_contract(
    *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS, idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
    cpu_limit: float = DEFAULT_CPU_LIMIT, memory_limit_mib: int = DEFAULT_MEMORY_LIMIT_MIB,
) -> ModalSandboxContract:
    return ModalSandboxContract(
        contract_version=MODAL_SANDBOX_CONTRACT_VERSION,
        image_tag=MODAL_SANDBOX_IMAGE_TAG,
        network_policy="block_network=True (full outbound block; no incoming connections by default per Modal's secure-by-default posture)",
        filesystem_policy="no volumes, no network_file_systems mounted -- candidate code passed as an inline command argument, never written to a mounted host/repo path; container filesystem destroyed on termination",
        cpu_request=DEFAULT_CPU_REQUEST,
        cpu_limit=cpu_limit,
        memory_request_mib=DEFAULT_MEMORY_REQUEST_MIB,
        memory_limit_mib=memory_limit_mib,
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        output_byte_limit=MAX_OUTPUT_BYTES,
        secrets_injected=False,
        volumes_mounted=0,
        isolation_runtime="gVisor (Modal Sandbox default)",
    )


def is_modal_available() -> bool:
    """Best-effort LOCAL check only: is the `modal` package importable
    and does it appear to have a configured token/profile. This is NOT
    equivalent to Docker's is_docker_available(), which performs a real
    round trip (`docker info`) to the daemon -- an equivalent live
    check for Modal would require a network call to Modal's API, which
    this function deliberately avoids making as a side effect of a
    plain availability check. Callers requiring a genuine live
    guarantee must perform their own authenticated round trip."""
    try:
        import modal  # noqa: F401
        import modal.config

        return bool(getattr(modal.config, "config", {}).get("token_id"))
    except Exception:
        return False


def _build_child_script(candidate_code: str, fn_name: str, args: tuple) -> str:
    return _CHILD_RUNNER_TEMPLATE.format(candidate_code=candidate_code, fn_name=fn_name, args=args)


def run_sandboxed_modal(
    candidate_code: str,
    fn_name: str,
    args: tuple,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
    cpu_limit: float = DEFAULT_CPU_LIMIT,
    memory_limit_mib: int = DEFAULT_MEMORY_LIMIT_MIB,
    sandbox_factory: Callable[..., Any] | None = None,
) -> DockerSandboxResult:
    """Executes `candidate_code` inside a fresh, ephemeral Modal
    Sandbox translating ORNEUR's security contract into Modal's own
    parameters (see module docstring for the live-verified mapping).
    Returns the same DockerSandboxResult shape the Docker backend uses,
    so callers depending on SandboxBackend never need to distinguish
    which concrete backend produced a result.

    `sandbox_factory`, if given, replaces the real `modal.Sandbox.create`
    call -- this is the sole seam tests use to inject a fake Modal API
    without requiring the real package or an account (spec section 8).

    Raises SandboxBackendUnavailable if Modal cannot be reached/is not
    configured, or if sandbox creation/execution fails for any provider
    reason -- this backend never falls back to a weaker execution path."""
    if sandbox_factory is None and not is_modal_available():
        raise SandboxBackendUnavailable(
            "Modal is not available (the `modal` package is not installed, or no "
            "token/profile is configured) -- refusing to fall back to a weaker "
            "execution path for untrusted candidate-generated code."
        )
    if memory_limit_mib < DEFAULT_MEMORY_REQUEST_MIB:
        raise SandboxBackendUnavailable(
            f"memory_limit_mib={memory_limit_mib} is below Modal's documented minimum "
            f"request of {DEFAULT_MEMORY_REQUEST_MIB} MiB -- refusing to attempt sandbox "
            "creation with a request/limit pair Modal will reject (fail closed with a "
            "clear reason, rather than an opaque provider InvalidError)."
        )

    child_script = _build_child_script(candidate_code, fn_name, args)
    create_kwargs = dict(
        timeout=max(MODAL_MIN_TIMEOUT_SECONDS, int(timeout_seconds) + 2),
        idle_timeout=idle_timeout_seconds,
        cpu=(DEFAULT_CPU_REQUEST, float(cpu_limit)),
        memory=(DEFAULT_MEMORY_REQUEST_MIB, int(memory_limit_mib)),
        block_network=True,
        secrets=None,
        volumes={},
        network_file_systems={},
        env={},
        workdir="/tmp",
    )

    sb = None
    try:
        if sandbox_factory is not None:
            sb = sandbox_factory("python3", "-c", child_script, **create_kwargs)
        else:
            import modal

            app = modal.App.lookup("orca-genesis-eval-sandbox", create_if_missing=True)
            image = modal.Image.from_registry(MODAL_SANDBOX_IMAGE_TAG)
            sb = modal.Sandbox.create("python3", "-c", child_script, app=app, image=image, **create_kwargs)

        sb.wait()
        stdout_bytes = sb.stdout.read()
        stderr_bytes = sb.stderr.read() if hasattr(sb, "stderr") else ""
    except Exception as exc:
        raise SandboxBackendUnavailable(f"Modal sandbox execution failed: {exc!r}") from exc
    finally:
        if sb is not None:
            try:
                sb.terminate()
            except Exception:
                pass

    stdout_text = stdout_bytes if isinstance(stdout_bytes, str) else str(stdout_bytes)
    output_truncated = len(stdout_text) > MAX_OUTPUT_BYTES
    if output_truncated:
        stdout_text = stdout_text[:MAX_OUTPUT_BYTES]

    last_line = ""
    for line in stdout_text.strip().splitlines():
        if line.strip():
            last_line = line.strip()
    if not last_line:
        return DockerSandboxResult(ok=False, error="sandbox produced no parseable output", output_truncated=output_truncated)
    try:
        parsed = json.loads(last_line)
    except json.JSONDecodeError:
        return DockerSandboxResult(ok=False, error=f"sandbox output was not valid JSON: {last_line[:200]!r}", output_truncated=output_truncated)

    return DockerSandboxResult(
        ok=bool(parsed.get("ok")),
        fn_result=parsed.get("fn_result"),
        error=parsed.get("error"),
        output_truncated=output_truncated,
        stderr_tail=(stderr_bytes[-500:] if isinstance(stderr_bytes, str) else ""),
    )
