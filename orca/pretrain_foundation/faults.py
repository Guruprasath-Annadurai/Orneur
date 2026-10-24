"""Deterministic fault injection for local file publication.

`publish_bytes` writes to a temp file in the destination directory and
renames it into place. Injected faults leave the destination untouched.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


class InjectedFault(Exception):
    """A test-requested fault. Not an operational success."""


def publish_bytes(path: Path, data: bytes, *, inject: str | None = None) -> None:
    """Atomically publish `data` to `path`.

    `inject` is one of None, `disk_full`, `partial_write`, or
    `after_write_before_rename`. Any of those raises `InjectedFault`
    after leaving `path` absent or unchanged.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise InjectedFault(f"refusing to publish through symlink {path}")
    before = path.read_bytes() if path.exists() else None
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        if inject == "disk_full":
            raise InjectedFault("injected disk full before any byte was committed")
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            if inject == "partial_write":
                handle.write(data[: max(0, len(data) // 2)])
                handle.flush()
                raise InjectedFault("injected failure after a partial temp write")
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if inject == "after_write_before_rename":
            raise InjectedFault("injected failure after the temp file was durable and before rename")
        if inject is not None:
            raise ValueError(f"unknown inject mode {inject!r}")
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        after = path.read_bytes() if path.exists() else None
        if after != before:
            raise InjectedFault("fault path modified the destination; this is a publisher bug") from None
        raise
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


def destination_unchanged(path: Path, previous: bytes | None) -> bool:
    if previous is None:
        return not path.exists()
    return path.is_file() and not path.is_symlink() and path.read_bytes() == previous
