"""
Phase 15.6 -- the governed command execution adapter (spec sections
5-12, 25).

Builds on `orca/code/sandbox.py`'s precedent (subprocess isolation,
hard timeout, bounded output) rather than inventing new isolation
technology, but extends it for ORNEUR Code's needs: argv-based
execution of ARBITRARY commands (not just `python -c`), an explicit
workspace filesystem boundary with canonical-path resolution (not
string-prefix checking), an explicit environment allowlist (never
blind `os.environ` inheritance), best-effort POSIX resource limits,
real cooperative cancellation via `orca.godmode.cancellation
.CancellationSignal`, and a structured `Executor` protocol adapter so
this plugs directly into `orca.mission.operation_store` for privileged
operations rather than duplicating the operation engine.

HONEST LIMITATIONS (spec section 5: "do not claim controls the
runtime does not actually enforce"):
  - This is a subprocess-level V1 boundary, not a container/VM
    boundary. A command that can itself make raw syscalls is only
    constrained by whatever `resource.setrlimit` and workspace-path
    validation this module applies -- it is not namespace/cgroup
    isolated. Stronger isolation (network namespace denial, full
    filesystem namespace confinement) requires container execution,
    which this phase does NOT implement or claim.
  - RLIMIT_AS (address-space/memory) is set via `resource.setrlimit`
    where the platform exposes it, but is a known-unreliable control
    on macOS (the XNU kernel does not enforce RLIMIT_AS the way Linux
    does) -- see `test_resource_limits_adversarial.py` for what was
    actually observed on THIS host, not an assumed guarantee.
  - NETWORK_POLICY.DENIED is enforced by NOT setting any credentials
    or proxy config and by workspace/command review, not by kernel-
    level network namespace removal -- a command that opens raw
    sockets on this V1 path is not physically prevented from reaching
    the network on a bare subprocess. This is disclosed, not hidden.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from orca.godmode.cancellation import CancellationSignal, NoCancellation
from orca.mission.execution_plan import ExecutionPlan
from orca.mission.executor import ExecutionFailed

MAX_OUTPUT_BYTES = 64 * 1024
_POLL_INTERVAL_SECONDS = 0.05


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceEscapeError(Exception):
    """Raised when a resolved path falls outside the plan's
    workspace_root -- covers ../ traversal, an absolute path outside
    the workspace, and symlink escapes, all via canonical-path
    resolution (never string-prefix comparison)."""


def resolve_in_workspace(workspace_root: str, candidate: str) -> Path:
    """Resolves `candidate` (relative or absolute) against
    `workspace_root`, following symlinks, and raises
    WorkspaceEscapeError if the RESOLVED path is not contained in the
    RESOLVED workspace root. Containment is checked with
    `Path.relative_to()` after both sides are canonicalized via
    `os.path.realpath` -- never a naive `str.startswith()`, which a
    sibling directory sharing a name prefix (e.g. `/workspace-evil`
    vs `/workspace`) would falsely pass."""
    root = Path(os.path.realpath(workspace_root))
    target_raw = candidate if os.path.isabs(candidate) else os.path.join(str(root), candidate)
    resolved = Path(os.path.realpath(target_raw))
    try:
        resolved.relative_to(root)
    except ValueError:
        raise WorkspaceEscapeError(
            f"path {candidate!r} resolves to {resolved} outside workspace root {root}"
        ) from None
    return resolved


class ExecutionOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    #: Phase 15.6.1 -- the verified sandbox (orca.mission.container_executor)
    #: could not be reached. Fail-closed: this is a terminal, truthful
    #: outcome -- callers must NEVER interpret it as license to run the
    #: same untrusted command via this module's weaker LOCAL_SUBPROCESS
    #: path instead.
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"


class ExecutionPath(str, Enum):
    """Phase 15.6.1 -- explicit, never-hidden distinction between the
    two execution paths this package offers. Only CONTAINER_SANDBOX
    (orca.mission.container_executor) is the VERIFIED V1 execution
    path for arbitrary commands -- see REQ-SANDBOX-BOUNDARY-001 in
    PHASE15_EVIDENCE.md. LOCAL_SUBPROCESS (this module) remains a
    development-only fallback with the partial-isolation properties
    documented in this module's own docstring; it is NEVER the path a
    caller should label as "the ORNEUR Code sandbox" for anything
    that executes genuinely untrusted, arbitrary commands."""
    LOCAL_SUBPROCESS = "LOCAL_SUBPROCESS"       # DEVELOPMENT_ONLY, PARTIAL_ISOLATION, NOT_VERIFIED_SANDBOX
    CONTAINER_SANDBOX = "CONTAINER_SANDBOX"     # VERIFIED_V1_EXECUTION_PATH


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    started_at: str
    finished_at: str
    status: ExecutionOutcome
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    evidence_reference: str | None = None
    execution_path: str = ExecutionPath.LOCAL_SUBPROCESS.value

    @property
    def ok(self) -> bool:
        return self.status is ExecutionOutcome.SUCCEEDED and self.exit_code == 0


def _drain_capped(pipe, cap: int, out: list) -> None:
    """Reads from `pipe` in a background thread until EOF, keeping at
    most `cap` bytes and discarding (but still reading, to prevent a
    pipe-buffer deadlock) anything beyond that. `out` is a 2-element
    list used as an out-param: [collected_bytes, truncated_bool]."""
    collected = bytearray()
    truncated = False
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            if len(collected) < cap:
                room = cap - len(collected)
                collected.extend(chunk[:room])
                if len(chunk) > room:
                    truncated = True
            else:
                truncated = True
    finally:
        out[0] = bytes(collected)
        out[1] = truncated


def _apply_resource_limits(plan: ExecutionPlan):
    """Returns a preexec_fn (POSIX only) applying the plan's
    ResourcePolicy via resource.setrlimit in the child, best-effort --
    a limit the platform rejects is silently skipped (never crashes
    the whole exec attempt), consistent with the disclosed limitation
    that RLIMIT_AS is unreliable on macOS."""
    if os.name != "posix":
        return None

    policy = plan.resource_policy

    def _limit():
        import resource as _resource
        os.setsid()
        if policy.cpu_seconds is not None:
            try:
                _resource.setrlimit(_resource.RLIMIT_CPU, (policy.cpu_seconds, policy.cpu_seconds))
            except (ValueError, OSError):
                pass
        if policy.memory_bytes is not None and hasattr(_resource, "RLIMIT_AS"):
            try:
                _resource.setrlimit(_resource.RLIMIT_AS, (policy.memory_bytes, policy.memory_bytes))
            except (ValueError, OSError):
                pass
        if policy.max_processes is not None and hasattr(_resource, "RLIMIT_NPROC"):
            try:
                _resource.setrlimit(_resource.RLIMIT_NPROC, (policy.max_processes, policy.max_processes))
            except (ValueError, OSError):
                pass

    return _limit


def run_command(
    plan: ExecutionPlan,
    *,
    cancellation: CancellationSignal = NoCancellation(),
) -> ExecutionResult:
    """Executes `plan.command` (argv, never a shell string) with the
    plan's workspace/env/resource/timeout policy. Truthful outcome
    semantics: a killed-on-timeout process is TIMED_OUT, a cancelled
    one is CANCELLED, neither is ever reported as SUCCEEDED."""
    started_at = _now_iso()
    t0 = time.monotonic()

    try:
        cwd = resolve_in_workspace(plan.workspace_root, plan.working_directory)
    except WorkspaceEscapeError as e:
        return ExecutionResult(
            execution_id=plan.execution_id, started_at=started_at, finished_at=_now_iso(),
            status=ExecutionOutcome.FAILED, exit_code=None,
            stdout="", stderr=str(e), stdout_truncated=False, stderr_truncated=False,
        )

    env: dict[str, str] = {}
    for name in plan.environment_policy:
        if name in os.environ:
            env[name] = os.environ[name]

    preexec_fn = _apply_resource_limits(plan)

    try:
        proc = subprocess.Popen(
            list(plan.command),
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=preexec_fn,
            start_new_session=(preexec_fn is None and os.name == "posix"),
            text=False,
        )
    except (OSError, FileNotFoundError) as e:
        return ExecutionResult(
            execution_id=plan.execution_id, started_at=started_at, finished_at=_now_iso(),
            status=ExecutionOutcome.FAILED, exit_code=None,
            stdout="", stderr=f"failed to start process: {e}",
            stdout_truncated=False, stderr_truncated=False,
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
        time.sleep(_POLL_INTERVAL_SECONDS)

    exit_code_final: int | None
    if outcome in (ExecutionOutcome.CANCELLED, ExecutionOutcome.TIMED_OUT):
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        proc.wait(timeout=5)
        exit_code_final = proc.returncode
    else:
        proc.wait(timeout=5)
        exit_code_final = proc.returncode

    t_stdout.join(timeout=5)
    t_stderr.join(timeout=5)

    stdout_text = stdout_out[0].decode("utf-8", errors="replace")
    stderr_text = stderr_out[0].decode("utf-8", errors="replace")

    return ExecutionResult(
        execution_id=plan.execution_id,
        started_at=started_at,
        finished_at=_now_iso(),
        status=outcome,
        exit_code=exit_code_final,
        stdout=stdout_text,
        stderr=stderr_text,
        stdout_truncated=stdout_out[1],
        stderr_truncated=stderr_out[1],
        evidence_reference=plan.evidence_destination,
    )


def write_file_in_workspace(workspace_root: str, relative_path: str, content: bytes) -> Path:
    """The WRITE_FILES tool-level action, where THIS adapter controls
    the path (as opposed to an arbitrary subprocess argv, which it
    does not control -- see module docstring). Resolves and validates
    containment BEFORE performing any write."""
    target = resolve_in_workspace(workspace_root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def delete_file_in_workspace(workspace_root: str, relative_path: str) -> None:
    """The DELETE_FILES tool-level action -- same path-controlled
    boundary as write_file_in_workspace()."""
    target = resolve_in_workspace(workspace_root, relative_path)
    target.unlink()


@dataclass
class SandboxCommandExecutor:
    """Adapts `run_command()` to `orca.mission.executor.Executor` so a
    Code-mode execution plugs directly into
    `orca.mission.operation_store.start_and_execute_operation()` for
    privileged operations, instead of a second, parallel execution
    path. One instance wraps exactly one ExecutionPlan (mirroring
    the 1:1 operation<->plan relationship) -- the plan itself is not
    persisted into operation_store's `parameters` (only its
    fingerprint is, per spec section 7), so the executor must already
    hold the plan when constructed."""
    plan: ExecutionPlan
    cancellation: CancellationSignal = field(default_factory=NoCancellation)
    last_result: ExecutionResult | None = None

    def execute(self, *, operation_id: str, kind: str, mission_id: str | None) -> str:
        result = run_command(self.plan, cancellation=self.cancellation)
        self.last_result = result
        if result.status is not ExecutionOutcome.SUCCEEDED:
            raise ExecutionFailed(
                f"sandbox execution {result.execution_id} ended in {result.status.value} "
                f"(exit_code={result.exit_code}): {result.stderr[:500]}"
            )
        return f"sandbox-result:{result.execution_id}:exit={result.exit_code}"
