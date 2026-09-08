"""
Phase 15.6.1 -- SANDBOX CLOSURE: a genuinely isolated container
execution path for arbitrary commands, closing the gap Phase 15.6's
own evidence disclosed (REQ-SANDBOX-BOUNDARY-001 left IMPLEMENTED,
not VERIFIED, because the subprocess-only V1 path did not physically
confine filesystem or network access).

This module does NOT invent new isolation technology. It shells out
to the `docker` CLI already present in this repository's own CI
(`.github/workflows/test.yml` already builds and runs a Docker image
as its production-parity smoke test) and on this development host
(confirmed via `docker version`/`docker info` before writing any
code), using ONLY long-established Docker/OCI runtime primitives:

  - `--network none`   -- a real network NAMESPACE with no interfaces
                           but loopback. Empirically confirmed (see
                           PHASE15_EVIDENCE.md's Phase 15.6.1 section)
                           to produce `OSError: Network is unreachable`
                           for an outbound connection attempt -- a
                           kernel-level denial, not an application-
                           level choice that merely never happens to
                           try.
  - a single bind mount -- ONLY the plan's `workspace_root` is mounted
                           into the container at `/workspace`; nothing
                           else from the host filesystem is visible.
                           Empirically confirmed: `/Users` (this host's
                           entire home-directory tree) does not exist
                           inside the container at all -- not merely
                           permission-denied, genuinely absent.
  - `--read-only` root filesystem + a size-capped `--tmpfs /tmp`
                           -- a command can write to the workspace or
                           to its own `/tmp` scratch space and nowhere
                           else on the container's own root filesystem.
                           Empirically confirmed:
                           `OSError: Read-only file system`.
  - `--user <uid>:<gid>` (non-root)
                           -- confirmed unable to read `/etc/shadow`
                           inside the container (`PermissionError`).
  - `--pids-limit`, `--memory` (+ `--memory-swap` pinned equal, so
    swap cannot be used to bypass the limit), `--cpus`
                           -- real cgroup-enforced resource limits.
                           Empirically confirmed: exceeding
                           `--pids-limit` raises `BlockingIOError:
                           Resource temporarily unavailable` inside
                           the container (the fork itself fails, the
                           HOST's own process table is untouched --
                           unlike the RLIMIT_NPROC bug disclosed in
                           Phase 15.6's own evidence); exceeding
                           `--memory` results in the container being
                           OOM-killed (exit code 137), a real
                           mechanism distinct from macOS's disclosed-
                           unreliable RLIMIT_AS.

FAIL-CLOSED (spec section 8): if the Docker daemon is unreachable,
`run_in_container()` returns `ExecutionOutcome.SANDBOX_UNAVAILABLE`
and NEVER falls back to running the untrusted command directly on the
host via `orca.mission.sandbox_executor` -- that fallback would
silently re-expose exactly the gap this closure exists to fix. See
`is_docker_available()` and `test_container_adversarial.py::
TestFailClosed`.

WHAT REMAINS A DISCLOSED LIMITATION even on this path (not claimed as
solved): the container image itself (`python:3.11-slim` by default)
is a shared, generic runtime -- it is not rebuilt per mission, and a
command that can exploit an unpatched container-escape vulnerability
in the Docker/kernel stack itself is outside this module's threat
model (same as any container-based CI system). NetworkPolicy.ALLOWED
uses Docker's default bridge network with NO additional egress
filtering -- "ALLOWED" is unrestricted, not selectively permitted;
NetworkPolicy.RESTRICTED is NOT implemented and stays UNVERIFIED
(spec section 4's explicit instruction: do not pretend hostname
review equals kernel enforcement).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from orca.godmode.cancellation import CancellationSignal, NoCancellation
from orca.mission.execution_plan import ExecutionPlan, NetworkPolicy
from orca.mission.executor import ExecutionFailed
from orca.mission.sandbox_executor import (
    MAX_OUTPUT_BYTES,
    ExecutionOutcome,
    ExecutionPath,
    ExecutionResult,
    _drain_capped,
)

DEFAULT_IMAGE = "python:3.11-slim"
_CONTAINER_UID_GID = "1000:1000"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_docker_available() -> bool:
    """Real availability check -- never assumed. Used to implement
    fail-closed behavior (spec section 8): if this returns False,
    `run_in_container()` must return SANDBOX_UNAVAILABLE, never
    silently execute the untrusted command anywhere else."""
    docker_path = shutil.which("docker")
    if docker_path is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _docker_run_command(plan: ExecutionPlan, container_name: str, *, image: str) -> list[str]:
    resource_policy = plan.resource_policy
    cmd = [
        "docker", "run", "--rm", "--name", container_name,
        "--network", "none" if plan.network_policy == NetworkPolicy.DENIED else "bridge",
        "-v", f"{os.path.realpath(plan.workspace_root)}:/workspace",
        "-w", "/workspace",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
        "--user", _CONTAINER_UID_GID,
    ]
    if resource_policy.max_processes is not None:
        cmd += ["--pids-limit", str(resource_policy.max_processes)]
    if resource_policy.memory_bytes is not None:
        mem = f"{resource_policy.memory_bytes}b"
        cmd += ["--memory", mem, "--memory-swap", mem]  # swap pinned equal -- no swap escape hatch
    cmd += ["--cpus", "1"]

    for name in plan.environment_policy:
        if name in os.environ:
            cmd += ["-e", f"{name}={os.environ[name]}"]

    cmd += [image, *plan.command]
    return cmd


def run_in_container(
    plan: ExecutionPlan,
    *,
    cancellation: CancellationSignal = NoCancellation(),
    image: str = DEFAULT_IMAGE,
) -> ExecutionResult:
    """The VERIFIED V1 execution path for arbitrary commands. Fails
    closed (SANDBOX_UNAVAILABLE) if Docker is unreachable -- never
    falls back to `orca.mission.sandbox_executor.run_command()`."""
    started_at = _now_iso()
    t0 = time.monotonic()

    if not is_docker_available():
        return ExecutionResult(
            execution_id=plan.execution_id, started_at=started_at, finished_at=_now_iso(),
            status=ExecutionOutcome.SANDBOX_UNAVAILABLE, exit_code=None,
            stdout="", stderr="Docker daemon is unavailable -- refusing to execute untrusted "
                              "command outside the verified container sandbox (fail-closed).",
            stdout_truncated=False, stderr_truncated=False,
            execution_path=ExecutionPath.CONTAINER_SANDBOX.value,
        )

    container_name = f"orneur-sbx-{uuid.uuid4().hex[:12]}"
    docker_cmd = _docker_run_command(plan, container_name, image=image)

    try:
        proc = subprocess.Popen(docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
    except (OSError, FileNotFoundError) as e:
        return ExecutionResult(
            execution_id=plan.execution_id, started_at=started_at, finished_at=_now_iso(),
            status=ExecutionOutcome.FAILED, exit_code=None,
            stdout="", stderr=f"failed to start container: {e}",
            stdout_truncated=False, stderr_truncated=False,
            execution_path=ExecutionPath.CONTAINER_SANDBOX.value,
        )

    stdout_out: list = [b"", False]
    stderr_out: list = [b"", False]
    t_stdout = threading.Thread(target=_drain_capped, args=(proc.stdout, MAX_OUTPUT_BYTES, stdout_out), daemon=True)
    t_stderr = threading.Thread(target=_drain_capped, args=(proc.stderr, MAX_OUTPUT_BYTES, stderr_out), daemon=True)
    t_stdout.start()
    t_stderr.start()

    outcome: ExecutionOutcome | None = None
    while True:
        exit_code = proc.poll()
        if exit_code is not None:
            outcome = ExecutionOutcome.SUCCEEDED if exit_code == 0 else ExecutionOutcome.FAILED
            break
        if cancellation.is_cancelled():
            outcome = ExecutionOutcome.CANCELLED
            break
        if time.monotonic() - t0 > plan.timeout_seconds:
            outcome = ExecutionOutcome.TIMED_OUT
            break
        time.sleep(0.05)

    if outcome in (ExecutionOutcome.CANCELLED, ExecutionOutcome.TIMED_OUT):
        subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10)

    proc.wait(timeout=15)
    t_stdout.join(timeout=15)
    t_stderr.join(timeout=15)

    return ExecutionResult(
        execution_id=plan.execution_id,
        started_at=started_at,
        finished_at=_now_iso(),
        status=outcome,
        exit_code=proc.returncode,
        stdout=stdout_out[0].decode("utf-8", errors="replace"),
        stderr=stderr_out[0].decode("utf-8", errors="replace"),
        stdout_truncated=stdout_out[1],
        stderr_truncated=stderr_out[1],
        evidence_reference=plan.evidence_destination,
        execution_path=ExecutionPath.CONTAINER_SANDBOX.value,
    )


@dataclass
class ContainerCommandExecutor:
    """The VERIFIED-path Executor adapter -- same `Executor` protocol
    integration as `orca.mission.sandbox_executor.SandboxCommandExecutor`,
    so Code execution still plugs into `orca.mission.operation_store`
    unmodified. Sandboxing here is orthogonal to authorization: this
    class performs NO authority decision of its own -- it is only ever
    invoked (via `orca.mission.operation_store.start_and_execute_
    operation`) after `authorize_operation()` has already produced a
    real ALLOW from `orca.godmode`."""
    plan: ExecutionPlan
    cancellation: CancellationSignal = field(default_factory=NoCancellation)
    image: str = DEFAULT_IMAGE
    last_result: ExecutionResult | None = None

    def execute(self, *, operation_id: str, kind: str, mission_id: str | None) -> str:
        result = run_in_container(self.plan, cancellation=self.cancellation, image=self.image)
        self.last_result = result
        if result.status is not ExecutionOutcome.SUCCEEDED:
            raise ExecutionFailed(
                f"container execution {result.execution_id} ended in {result.status.value} "
                f"(exit_code={result.exit_code}): {result.stderr[:500]}"
            )
        return f"container-result:{result.execution_id}:exit={result.exit_code}"
