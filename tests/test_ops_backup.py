"""
L02-B6: creation and restore in orca/ops/backup.py are RETIRED (they wrote unencrypted copies of the accounts database and restored one without consulting deletion history);
the tests that exercised them now assert that every such entry point refuses and changes nothing. The full matrix is in tests/test_l02_b6_corrective.py. What remains here is the
read-only listing and the pruning that let an operator find and destroy pre-existing plaintext backups.

Original docstring:

Tests for orca/ops/backup.py — the disaster-recovery mechanism that had
zero test coverage despite being a genuinely destructive operation
(restore_sqlite overwrites the live database). "Backup/restore never
actually tested" was the honest status before this file existed — these
tests exercise the real code against real, isolated SQLite files, not
mocks, since a backup tool is exactly the kind of thing where "it probably
works" isn't good enough.
"""
from __future__ import annotations

import sqlite3

import pytest

from orca.ops import backup as backup_module


@pytest.fixture
def isolated_backup_env(tmp_path, monkeypatch):
    """Real SQLite files in an isolated temp dir — never touches the real
    production auth.db or backups directory."""
    auth_db = tmp_path / "auth.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    conn = sqlite3.connect(str(auth_db))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    conn.execute("INSERT INTO users (email) VALUES ('real-user@example.com')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(backup_module, "AUTH_DB", auth_db)
    monkeypatch.setattr(backup_module, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backup_module, "BACKEND", "sqlite")

    return auth_db, backup_dir


def _read_users(db_path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT id, email FROM users").fetchall()
    conn.close()
    return rows


def test_legacy_creation_and_restore_refuse_and_change_nothing(isolated_backup_env, monkeypatch):
    from orca.serve.backup_crypto import BackupError

    auth_db, backup_dir = isolated_backup_env
    for call in (backup_module.backup_sqlite, backup_module.run_backup, lambda: backup_module.backup_postgres("postgresql://x/y"),
                 lambda: backup_module.restore_sqlite(str(auth_db), confirm=True), lambda: backup_module.restore_sqlite("/tmp/does-not-exist.db", confirm=False)):
        with pytest.raises(BackupError, match="data-backup"):
            call()
    monkeypatch.setattr(backup_module, "BACKEND", "postgres")
    with pytest.raises(BackupError):
        backup_module.restore_sqlite("/some/path.db", confirm=True)
    assert list(backup_dir.iterdir()) == []
    assert _read_users(auth_db) == [(1, "real-user@example.com")]


def _seed(backup_dir, n):
    import os
    import time

    for i in range(n):
        p = backup_dir / f"auth_backup_2020010{i}T000000Z.db"
        p.write_bytes(b"legacy")
        os.utime(p, (time.time() - 1000 + i, time.time() - 1000 + i))


def test_prune_old_backups_keeps_only_the_newest_n(isolated_backup_env):
    auth_db, backup_dir = isolated_backup_env
    _seed(backup_dir, 10)
    assert len(backup_module.list_backups()) == 10
    result = backup_module.prune_old_backups(keep_last_n=3)
    assert result["kept"] == 3
    assert result["deleted_count"] == 7
    assert len(backup_module.list_backups()) == 3


def test_prune_old_backups_never_deletes_more_than_exist(isolated_backup_env):
    auth_db, backup_dir = isolated_backup_env
    _seed(backup_dir, 1)
    result = backup_module.prune_old_backups(keep_last_n=100)
    assert result["deleted_count"] == 0
    assert result["kept"] == 1


def test_list_backups_reports_real_file_sizes(isolated_backup_env):
    auth_db, backup_dir = isolated_backup_env
    _seed(backup_dir, 1)
    backups = backup_module.list_backups()
    assert len(backups) == 1
    assert backups[0]["size_bytes"] > 0
