"""Hermetic coding-evaluation sandbox contract for Genesis Capability Eval V2 (extends the hardened `orca.eval.sandbox_docker` primitive).

This phase RUNS NO MODEL-GENERATED CODE: the tests execute hostile fixture programs written by the test suite to prove containment.

Architecture (one fresh container per item, destroyed afterwards):
  * network: none (no interface but loopback inside the container's own namespace) -> no egress, no host localhost, no cloud-metadata route
  * filesystem: read-only root; writable ephemeral tmpfs at /work and /tmp only (size-capped, noexec/nosuid/nodev); the ONLY host path visible is a
    freshly staged job directory mounted READ-ONLY at /job. No repository, home, corpus, credentials or Docker socket is ever mounted
  * privileges: uid 65534, all capabilities dropped, no-new-privileges, default seccomp, private PID/IPC/UTS namespaces, no --privileged
  * resources: --memory (no swap), --cpus, --pids-limit, ulimits (nofile, nproc, fsize, cpu, core=0), host-side wall-clock kill of the NAMED container,
    streamed output cap with kill on excess
  * environment: nothing is inherited; only an explicit allow-list is passed (PATH, HOME=/tmp, LANG/LC_ALL=C.UTF-8, TZ=UTC, PYTHONHASHSEED=0, ...)
  * execution never pulls an image (--pull never); qualification mode requires the image to be referenced by digest
  * a structured, content-free ExecutionRecord (digests only) is returned for every run
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping

from orca.eval.sandbox_docker import is_docker_available

POLICY_VERSION = "genesis-v2-coding-sandbox-policy/1"
LABEL = "orneur.genesis.v2.sandbox=1"
SUPPORTED_RUNTIMES = {"python3.11": "python:3.11-slim"}
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_PATH_LEN = 64, 1 << 20, 2 << 20, 200


class SandboxUnavailable(RuntimeError):
    """Docker cannot be reached or the required image is absent. Never falls back to a weaker executor."""


class SandboxPolicyViolation(ValueError):
    """A job or policy violates the hermetic contract (path traversal, symlink, oversize, unpinned image in qualification mode, ...)."""


@dataclass(frozen=True)
class SandboxPolicy:
    image: str = SUPPORTED_RUNTIMES["python3.11"]
    runtime: str = "python3.11"
    require_pinned_digest: bool = False            # True for qualification: image must be name@sha256:<digest>
    cpus: str = "1"
    memory: str = "256m"
    pids: int = 32
    wall_seconds: float = 10.0
    cpu_seconds: int = 8
    max_output_bytes: int = 65536
    max_file_bytes: int = 4 * 1024 * 1024
    tmpfs_bytes: int = 16 * 1024 * 1024
    nofile: int = 64
    user: str = "65534:65534"
    network: str = "none"
    allow_dependencies: tuple = ()                 # stdlib only: no dependency installation exists inside the sandbox
    policy_version: str = POLICY_VERSION

    def problems(self) -> list:
        p = []
        if self.runtime not in SUPPORTED_RUNTIMES:
            p.append("unsupported runtime")
        if self.network != "none":
            p.append("network must be 'none'")
        if self.user.split(":")[0] in ("0", "root", ""):
            p.append("must not run as root")
        if self.allow_dependencies:
            p.append("dependency installation is not permitted (stdlib only)")
        if self.require_pinned_digest and "@sha256:" not in self.image:
            p.append("qualification mode requires an image pinned by digest (name@sha256:...)")
        for name, v in (("cpus", float(self.cpus)), ("pids", self.pids), ("wall_seconds", self.wall_seconds), ("max_output_bytes", self.max_output_bytes),
                        ("tmpfs_bytes", self.tmpfs_bytes), ("max_file_bytes", self.max_file_bytes), ("nofile", self.nofile)):
            if not v or v <= 0:
                p.append(f"{name} must be positive")
        if self.pids > 256 or self.wall_seconds > 60 or self.max_output_bytes > (16 << 20):
            p.append("limits exceed the hermetic maximums")
        return p


@dataclass(frozen=True)
class SandboxJob:
    item_id: str
    candidate_revision: str
    files: Mapping[str, bytes]          # relative path -> bytes; mounted read-only at /job
    command: tuple                      # argv executed inside the container, cwd /work
    extra_env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionRecord:
    item_id: str
    candidate_revision: str
    sandbox_image_digest: str
    command: tuple
    exit_status: int | None
    timed_out: bool
    resource_limit_status: dict
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    test_result_digest: str
    duration_seconds: float
    sandbox_policy_version: str

    def as_dict(self) -> dict:
        d = asdict(self)
        d["command"] = list(self.command)
        return d


# ----------------------------------------------------------------------------------------------------------- staging (host side)
def validate_relpath(rel: str) -> str:
    if not isinstance(rel, str) or not rel or len(rel) > MAX_PATH_LEN or "\x00" in rel or "\\" in rel or rel.startswith("/") or rel.endswith("/"):
        raise SandboxPolicyViolation("illegal job path")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts) or os.path.normpath(rel) != rel:
        raise SandboxPolicyViolation("path traversal or non-normalized job path")
    return rel


def stage_files(files: Mapping[str, bytes], root: Path) -> None:
    """Materialize files as regular, read-only files under a fresh directory (O_EXCL|O_NOFOLLOW; no symlinks, no hardlinks, no specials)."""
    if len(files) > MAX_FILES:
        raise SandboxPolicyViolation("too many job files")
    total = 0
    for rel, data in files.items():
        validate_relpath(rel)
        if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_FILE_BYTES:
            raise SandboxPolicyViolation("job file must be bytes within the size limit")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise SandboxPolicyViolation("job too large")
        dest = root / rel
        parent = dest.parent
        cur = root
        for comp in parent.relative_to(root).parts:
            cur = cur / comp
            if cur.is_symlink():
                raise SandboxPolicyViolation("symlinked directory in job path")
            cur.mkdir(exist_ok=True)
            os.chmod(cur, 0o755)
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o444)
        with os.fdopen(fd, "wb") as f:
            f.write(bytes(data))


def load_fixture_tree(path: Path) -> dict:
    """Read a fixture directory from disk for mounting. Refuses symlinks, hardlinks, special files and anything resolving outside the tree."""
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise SandboxPolicyViolation("fixture root must be a real directory")
    base = path.resolve()
    out = {}
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        for name in list(dirnames) + filenames:
            p = Path(dirpath) / name
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                raise SandboxPolicyViolation("symlink in fixture tree")
            if p.is_file():
                if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
                    raise SandboxPolicyViolation("special file or hardlink in fixture tree")
                if base not in p.resolve().parents:
                    raise SandboxPolicyViolation("fixture resolves outside its tree")
                out[str(p.relative_to(base))] = p.read_bytes()
            elif not p.is_dir():
                raise SandboxPolicyViolation("special file in fixture tree")
    return out


# ----------------------------------------------------------------------------------------------------------- docker command
def _env(policy: SandboxPolicy, job: SandboxJob) -> dict:
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "PYTHONHASHSEED": "0",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1"}
    for k, v in job.extra_env.items():
        if not k.replace("_", "").isalnum() or k in env or k.upper().startswith(("AWS", "GITHUB", "ORNEUR", "ANTHROPIC", "OPENAI", "DOCKER")):
            raise SandboxPolicyViolation("illegal extra environment variable")
        env[k] = str(v)
    return env


def build_docker_args(policy: SandboxPolicy, job: SandboxJob, job_dir: Path, name: str) -> list:
    """Pure function: the exact argv for `docker run`. Tested without Docker."""
    pr = policy.problems()
    if pr:
        raise SandboxPolicyViolation("; ".join(pr))
    if not job.command or not all(isinstance(c, str) and c for c in job.command):
        raise SandboxPolicyViolation("command must be a non-empty argv of strings")
    mb = max(1, policy.tmpfs_bytes // (1024 * 1024))
    tmpfs_opts = f"rw,noexec,nosuid,nodev,size={mb}m,mode=1777"
    args = ["docker", "run", "--name", name, "--label", LABEL, "--pull", "never",
            "--network", policy.network, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", policy.user, "--ipc", "private", "--pids-limit", str(policy.pids), "--memory", policy.memory, "--memory-swap", policy.memory,
            "--cpus", policy.cpus, "--ulimit", f"nofile={policy.nofile}:{policy.nofile}", "--ulimit", f"nproc={policy.pids}:{policy.pids}",
            "--ulimit", f"fsize={policy.max_file_bytes}:{policy.max_file_bytes}", "--ulimit", f"cpu={policy.cpu_seconds}:{policy.cpu_seconds}",
            "--ulimit", "core=0:0", "--tmpfs", f"/tmp:{tmpfs_opts}", "--tmpfs", f"/work:{tmpfs_opts}",
            "--mount", f"type=bind,source={job_dir},target=/job,readonly", "--workdir", "/work", "--hostname", "sandbox", "--stop-timeout", "1"]
    # `env -i` inside the container wipes even the image's own ENV; the program sees EXACTLY the allow-list and nothing else
    args += [policy.image, "/usr/bin/env", "-i", *[f"{k}={v}" for k, v in _env(policy, job).items()], *job.command]
    return args


def _host_env() -> dict:
    """Minimal environment for the docker CLI itself. Credentials/tokens of the host process are not passed on."""
    keep = {}
    for k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "XDG_RUNTIME_DIR"):
        if os.environ.get(k):
            keep[k] = os.environ[k]
    return keep


def _docker(*args, timeout=30) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, env=_host_env())


def resolve_image_digest(image: str) -> str:
    r = _docker("image", "inspect", image, "--format", "{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}{{.Id}}{{end}}")
    if r.returncode != 0 or not r.stdout.strip():
        raise SandboxUnavailable(f"image {image!r} is not present locally (execution never pulls images)")
    return r.stdout.strip()


# ----------------------------------------------------------------------------------------------------------- execution
def run_job(job: SandboxJob, policy: SandboxPolicy | None = None) -> ExecutionRecord:
    policy = policy or SandboxPolicy()
    if not is_docker_available():
        raise SandboxUnavailable("Docker is not reachable; coding items are never executed without the hermetic sandbox")
    job_dir = Path(tempfile.mkdtemp(prefix="gce2-sbx-"))
    os.chmod(job_dir, 0o755)
    name = "gce2-sbx-" + uuid.uuid4().hex[:16]
    try:
        stage_files(job.files, job_dir)
        digest = resolve_image_digest(policy.image)
        args = build_docker_args(policy, job, job_dir, name)
        start = time.monotonic()
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_host_env())
        buf = {"out": bytearray(), "err": bytearray()}
        seen = {"out": 0, "err": 0}
        exceeded = threading.Event()

        def pump(stream, key):
            while True:
                chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
                if not chunk:
                    return
                seen[key] += len(chunk)
                room = policy.max_output_bytes - len(buf[key])
                if room > 0:
                    buf[key] += chunk[:room]
                if seen[key] > policy.max_output_bytes:
                    exceeded.set()
        threads = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True), threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
        for t in threads:
            t.start()
        timed_out = False
        while proc.poll() is None:
            if exceeded.is_set() or time.monotonic() - start > policy.wall_seconds:
                timed_out = not exceeded.is_set()
                _docker("kill", name, timeout=15)
                break
            time.sleep(0.02)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for t in threads:
            t.join(timeout=5)
        duration = time.monotonic() - start
        insp = _docker("inspect", name, "--format", "{{.State.OOMKilled}}|{{.State.ExitCode}}")
        oom = insp.returncode == 0 and insp.stdout.strip().startswith("true")
        code = None
        if insp.returncode == 0 and "|" in insp.stdout:
            try:
                code = int(insp.stdout.strip().split("|")[1])
            except ValueError:
                code = None
        out, err = bytes(buf["out"]), bytes(buf["err"])
        limits = {"oom_killed": oom, "wall_timeout": timed_out, "output_limit_exceeded": exceeded.is_set(),
                  "limit_hit": bool(oom or timed_out or exceeded.is_set())}
        so, se = hashlib.sha256(out).hexdigest(), hashlib.sha256(err).hexdigest()
        trd = hashlib.sha256(json.dumps({"exit": code, "timed_out": timed_out, "limits": limits, "stdout": so, "stderr": se}, sort_keys=True).encode()).hexdigest()
        return ExecutionRecord(job.item_id, job.candidate_revision, digest, tuple(job.command), code, timed_out, limits, so, se, seen["out"], seen["err"], trd,
                               round(duration, 3), policy.policy_version)
    finally:
        try:
            _docker("rm", "-f", name, timeout=20)         # the container never outlives the call
        except Exception:
            pass
        shutil.rmtree(job_dir, ignore_errors=True)


def leftover_containers() -> list:
    r = _docker("ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}")
    return [x for x in r.stdout.split() if x]


def policy_manifest(policy: SandboxPolicy | None = None) -> dict:
    """Content-free description of the policy in force (goes into the preregistration; never contains task content)."""
    p = policy or SandboxPolicy()
    return {**asdict(p), "supported_runtimes": SUPPORTED_RUNTIMES, "isolation": "one fresh container per item; no state shared; destroyed after scoring",
            "mounts": ["/job (staged job directory, read-only)"], "forbidden": ["docker socket", "privileged", "host pid", "host network", "host ipc", "secrets"]}
