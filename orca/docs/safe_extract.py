"""L02-02: bounded, isolated text extraction for container formats (PDF, DOCX).

The parsers for these formats are large third-party code fed attacker-controlled bytes. They run in a CHILD PROCESS with a wall-clock timeout, a CPU limit, an
address-space limit and a bounded output, so a parser hang, a decompression bomb that slipped past the pre-checks, or a crash costs one child process - never the
server's event loop, memory or threads. Plain-text formats are decoded in-process (cost is bounded by the already-enforced upload size).
"""
from __future__ import annotations

import asyncio
import json
import os
import resource
import sys

from orca.docs.validation import UploadRejected

CONTAINER_EXT = {".pdf", ".docx"}
TIMEOUT_S = 20.0
MEM_BYTES = 1536 * 1024 * 1024
MAX_OUT_BYTES = 12 * 1024 * 1024


class ExtractUnavailable(Exception):
    """The parser for this format is not installed on this deployment."""


class ExtractFailed(Exception):
    """The file could not be parsed (malformed, encrypted, hostile)."""


def _limits(timeout_s: float):
    def apply():
        resource.setrlimit(resource.RLIMIT_AS, (MEM_BYTES, MEM_BYTES))
        cpu = int(timeout_s) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()
    return apply


def _run_blocking(argv, env, payload: bytes, timeout_s: float):
    """Run the child with plain ``subprocess`` + threads (asyncio's subprocess ``wait()`` can block forever on an unread, still-open stdout pipe after a kill).
    Returns (returncode, stdout_bytes). Raises UploadRejected on timeout or output flood; the child's whole process group is killed and reaped first."""
    import subprocess
    import threading
    import time

    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, preexec_fn=_limits(timeout_s))
    deadline = time.monotonic() + timeout_s
    state = {"reject": None}
    chunks: list[bytes] = []
    total = 0

    def feed():
        try:
            proc.stdin.write(payload)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()

    def reap(reject):
        state["reject"] = reject
        _kill(proc)

    timer = threading.Timer(max(0.0, deadline - time.monotonic()), lambda: reap(UploadRejected("extraction_timeout", "This file took too long to read and was stopped.")))
    timer.daemon = True
    timer.start()
    try:
        while True:
            block = proc.stdout.read(1024 * 1024)
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > MAX_OUT_BYTES:
                reap(UploadRejected("document_too_large", "This document produced too much text.", 413))
                break
    finally:
        timer.cancel()
        try:
            proc.stdout.close()
        except OSError:
            pass
        _kill(proc)                       # the child's group is always gone before we return (grandchildren included)
        proc.wait()
        feeder.join(timeout=1)
    if state["reject"] is not None:
        raise state["reject"]
    return proc.returncode, b"".join(chunks)


async def extract_isolated(filename: str, data: bytes, *, timeout_s: float = TIMEOUT_S, _argv: list[str] | None = None) -> str:
    argv = _argv or [sys.executable, "-m", "orca.docs._extract_worker"]
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "PYTHONPATH", "HOME", "LANG", "LC_ALL", "ORNEUR_HOME", "ORCA_HOME", "VIRTUAL_ENV")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    payload = json.dumps({"filename": filename}).encode() + b"\n" + data
    returncode, out = await asyncio.to_thread(_run_blocking, argv, env, payload, timeout_s)
    if returncode != 0 or not out:
        raise ExtractFailed("worker_exit")
    try:
        result = json.loads(out)
    except ValueError:
        raise ExtractFailed("worker_output")
    if result.get("ok"):
        return str(result.get("text", ""))
    kind = result.get("kind")
    if kind == "unavailable":
        raise ExtractUnavailable()
    if kind == "unsupported":
        raise ValueError(result.get("message", "unsupported"))
    raise ExtractFailed(kind or "failed")


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
