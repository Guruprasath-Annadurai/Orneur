"""Authorized pytest runs inside a user, mount, pid, and network namespace.

An arbitrary command is not accepted. If the namespace tools are missing,
nothing is executed and the caller reports the containment gap. The jail is
single-host isolation, not a production sandbox certification.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_TEST_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.py$")
_SCRIPT = r"""
set -eu
base=$1
rel=$2
wall=$3
cpu=$4
mem=$5
mkdir -p "$base/root"
mount -t tmpfs -o size=128m tmpfs "$base/root"
mkdir -p "$base/root/usr" "$base/root/bin" "$base/root/lib" "$base/root/lib64" "$base/root/work" "$base/root/tmp" "$base/root/proc" "$base/root/dev"
mount --bind /usr "$base/root/usr"
mount -o remount,bind,ro "$base/root/usr"
if [ -d /lib ]; then mount --bind /lib "$base/root/lib"; mount -o remount,bind,ro "$base/root/lib"; fi
if [ -d /lib64 ]; then mount --bind /lib64 "$base/root/lib64"; mount -o remount,bind,ro "$base/root/lib64"; fi
if [ -d /bin ]; then mount --bind /bin "$base/root/bin"; mount -o remount,bind,ro "$base/root/bin"; fi
cp -a "$base/src/." "$base/root/work/"
chmod 1777 "$base/root/tmp"
for node in null zero urandom; do
  touch "$base/root/dev/$node"
  mount --bind "/dev/$node" "$base/root/dev/$node"
done
mount -t proc proc "$base/root/proc"
cd "$base/root"
exec prlimit --cpu="$cpu" --as="$mem" timeout --kill-after=2s "$wall" /usr/sbin/chroot "$base/root" /usr/bin/env -i PATH=/usr/bin:/bin HOME=/tmp TMPDIR=/tmp LANG=C LC_ALL=C PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/work /usr/bin/python3 -m pytest -q --tb=line -p no:cacheprovider "$rel"
"""


class ContainmentError(Exception):
    """The process was not started."""


def containment_status() -> dict:
    missing = [tool for tool in ("/usr/bin/unshare", "/bin/bash", "/usr/sbin/chroot", "/usr/bin/prlimit", "/usr/bin/timeout") if not Path(tool).exists()]
    if missing:
        return {"available": False, "gap": "missing " + ",".join(missing), "executed": False}
    try:
        proc = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--net", "--mount", "--pid", "--fork", "--", "/bin/true"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "gap": f"namespace probe failed: {exc}", "executed": False}
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace")[:240]
        return {"available": False, "gap": detail or "namespace probe failed", "executed": False}
    return {
        "available": True,
        "gap": None,
        "executed": False,
        "filesystem": "tmpfs-chroot",
        "network": "new-netns",
        "identity": "user-namespace",
        "limits": "prlimit-cpu-as-and-timeout",
        "multi_host": False,
    }


def run_authorized_pytest(
    workspace: Path,
    relative_test: str,
    *,
    wall_seconds: int = 20,
    cpu_seconds: int = 8,
    memory_bytes: int = 768 * 1024 * 1024,
) -> dict:
    relative = _validate_test(workspace, relative_test)
    if wall_seconds < 1 or wall_seconds > 60 or cpu_seconds < 1 or cpu_seconds > 30:
        raise ContainmentError("resource budget is outside the authorized range")
    if memory_bytes < 256 * 1024 * 1024 or memory_bytes > 1024 * 1024 * 1024:
        raise ContainmentError("memory budget is outside the authorized range")
    status = containment_status()
    if not status["available"]:
        raise ContainmentError(status["gap"] or "containment is unavailable")
    test_bytes = (Path(workspace) / relative).read_bytes()
    test_digest = hashlib.sha256(test_bytes).hexdigest()
    command = ["python3", "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider", relative]
    base = Path(tempfile.mkdtemp(prefix="orneur-jail-"))
    try:
        _copy_regular_tree(Path(workspace), base / "src")
        script = base / "enter.sh"
        script.write_text(_SCRIPT)
        proc = subprocess.run(
            [
                "unshare", "--user", "--map-root-user", "--net", "--mount", "--pid", "--fork", "--kill-child", "--",
                "/bin/bash", str(script), str(base), "/work/" + relative, str(wall_seconds), str(cpu_seconds), str(memory_bytes),
            ],
            capture_output=True,
            timeout=wall_seconds + 15,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/sbin"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ContainmentError("the jail did not exit before the outer deadline") from exc
    finally:
        shutil.rmtree(base, ignore_errors=True)
    output = ((proc.stdout or b"") + (proc.stderr or b""))[:64000]
    return {
        "executed": True,
        "exit_code": proc.returncode,
        "command": command,
        "test_digest": test_digest,
        "output": output.decode("utf-8", "replace"),
        "containment": "user-namespace-chroot",
        "network": "new-netns",
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "memory_bytes": memory_bytes,
        "exactly_once": False,
    }


def _validate_test(workspace: Path, relative_test: str) -> str:
    if not isinstance(relative_test, str) or not _TEST_PATH.fullmatch(relative_test) or ".." in relative_test.split("/"):
        raise ContainmentError("test path is not an authorized relative pytest file")
    root = Path(workspace).resolve()
    candidate = root / relative_test
    if candidate.is_symlink():
        raise ContainmentError("symlink refused")
    target = candidate.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ContainmentError("test path is not a regular file inside the workspace")
    return relative_test


def _copy_regular_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        current = Path(dirpath)
        kept = []
        for name in dirnames:
            child = current / name
            if child.is_symlink():
                raise ContainmentError("symlink refused")
            kept.append(name)
        dirnames[:] = kept
        relative = current.relative_to(src)
        (dst / relative).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            child = current / name
            if child.is_symlink() or not child.is_file():
                raise ContainmentError("symlink refused")
            target = dst / relative / name
            target.write_bytes(child.read_bytes())
