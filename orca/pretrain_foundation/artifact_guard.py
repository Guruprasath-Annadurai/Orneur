"""Local file checks for synthetic fixtures.

A digest mismatch or a symlink leaf is refused. This is not a signature
and it does not enroll a reviewer.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


class ArtifactBoundaryError(Exception):
    """The path or the bytes are not the artifact that was bound."""


def read_regular_nofollow(path: Path) -> bytes:
    """Read one regular file without following a symlink at the leaf."""
    path = Path(path)
    if not hasattr(os, "O_NOFOLLOW"):
        raise ArtifactBoundaryError("refusing artifact access without O_NOFOLLOW")
    directory = path.parent
    if directory.is_symlink():
        raise ArtifactBoundaryError("refusing a symlink directory")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ArtifactBoundaryError("artifact directory could not be opened") from exc
    try:
        try:
            fd = os.open(path.name, flags, dir_fd=dir_fd)
        except OSError as exc:
            raise ArtifactBoundaryError(f"refusing to read {path.name}") from exc
        try:
            info = os.fstat(fd)
            if not stat_is_regular(info.st_mode):
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


def checkpoint_digest(path: Path) -> str:
    return hashlib.sha256(read_regular_nofollow(path)).hexdigest()


def require_checkpoint(path: Path, expected_digest: str) -> bytes:
    payload = read_regular_nofollow(path)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_digest:
        raise ArtifactBoundaryError("checkpoint digest does not match the bound value")
    return payload
