"""
Container-isolated execution of untrusted, model-generated Python code
(Phase 21B.4.1). REPLACES orca.eval.sandbox's subprocess-only isolation
as the backend orca.eval.genesis_suite.score_unit_test() actually uses,
after a live re-audit this closure found the subprocess-only approach
had real, unclosed gaps:

  - DNS resolution (`socket.gethostbyname()`) succeeded despite the
    Python-level network guard -- the guard only intercepted
    `socket.socket()`/`socket.create_connection()`, not the separate C-
    extension code path `gethostbyname()` uses. A live test this
    closure resolved a real hostname to a real IP from inside the
    "sandboxed" subprocess.
  - `ctypes.CDLL(None)` succeeded, giving raw libc access -- any
    Python-level guard is fundamentally bypassable this way, since
    ctypes can call arbitrary C functions (including raw socket
    syscalls) without ever going through the `socket` module at all.
  - Filesystem access was (and remains, in orca.eval.sandbox) fully
    open: confirmed live that generated code could write to this
    project's own repository directory, the real developer's home
    directory, and read `/etc/passwd`'s real host contents.

A Python-level guard cannot close these -- they require a REAL OS-level
boundary. This module uses Docker: `--network none` (no virtual network
interface exists inside the container at all -- not a guard that can be
bypassed via ctypes, since there is nothing to call), `--read-only` root
filesystem with no repository or home-directory bind mount (the
container image is the only filesystem the code can see, plus an
ephemeral `--tmpfs /tmp` destroyed with the container), resource limits
(`--memory`, `--cpus`, `--pids-limit`), and `--cap-drop=ALL` /
`--security-opt=no-new-privileges` to remove Linux capabilities the
code has no legitimate need for.

FAIL-CLOSED CONTRACT: `is_docker_available()` must be checked by any
caller that requires the strong backend for real (non-test) candidate
scoring. `orca.eval.genesis_suite.score_unit_test()` raises
`SandboxBackendUnavailable` rather than silently falling back to the
weaker `orca.eval.sandbox.run_sandboxed()` subprocess-only
implementation if Docker is not available -- there is no unsafe
in-process fallback anywhere in this path.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass

# Pinned by tag AND verified digest at call time (see resolve_image_digest())
# -- pinning to a mutable tag alone would let the upstream image silently
# change under us between two runs claiming to use "the same" sandbox.
SANDBOX_IMAGE_TAG = "python:3.11-slim"

DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MEMORY_LIMIT = "256m"
DEFAULT_CPU_LIMIT = "1"
DEFAULT_PIDS_LIMIT = 32
MAX_OUTPUT_BYTES = 1_000_000  # 1MB cap on combined stdout+stderr


class SandboxBackendUnavailable(RuntimeError):
    """Docker is not available (not installed, daemon not running, or
    not permitted in this environment). Callers requiring the strong
    sandbox for real untrusted-code scoring MUST fail closed on this --
    never silently fall back to a weaker in-process or subprocess-only
    execution path."""


@dataclass(frozen=True)
class DockerSandboxResult:
    ok: bool
    fn_result: object = None
    error: str | None = None
    timed_out: bool = False
    output_truncated: bool = False
    stderr_tail: str = ""


_CHILD_RUNNER_TEMPLATE = r"""
import json, sys

CANDIDATE_CODE = {candidate_code!r}
FN_NAME = {fn_name!r}
ARGS = {args!r}

namespace = {{"__name__": "__sandboxed_candidate__"}}
try:
    exec(compile(CANDIDATE_CODE, "<candidate>", "exec"), namespace)
except Exception as exc:
    print(json.dumps({{"ok": False, "error": f"code failed to execute: {{exc!r}}"}}))
    sys.exit(0)

fn = namespace.get(FN_NAME)
if fn is None or not callable(fn):
    print(json.dumps({{"ok": False, "error": f"function {{FN_NAME!r}} not defined"}}))
    sys.exit(0)

try:
    result = fn(*ARGS)
    json.dumps(result)
    print(json.dumps({{"ok": True, "fn_result": result}}))
except Exception as exc:
    print(json.dumps({{"ok": False, "error": f"function raised: {{exc!r}}"}}))
"""


def is_docker_available() -> bool:
    """Real availability check -- not just 'is the CLI on PATH', but
    'can the daemon actually be reached and asked to run something'.
    Cheap (`docker info`), does not itself run a container."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def resolve_image_digest(image_tag: str = SANDBOX_IMAGE_TAG) -> str | None:
    """Resolves the CURRENT content digest the local Docker daemon has
    for `image_tag`, for recording in the sandbox security contract
    (orca.eval.sandbox_contract). Returns None if the image has never
    been pulled locally (caller should pull it before relying on this)."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_tag, "--format", "{{index .RepoDigests 0}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        digest = result.stdout.strip()
        return digest or None
    except Exception:
        return None


def run_sandboxed_docker(
    candidate_code: str,
    fn_name: str,
    args: tuple,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    image_tag: str = SANDBOX_IMAGE_TAG,
    memory_limit: str = DEFAULT_MEMORY_LIMIT,
    cpu_limit: str = DEFAULT_CPU_LIMIT,
    pids_limit: int = DEFAULT_PIDS_LIMIT,
) -> DockerSandboxResult:
    """Executes `candidate_code` inside a freshly-created, ephemeral
    Docker container with no network interface, a read-only root
    filesystem, no bind mounts of the host filesystem (the candidate
    script is piped in via stdin, never written to a mounted path), and
    hard resource limits. The container is always removed (`--rm`)
    whether the call succeeds, fails, or times out.

    Raises `SandboxBackendUnavailable` if Docker cannot be reached --
    callers requiring the strong backend must let this propagate, never
    catch it to silently fall back to a weaker execution path."""
    if not is_docker_available():
        raise SandboxBackendUnavailable(
            "Docker is not available (not installed, or the daemon is not reachable) -- "
            "the strong container sandbox cannot run. Refusing to fall back to a weaker "
            "execution path for untrusted candidate-generated code."
        )

    child_script = _CHILD_RUNNER_TEMPLATE.format(candidate_code=candidate_code, fn_name=fn_name, args=args)

    docker_cmd = [
        "docker", "run", "--rm", "-i",
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,exec,size=64m",
        "--memory", memory_limit,
        "--memory-swap", memory_limit,  # no swap beyond the memory limit
        "--cpus", cpu_limit,
        "--pids-limit", str(pids_limit),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",  # nobody:nogroup -- never root inside the container
        "-e", "HOME=/tmp",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        image_tag,
        "python3", "-I", "-S", "-",
    ]

    start = time.time()
    try:
        proc = subprocess.Popen(
            docker_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except Exception as exc:
        raise SandboxBackendUnavailable(f"Failed to launch docker: {exc!r}") from exc

    try:
        stdout, stderr = proc.communicate(input=child_script, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return DockerSandboxResult(ok=False, error=f"execution exceeded {timeout_seconds}s timeout", timed_out=True)

    output_truncated = False
    if len(stdout) + len(stderr) > MAX_OUTPUT_BYTES:
        output_truncated = True
        stdout = stdout[:MAX_OUTPUT_BYTES]

    stderr_tail = stderr[-2000:] if stderr else ""

    if proc.returncode != 0 and not stdout.strip():
        return DockerSandboxResult(
            ok=False, error=f"container exited {proc.returncode} with no output",
            stderr_tail=stderr_tail, output_truncated=output_truncated,
        )

    try:
        payload = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else None
    except (json.JSONDecodeError, IndexError):
        return DockerSandboxResult(
            ok=False, error="container produced malformed output (not valid JSON)",
            stderr_tail=stderr_tail, output_truncated=output_truncated,
        )

    if payload is None or not isinstance(payload, dict) or "ok" not in payload:
        return DockerSandboxResult(ok=False, error="container produced no structured result", stderr_tail=stderr_tail)

    if not payload["ok"]:
        return DockerSandboxResult(ok=False, error=payload.get("error", "unknown failure"), stderr_tail=stderr_tail)

    return DockerSandboxResult(ok=True, fn_result=payload.get("fn_result"), stderr_tail=stderr_tail, output_truncated=output_truncated)
