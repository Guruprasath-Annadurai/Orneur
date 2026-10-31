"""Where the vector service for one data directory keeps its socket, locks and token. Standard library only.

The run directory lives under the system temp directory (AF_UNIX paths are limited to ~100 characters, which long data-directory paths exceed), is named from the user id and a
hash of the data directory, is created 0700 and is refused if it is not owned by the current user or is group/world accessible."""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path


def run_dir(home: Path | str) -> Path:
    h = hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()[:16]
    d = Path(tempfile.gettempdir()) / f"orneur-vec-{os.getuid()}-{h}"
    try:
        d.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        raise
    st = d.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PermissionError(f"vector service run directory {d} is not private to this user")
    return d


def sock_path(home) -> Path:
    return run_dir(home) / "sock"


def owner_lock_path(home) -> Path:
    return run_dir(home) / "owner.lock"


def spawn_lock_path(home) -> Path:
    return run_dir(home) / "spawn.lock"


def token_path(home) -> Path:
    return run_dir(home) / "token"


def pid_path(home) -> Path:
    return run_dir(home) / "owner.pid"


def log_path(home) -> Path:
    return run_dir(home) / "owner.log"
