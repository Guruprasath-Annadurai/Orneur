"""Data-directory locks that keep a restore and a running server from overlapping. Standard library only (imported by the server at start-up).

* every server process holds a SHARED lock on ``<data dir>/.server.lock`` for its life (``serving_lock``);
* a restore (or an offline import) holds an EXCLUSIVE ``.<name>.restore.lock`` beside the data directory, then an EXCLUSIVE ``.server.lock`` inside it
  (``exclusive_data_dir``): it refuses while any server is up, and a server refuses to start while a restore holds the directory.
Advisory ``flock`` on a local filesystem: not reliable across NFS; a process started without this lock (an older version) is not detected.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import stat
from pathlib import Path

from orca.serve.backup_errors import RestoreFailed

JOURNAL = ".restore-journal.json"


def restore_pending(home: Path) -> bool:
    """True when an earlier restore did not finish. The data directory must not be served until ``recover_interrupted`` has run."""
    return (Path(home) / JOURNAL).exists()


def restore_lock_path(home: Path) -> Path:
    home = Path(home)
    return home.parent / f".{home.name}.restore.lock"


@contextlib.contextmanager
def flock(path: Path, mode: int, busy: str, *, create: bool = True):
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    else:
        try:
            fd = os.open(str(path), os.O_RDONLY)                    # read-only probe: a lock file that does not exist means no server ever held this directory
        except FileNotFoundError:
            yield
            return
    try:
        try:
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
        except OSError:
            raise RestoreFailed(busy) from None
        yield
    finally:
        os.close(fd)                                              # closing releases the lock


@contextlib.contextmanager
def exclusive_data_dir(home: Path):
    """Held by a restore (or an offline import) for its whole run."""
    home = Path(home)
    with flock(restore_lock_path(home), fcntl.LOCK_EX, "another restore is in progress for this data directory"):
        if home.exists():
            with flock(home / ".server.lock", fcntl.LOCK_EX, "a server is running on this data directory: stop it before restoring"):
                yield
        else:
            yield


@contextlib.contextmanager
def serving_lock(home: Path):
    """Held by every server process for its lifetime."""
    home = Path(home)
    with flock(restore_lock_path(home), fcntl.LOCK_SH, "a restore is in progress for this data directory: the server will not start"):
        pass                                                      # a momentary check only: holding it for life would make every restore report "another restore" instead of "a server is running"
    with flock(home / ".server.lock", fcntl.LOCK_SH, "a restore is in progress for this data directory: the server will not start"):
        yield


# ── recovery journal ─────────────────────────────────────────────────────────────────────────────────────────────────────────

_NAME = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]{0,200}$")
_ASIDE = re.compile(r"^\.pre-restore-[0-9a-f]{10}$")


def _load_journal(home: Path) -> dict:
    """Read and VALIDATE the journal. It is trusted input for deletions and moves, so anything unexpected stops recovery and leaves the directory flagged."""
    jp = home / JOURNAL
    try:
        st = jp.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
            raise ValueError("not a private regular file owned by this user")
        j = json.loads(jp.read_text())
        if not isinstance(j, dict) or not isinstance(j.get("aside"), str) or not _ASIDE.match(j["aside"]):
            raise ValueError("bad holding directory")
        for k in ("moved", "placed"):
            if not isinstance(j.get(k), list) or not all(isinstance(n, str) and _NAME.match(n) and n not in (".", "..") for n in j[k]):
                raise ValueError(f"bad {k} list")
        aside = home / j["aside"]
        if aside.is_symlink() or (aside.exists() and not aside.is_dir()):
            raise ValueError("holding directory is not a directory")
        return j
    except (OSError, ValueError, TypeError) as exc:
        raise RestoreFailed(f"restore journal is invalid ({exc}); nothing was changed - inspect {jp} and the .pre-restore-* directory by hand") from None


def write_journal(home: Path, state: dict) -> None:
    tmp = home / (JOURNAL + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, home / JOURNAL)


def recover_interrupted(home: Path) -> dict:
    """Roll back a restore that was interrupted mid-swap: put every moved-aside original back and remove anything the restore had placed. Idempotent. Refuses (and keeps the
    directory flagged) when the journal is not exactly what a restore writes."""
    home = Path(home)
    (home / (JOURNAL + ".tmp")).unlink(missing_ok=True)           # a crash while writing the journal itself leaves only this temporary file
    if not (home / JOURNAL).exists():
        return {"recovered": False}
    j = _load_journal(home)
    aside = home / j["aside"]
    for name in j["placed"]:
        tgt = home / name
        if tgt.is_symlink():
            tgt.unlink()
        elif tgt.is_dir():
            shutil.rmtree(tgt, ignore_errors=True)
        else:
            tgt.unlink(missing_ok=True)
    for name in j["moved"]:
        src = aside / name
        if src.exists() or src.is_symlink():
            os.replace(src, home / name)
    shutil.rmtree(aside, ignore_errors=True)
    (home / JOURNAL).unlink(missing_ok=True)
    return {"recovered": True, "rolled_back": len(j["moved"])}
