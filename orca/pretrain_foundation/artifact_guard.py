"""Local file checks for synthetic fixtures.

Every path component is opened with ``O_NOFOLLOW`` from the directory fd
of its parent. A symlink at the leaf, the parent, or an ancestor is
refused, including a symlink that replaces a directory after a stat.
A digest mismatch is refused. This is not a signature and it does not
enroll a reviewer.
"""
from __future__ import annotations

import hashlib
import os
import stat
import threading
from pathlib import Path


class ArtifactBoundaryError(Exception):
    """The path or the bytes are not the artifact that was bound."""


def _components(path: Path) -> list[str]:
    text = str(path)
    if not os.path.isabs(text):
        text = os.path.join(os.getcwd(), text)
    parts = [part for part in text.split(os.sep) if part]
    if not parts:
        raise ArtifactBoundaryError("artifact path is empty")
    if any(part in {".", ".."} for part in parts):
        raise ArtifactBoundaryError("refusing a non-canonical artifact path")
    return parts


def _open_parent(parts: list[str]) -> int:
    """Return a directory fd for the parent of the last component."""
    if len(parts) < 1:
        raise ArtifactBoundaryError("artifact path is empty")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if not hasattr(os, "O_NOFOLLOW"):
        raise ArtifactBoundaryError("refusing artifact access without O_NOFOLLOW")
    fd = os.open(os.sep, flags)
    try:
        for part in parts[:-1]:
            try:
                nxt = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise ArtifactBoundaryError("refusing a symlink or missing directory") from exc
            os.close(fd)
            fd = nxt
        return fd
    except Exception:
        os.close(fd)
        raise


def read_regular_nofollow(path: Path) -> bytes:
    """Read one regular file without following a symlink on any component."""
    parts = _components(Path(path))
    dir_fd = _open_parent(parts)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        try:
            fd = os.open(parts[-1], flags, dir_fd=dir_fd)
        except OSError as exc:
            raise ArtifactBoundaryError(f"refusing to read {parts[-1]}") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactBoundaryError("artifact is not a regular file")
            chunks = []
            while True:
                block = os.read(fd, 64 * 1024)
                if not block:
                    break
                chunks.append(block)
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)


def stat_is_regular(mode: int) -> bool:
    return stat.S_ISREG(mode)


def atomic_write_regular(path: Path, data: bytes) -> None:
    """Write bytes by rename on a no-follow directory fd."""
    parts = _components(Path(path))
    dir_fd = _open_parent(parts)
    tmp_name = f".{parts[-1]}.{os.getpid()}.{threading.get_ident()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise ArtifactBoundaryError("artifact write stalled")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_name, parts[-1], src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def checkpoint_digest(path: Path) -> str:
    return hashlib.sha256(read_regular_nofollow(path)).hexdigest()


def require_checkpoint(path: Path, expected_digest: str) -> bytes:
    payload = read_regular_nofollow(path)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_digest:
        raise ArtifactBoundaryError("checkpoint digest does not match the bound value")
    return payload
