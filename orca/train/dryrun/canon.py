"""Canonical serialization, hashing and atomic file writes shared by the synthetic dry-run harness.

Pure standard library. Nothing here touches the network, a GPU, or a path the caller did not pass in.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ZERO_HASH = "0" * 64


def canonical_bytes(obj) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, ASCII only, and NaN/Infinity are rejected (they have no canonical form)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(obj) -> str:
    return sha256_hex(canonical_bytes(obj))


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fsync_dir(path: Path) -> None:
    """Make a rename/creation inside `path` durable. Best effort on platforms without directory fsync."""
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path, data: bytes) -> None:
    """Write `data` to `path` so a reader sees either the old file or the complete new one: temp file in the SAME directory, flush, fsync,
    rename over the target, fsync the directory. A crash leaves at worst an orphan `.tmp-*` file, never a half-written target."""
    path = Path(path)
    tmp = path.with_name(".tmp-" + path.name + "-" + hashlib.sha256(os.urandom(16)).hexdigest()[:8])
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    fsync_dir(path.parent)
