"""Authenticated untrusted-code execution behind a Docker isolator.

This is the product G1 path. It does not replace Sovereign Mission and
does not fall back to host subprocess execution. Callers cannot choose
Docker security flags, images, mounts, or network mode.

HTTP exposure stays off unless ORNEUR_UNTRUSTED_EXECUTION=development.
Shared-kernel containers are not a VM/hardware TEE: public multi-tenant
execution still needs an additional isolation technology after independent
qualification.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

from orca.serve.usage import record_usage

ALLOWED_IMAGE = "python:3.11-alpine"
ALLOWED_IMAGE_DIGEST = "sha256:79440cc1dfa86a5f98d67efcd219726a8e9d8083cc0aafd27c7bef5976c38868"
MAX_CODE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_CONCURRENT = 2
DEFAULT_TIMEOUT_S = 8.0
MEMORY = "64m"
CPUS = "0.5"
PIDS = 32
TMPFS_SIZE = "32m"

_LOCK = threading.Lock()
_SEM = threading.BoundedSemaphore(MAX_CONCURRENT)
_TEST_DB: Path | None = None


class UntrustedError(Exception):
    def __init__(self, code: str, **extra):
        self.code = code
        self.extra = extra
        super().__init__(code)


def set_job_path(path: Path | None) -> None:
    global _TEST_DB
    _TEST_DB = path


def _db_path() -> Path:
    if _TEST_DB is not None:
        return _TEST_DB
    from orca.config import ORCA_HOME

    return ORCA_HOME / "untrusted_jobs.sqlite"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            exit_code INTEGER,
            stdout TEXT,
            stderr TEXT,
            image TEXT,
            image_digest TEXT,
            limits_json TEXT,
            container_name TEXT,
            container_confirmed_stopped INTEGER,
            verified INTEGER,
            started_at REAL,
            finished_at REAL
        )
        """
    )
    conn.commit()
    return conn


def reset_for_tests() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM jobs")
            conn.commit()
        finally:
            conn.close()


def _user_id(user: object) -> str:
    if isinstance(user, (str, bytes, bytearray, dict)):
        raise UntrustedError("unauthenticated")
    uid = getattr(user, "id", None)
    if not isinstance(uid, str) or not uid.strip():
        raise UntrustedError("unauthenticated")
    return uid


def docker_bin() -> str | None:
    return shutil.which("docker")


def daemon_usable() -> bool:
    if docker_bin() is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def isolator() -> str | None:
    if daemon_usable():
        return "docker"
    return None


def execution_enabled() -> bool:
    from orca.config import orneur_env

    return orneur_env("UNTRUSTED_EXECUTION", "").strip().lower() == "development"


def _docker(args: list[str], *, timeout: float = 30.0, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )


def _image_present() -> bool:
    inspect = _docker(["image", "inspect", ALLOWED_IMAGE], timeout=15)
    return inspect.returncode == 0


def _image_digest() -> str | None:
    inspect = _docker(
        ["image", "inspect", ALLOWED_IMAGE, "--format", "{{index .RepoDigests 0}}"],
        timeout=15,
    )
    if inspect.returncode != 0:
        return None
    digest = (inspect.stdout or "").strip()
    return digest or None


def _refuse_caller_controls(**flags) -> None:
    for name, value in flags.items():
        if value not in (None, False, (), [], {}):
            raise UntrustedError("caller_flags_refused", flag=name)


def _run_argv(container_name: str) -> list[str]:
    return [
        "run",
        "--name",
        container_name,
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,exec,nosuid,nodev,size={TMPFS_SIZE},uid=65534,gid=65534",
        "--tmpfs",
        f"/workspace:rw,exec,nosuid,nodev,size={TMPFS_SIZE},uid=65534,gid=65534",
        "-w",
        "/workspace",
        "--memory",
        MEMORY,
        "--memory-swap",
        MEMORY,
        "--cpus",
        CPUS,
        "--pids-limit",
        str(PIDS),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "-e",
        "HOME=/tmp",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "PYTHONNOUSERSITE=1",
        "-i",
        ALLOWED_IMAGE,
        "python3",
        "-I",
        "-S",
        "-",
    ]


def _container_running(name: str) -> bool:
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return inspect.returncode == 0 and inspect.stdout.strip() == "true"


def _stop_container(name: str) -> bool:
    """Ask Docker to stop the container. True only if it is gone or not running."""
    subprocess.run(["docker", "kill", name], capture_output=True, timeout=20)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
    return not _container_running(name)


def get_job(*, user: object, job_id: str) -> dict:
    uid = _user_id(user)
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        finally:
            conn.close()
    if row is None:
        raise UntrustedError("job_not_found")
    if row["user_id"] != uid:
        raise UntrustedError("access_denied")
    return dict(row)


def list_jobs(*, user: object) -> list[dict]:
    uid = _user_id(user)
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT job_id, task_id, status, verified, started_at FROM jobs WHERE user_id = ? ORDER BY started_at",
                (uid,),
            ).fetchall()
        finally:
            conn.close()
    return [dict(row) for row in rows]


def _save(row: dict) -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    job_id, user_id, task_id, status, exit_code, stdout, stderr,
                    image, image_digest, limits_json, container_name,
                    container_confirmed_stopped, verified, started_at, finished_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["job_id"],
                    row["user_id"],
                    row["task_id"],
                    row["status"],
                    row.get("exit_code"),
                    row.get("stdout", ""),
                    row.get("stderr", ""),
                    row.get("image"),
                    row.get("image_digest"),
                    json.dumps(row.get("limits") or {}),
                    row.get("container_name"),
                    1 if row.get("container_confirmed_stopped") else 0,
                    1 if row.get("verified") else 0,
                    row.get("started_at"),
                    row.get("finished_at"),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def inspect_isolation_flags(container_name: str) -> dict:
    """Return HostConfig for a still-named container. Used by tests."""
    inspect = _docker(["inspect", container_name], timeout=15)
    if inspect.returncode != 0:
        raise UntrustedError("inspect_failed")
    payload = json.loads(inspect.stdout)[0]
    host = payload.get("HostConfig") or {}
    return {
        "privileged": bool(host.get("Privileged")),
        "network_mode": host.get("NetworkMode"),
        "readonly_rootfs": bool(host.get("ReadonlyRootfs")),
        "pids_limit": host.get("PidsLimit"),
        "memory": host.get("Memory"),
        "nano_cpus": host.get("NanoCpus"),
        "cap_drop": host.get("CapDrop") or [],
        "security_opt": host.get("SecurityOpt") or [],
        "binds": host.get("Binds") or [],
        "pid_mode": host.get("PidMode") or "",
        "user": payload.get("Config", {}).get("User"),
    }


def execute(
    source: str,
    *,
    user: object,
    task_id: str = "untrusted-dev",
    cancel: threading.Event | None = None,
    privileged: bool = False,
    image: str | None = None,
    network: str | None = None,
    mounts: list | None = None,
    extra_args: list | None = None,
    timeout_s: float | None = None,
) -> dict:
    uid = _user_id(user)
    _refuse_caller_controls(privileged=privileged, image=image, network=network, mounts=mounts, extra_args=extra_args)
    if not isinstance(source, str) or not source.strip():
        raise UntrustedError("source_refused")
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_CODE_BYTES:
        raise UntrustedError("source_too_large")
    if not isinstance(task_id, str) or not task_id.strip() or "/" in task_id or ".." in task_id:
        raise UntrustedError("task_refused")
    if isolator() is None:
        raise UntrustedError("isolation_unavailable")
    if not _image_present():
        raise UntrustedError("image_unavailable")

    deadline = DEFAULT_TIMEOUT_S if timeout_s is None else float(timeout_s)
    if deadline <= 0 or deadline > 30:
        raise UntrustedError("timeout_refused")

    acquired = _SEM.acquire(timeout=2.0)
    if not acquired:
        raise UntrustedError("concurrency_refused")
    job_id = uuid.uuid4().hex
    container_name = f"orneur-g1-{job_id[:12]}"
    started = time.time()
    row = {
        "job_id": job_id,
        "user_id": uid,
        "task_id": task_id.strip(),
        "status": "running",
        "image": ALLOWED_IMAGE,
        "image_digest": _image_digest(),
        "limits": {
            "memory": MEMORY,
            "cpus": CPUS,
            "pids": PIDS,
            "timeout_s": deadline,
            "network": "none",
            "user": "65534:65534",
            "cap_drop": "ALL",
            "read_only": True,
            "no_new_privileges": True,
        },
        "container_name": container_name,
        "container_confirmed_stopped": False,
        "verified": False,
        "started_at": started,
        "stdout": "",
        "stderr": "",
        "exit_code": None,
        "finished_at": None,
    }
    _save(row)
    argv = _run_argv(container_name)
    proc: subprocess.Popen | None = None
    status = "unknown"
    confirmed = False
    try:
        proc = subprocess.Popen(
            ["docker", *argv],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def _watch_cancel():
            if cancel is None:
                return
            while proc.poll() is None:
                if cancel.is_set():
                    _stop_container(container_name)
                    return
                time.sleep(0.05)

        watcher = threading.Thread(target=_watch_cancel, daemon=True)
        watcher.start()
        try:
            stdout, stderr = proc.communicate(input=source, timeout=deadline)
            if cancel is not None and cancel.is_set():
                status = "cancelled"
                confirmed = not _container_running(container_name)
                row.update(
                    {
                        "status": status,
                        "exit_code": proc.returncode,
                        "stdout": (stdout or "")[:MAX_OUTPUT_BYTES],
                        "stderr": "cancelled",
                        "container_confirmed_stopped": confirmed,
                        "verified": False,
                        "finished_at": time.time(),
                    }
                )
            else:
                code = proc.returncode
                truncated = len(stdout or "") > MAX_OUTPUT_BYTES or len(stderr or "") > MAX_OUTPUT_BYTES
                status = "succeeded" if code == 0 else "failed"
                confirmed = True
                row.update(
                    {
                        "status": status,
                        "exit_code": code,
                        "stdout": (stdout or "")[:MAX_OUTPUT_BYTES],
                        "stderr": (stderr or "")[:MAX_OUTPUT_BYTES],
                        "output_truncated": truncated,
                        "container_confirmed_stopped": confirmed,
                        "verified": status == "succeeded",
                        "finished_at": time.time(),
                    }
                )
        except subprocess.TimeoutExpired:
            status = "timed_out"
            confirmed = _stop_container(container_name)
            try:
                leftover = proc.communicate(timeout=10)
            except Exception:
                leftover = ("", "")
            row.update(
                {
                    "status": status,
                    "exit_code": proc.returncode,
                    "stdout": (leftover[0] or "")[:MAX_OUTPUT_BYTES],
                    "stderr": "deadline_exceeded",
                    "container_confirmed_stopped": confirmed,
                    "verified": False,
                    "finished_at": time.time(),
                }
            )
    except UntrustedError:
        raise
    except Exception as exc:
        if proc is not None:
            confirmed = _stop_container(container_name)
        row.update(
            {
                "status": "unknown",
                "stderr": f"runtime_error:{type(exc).__name__}",
                "container_confirmed_stopped": confirmed,
                "verified": False,
                "finished_at": time.time(),
            }
        )
        _save(row)
        raise UntrustedError("outcome_unknown") from exc
    finally:
        _SEM.release()

    if status == "unknown" and not confirmed:
        row["verified"] = False
        row["status"] = "unknown"
        _save(row)
        raise UntrustedError("outcome_unknown", job_id=job_id)

    _save(row)
    try:
        record_usage(user_id=uid, model="untrusted-python", backend="local", tokens_in=0, tokens_out=0)
    except Exception:
        pass
    return {
        "job_id": job_id,
        "user_id": uid,
        "task_id": task_id.strip(),
        "status": row["status"],
        "exit_code": row.get("exit_code"),
        "stdout": row.get("stdout", ""),
        "stderr": row.get("stderr", ""),
        "image": ALLOWED_IMAGE,
        "image_digest": row.get("image_digest"),
        "limits": row["limits"],
        "container_confirmed_stopped": bool(row.get("container_confirmed_stopped")),
        "verified": bool(row.get("verified")),
        "isolator": "docker",
        "native_family": None,
        "handlers_forcibly_stopped": False,
        "path": "docker",
    }


def spawn_probe_container() -> str:
    """Start a short-lived sleep container with the same isolation flags for inspect tests."""
    if isolator() is None:
        raise UntrustedError("isolation_unavailable")
    name = f"orneur-g1-probe-{uuid.uuid4().hex[:10]}"
    argv = _run_argv(name)
    # Drop stdin python runner (image + python3 -I -S -) and -i.
    sleep_argv = [a for a in argv[:-5] if a != "-i"] + [
        ALLOWED_IMAGE,
        "python3",
        "-I",
        "-S",
        "-c",
        "import time; time.sleep(12)",
    ]
    proc = subprocess.Popen(["docker", *sleep_argv], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 8
    while time.time() < deadline:
        if _container_running(name):
            return name
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise UntrustedError("probe_failed", detail=err[-500:])
        time.sleep(0.1)
    raise UntrustedError("probe_failed")
