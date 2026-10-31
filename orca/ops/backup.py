"""
RETIRED FOR CREATION AND RESTORE (L02-B6). ``backup_sqlite``, ``backup_postgres``, ``run_backup`` and ``restore_sqlite`` now refuse: they produced unencrypted copies of the
accounts database and restored one without consulting deletion history. Use ``orca data-backup`` (orca/serve/backup.py). ``list_backups`` / ``prune_old_backups`` remain so that
existing plaintext files can be found, migrated offline (``orca data-backup import-legacy``) and destroyed.

Original description (historical):

Automated backup / disaster recovery — real gap this closes: SQLite/Postgres
had ZERO backup automation. One bad `rm`, disk failure, or corrupted write
loses the auth DB (users, audit log, everything) with no way back.

HONEST SCOPE:
  - This is a backup/prune tool, meant to be invoked by an external
    scheduler (cron, systemd timer, a scheduled CI job) — it does NOT
    schedule itself inside the running server process. That's deliberate:
    an in-process scheduler dies when the process dies/restarts/crashes,
    which is exactly when you most need backups to keep running. Standard
    ops practice is external scheduling; this tool is the thing THAT gets
    scheduled, not a scheduler itself.
  - SQLite backup uses sqlite3's own online backup API (Connection.backup()),
    not a raw file copy — a raw `cp` of a live SQLite file (especially in
    WAL mode, which orca/auth/db.py uses) can capture a half-written,
    inconsistent state. The backup API produces a consistent snapshot even
    while the source DB is being actively written to.
  - Postgres backup shells out to `pg_dump` — requires it installed on the
    machine running the backup (checked explicitly, raises a clear error
    if missing rather than silently producing an empty/broken dump).
  - Restore is documented and provided for SQLite (the common single-user
    case — copy the backup file back over the live DB). Postgres restore
    uses standard `pg_restore`/`psql < dump.sql` — documented, not
    reimplemented, since re-inventing Postgres's own restore tooling would
    be needless risk for something Postgres already does correctly.
"""
from __future__ import annotations

import itertools
import shutil
import sqlite3
import subprocess
import time
from typing import NoReturn
from pathlib import Path

from orca.config import ORCA_HOME, orneur_env
from orca.auth.db import AUTH_DB, BACKEND

BACKUP_DIR = ORCA_HOME / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _unique_backup_path(prefix: str, suffix: str) -> Path:
    """
    Real bug this fixes: the previous timestamp format had only
    second-level resolution — two backups created within the same second
    silently overwrote each other, with no error or warning. Worse, inside
    restore_sqlite(), the "safety backup of the current state" this creates
    could collide with and destroy the very backup file being restored
    from, if both happened within the same second — defeating the entire
    safety mechanism. Guarantees a unique path by appending a counter if
    the timestamped name is already taken.
    """
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base = BACKUP_DIR / f"{prefix}_{ts}{suffix}"
    if not base.exists():
        return base
    for i in itertools.count(1):
        candidate = BACKUP_DIR / f"{prefix}_{ts}-{i}{suffix}"
        if not candidate.exists():
            return candidate


_REFUSAL = ("the legacy plaintext backup/restore is retired (L02-B6): it wrote an UNENCRYPTED copy of the accounts database and restored one over the live database without "
            "consulting deletion history, which could bring back accounts customers had deleted. Use `orca data-backup create|verify|restore` with a provisioned key "
            "(docs/orneur/landmarks/landmark-02/b6-backup-privacy). To keep an existing plaintext backup, migrate it OFFLINE with `orca data-backup import-legacy`.")


def _refuse() -> "NoReturn":
    from orca.serve.backup_crypto import BackupError

    raise BackupError(_REFUSAL)


def backup_sqlite() -> Path:
    """RETIRED: refuses. See ``_REFUSAL``."""
    _refuse()


def backup_postgres(database_url: str) -> Path:
    """RETIRED: refuses (a ``pg_dump`` is an unencrypted copy of every account and bypasses deletion history on restore). See ``_REFUSAL``."""
    _refuse()


def run_backup() -> dict:
    """RETIRED: refuses. See ``_REFUSAL``."""
    _refuse()


def list_backups() -> list[dict]:
    backups = []
    for path in sorted(BACKUP_DIR.glob("auth_backup_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        backups.append({
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
        })
    return backups


def prune_old_backups(keep_last_n: int = 7) -> dict:
    """Deletes backups beyond the retention count, oldest first. Never deletes the backup just created this run."""
    backups = list_backups()  # already sorted newest-first
    to_delete = backups[keep_last_n:]

    deleted = []
    for b in to_delete:
        try:
            Path(b["path"]).unlink()
            deleted.append(b["path"])
        except Exception:
            pass  # a failed delete of an old backup isn't worth failing the whole prune run over

    return {"kept": min(len(backups), keep_last_n), "deleted": deleted, "deleted_count": len(deleted)}


def restore_sqlite(backup_path: str, confirm: bool = False) -> dict:
    """RETIRED: refuses. A plaintext restore over the live accounts database could resurrect deleted accounts and cannot verify integrity or completeness. See ``_REFUSAL``."""
    _refuse()
