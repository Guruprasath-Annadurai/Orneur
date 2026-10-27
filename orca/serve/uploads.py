"""Tenant-separated uploads with size limits. Not a substitute for process isolation."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from orca.config import ORCA_HOME

MAX_BYTES = 1_048_576
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class UploadError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _root(user_id: str) -> Path:
    digest = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    path = ORCA_HOME / "uploads" / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def store(user_id: str, filename: str, data: bytes) -> dict:
    if not user_id:
        raise UploadError("unauthenticated")
    if not _SAFE_NAME.match(filename) or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise UploadError("filename_refused")
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0 or len(data) > MAX_BYTES:
        raise UploadError("size_refused")
    dest = _root(user_id) / filename
    if dest.exists():
        raise UploadError("duplicate_name")
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(bytes(data))
    tmp.replace(dest)
    return {
        "filename": filename,
        "nbytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "user_id": user_id,
    }


def read(user_id: str, filename: str) -> bytes:
    if not _SAFE_NAME.match(filename):
        raise UploadError("filename_refused")
    path = _root(user_id) / filename
    if not path.is_file() or path.is_symlink():
        raise UploadError("not_found")
    return path.read_bytes()


def delete(user_id: str, filename: str) -> dict:
    if not _SAFE_NAME.match(filename):
        raise UploadError("filename_refused")
    path = _root(user_id) / filename
    existed = path.is_file()
    if existed:
        path.unlink()
    return {"deleted": existed, "filename": filename}
