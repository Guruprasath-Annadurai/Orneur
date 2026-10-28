"""Tenant-separated uploads with size limits. Not an OS isolation boundary.

A hashed directory name does not separate tenants at the kernel. Callers must
pass a server-authenticated User into store_for(); a raw user_id string is not
proof of authentication.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import threading
from pathlib import Path

from orca.auth.store import User
from orca.config import ORCA_HOME

MAX_BYTES = 1_048_576
_NAME = __import__("re").compile(r"^[A-Za-z0-9._-]{1,128}$")
_LOCK = threading.Lock()
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class UploadError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require_user(user: User) -> str:
    if not isinstance(user, User) or not user.id:
        raise UploadError("unauthenticated")
    return user.id


def _root(user_id: str) -> Path:
    digest = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    path = Path(ORCA_HOME) / "uploads" / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(filename: str) -> str:
    if not isinstance(filename, str) or not _NAME.match(filename) or filename in {".", ".."}:
        raise UploadError("filename_refused")
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise UploadError("filename_refused")
    return filename


def _lstat(path: Path):
    return os.lstat(path)


def _confined(root: Path, dest: Path) -> None:
    root_real = root.resolve()
    if dest.parent.resolve() != root_real:
        raise UploadError("path_refused")
    try:
        info = _lstat(dest)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise UploadError("symlink_refused")
    if not stat.S_ISREG(info.st_mode):
        raise UploadError("path_refused")


def store_for(user: User, filename: str, data: bytes) -> dict:
    return store(_require_user(user), filename, data)


def store(user_id: str, filename: str, data: bytes) -> dict:
    """Low-level write. Ownership identity is the caller-supplied user_id."""
    if not user_id:
        raise UploadError("unauthenticated")
    name = _safe_name(filename)
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0 or len(data) > MAX_BYTES:
        raise UploadError("size_refused")
    payload = bytes(data)
    digest = hashlib.sha256(payload).hexdigest()
    root = _root(user_id)
    dest = root / name
    tmp_name = None
    with _LOCK:
        _confined(root, dest)
        try:
            _lstat(dest)
        except FileNotFoundError:
            pass
        else:
            raise UploadError("duplicate_name")
        fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=str(root))
        try:
            written = 0
            view = memoryview(payload)
            while written < len(payload):
                written += os.write(fd, view[written:])
            os.fsync(fd)
        except Exception:
            os.close(fd)
            Path(tmp_name).unlink(missing_ok=True)
            raise UploadError("write_failed")
        os.close(fd)
        try:
            os.link(tmp_name, dest)
        except FileExistsError:
            Path(tmp_name).unlink(missing_ok=True)
            raise UploadError("duplicate_name")
        except OSError:
            Path(tmp_name).unlink(missing_ok=True)
            raise UploadError("publish_failed")
        Path(tmp_name).unlink(missing_ok=True)
        try:
            info = _lstat(dest)
        except FileNotFoundError as exc:
            raise UploadError("publish_failed") from exc
        if stat.S_ISLNK(info.st_mode):
            dest.unlink(missing_ok=True)
            raise UploadError("symlink_refused")
    return {
        "filename": name,
        "nbytes": len(payload),
        "sha256": digest,
        "user_id": user_id,
        "isolation": "directory_hash_not_os",
    }


def read_for(user: User, filename: str) -> bytes:
    return read(_require_user(user), filename)


def read(user_id: str, filename: str) -> bytes:
    name = _safe_name(filename)
    if not user_id:
        raise UploadError("unauthenticated")
    path = _root(user_id) / name
    _confined(_root(user_id), path)
    try:
        info = _lstat(path)
    except FileNotFoundError as exc:
        raise UploadError("not_found") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UploadError("not_found")
    fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW)
    try:
        return os.read(fd, info.st_size + 1)
    finally:
        os.close(fd)


def delete_for(user: User, filename: str) -> dict:
    return delete(_require_user(user), filename)


def delete(user_id: str, filename: str) -> dict:
    name = _safe_name(filename)
    if not user_id:
        raise UploadError("unauthenticated")
    path = _root(user_id) / name
    _confined(_root(user_id), path)
    existed = False
    try:
        info = _lstat(path)
    except FileNotFoundError:
        info = None
    if info is not None:
        if stat.S_ISLNK(info.st_mode):
            raise UploadError("symlink_refused")
        os.unlink(path)
        existed = True
    return {
        "deleted": existed,
        "filename": name,
        "scope": "local_object",
        "replicas_removed": "unknown",
        "other_indexes": "not_reconciled",
    }
