"""
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


def test_backup_sqlite_produces_a_readable_consistent_snapshot(isolated_backup_env):
    auth_db, backup_dir = isolated_backup_env
    dest = backup_module.backup_sqlite()

    assert dest.exists()
    assert dest.parent == backup_dir
    assert _read_users(dest) == [(1, "real-user@example.com")]


def test_backup_sqlite_raises_clearly_when_no_db_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_module, "AUTH_DB", tmp_path / "does-not-exist.db")
    monkeypatch.setattr(backup_module, "BACKUP_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="nothing to back up"):
        backup_module.backup_sqlite()


def test_full_backup_then_restore_roundtrip_recovers_real_data(isolated_backup_env):
    """
    The actual end-to-end scenario this tool exists for: back up the live
    DB, simulate data loss (corrupt/wipe the live DB), restore from the
    backup, and confirm the real data comes back — not just that the
    functions return without raising.
    """
    auth_db, backup_dir = isolated_backup_env

    backup_path = backup_module.backup_sqlite()
    assert _read_users(auth_db) == [(1, "real-user@example.com")]

    # Simulate real data loss: wipe the live DB.
    conn = sqlite3.connect(str(auth_db))
    conn.execute("DELETE FROM users")
    conn.execute("INSERT INTO users (email) VALUES ('corrupted-state@example.com')")
    conn.commit()
    conn.close()
    assert _read_users(auth_db) == [(1, "corrupted-state@example.com")]

    result = backup_module.restore_sqlite(str(backup_path), confirm=True)

    assert _read_users(auth_db) == [(1, "real-user@example.com")]
    assert "pre_restore_backup" in result


def test_restore_sqlite_refuses_without_explicit_confirm(isolated_backup_env):
    auth_db, backup_dir = isolated_backup_env
    backup_path = backup_module.backup_sqlite()

    with pytest.raises(ValueError, match="confirm=True"):
        backup_module.restore_sqlite(str(backup_path), confirm=False)

    # Data must be untouched — the refusal must be a genuine no-op.
    assert _read_users(auth_db) == [(1, "real-user@example.com")]


def test_restore_sqlite_backs_up_the_about_to_be_overwritten_state_first(isolated_backup_env):
    """A bad restore choice must itself be recoverable — restoring must not
    be a second, irreversible data-loss event."""
    auth_db, backup_dir = isolated_backup_env
    original_backup = backup_module.backup_sqlite()

    conn = sqlite3.connect(str(auth_db))
    conn.execute("INSERT INTO users (email) VALUES ('second-user@example.com')")
    conn.commit()
    conn.close()

    pre_count = len(list(backup_dir.glob("auth_backup_*")))
    backup_module.restore_sqlite(str(original_backup), confirm=True)
    post_count = len(list(backup_dir.glob("auth_backup_*")))

    assert post_count == pre_count + 1  # the pre-restore safety backup was created


def test_restore_sqlite_raises_on_missing_backup_file(isolated_backup_env):
    with pytest.raises(FileNotFoundError):
        backup_module.restore_sqlite("/tmp/does-not-exist-anywhere.db", confirm=True)


def test_restore_sqlite_refuses_when_backend_is_not_sqlite(isolated_backup_env, monkeypatch):
    monkeypatch.setattr(backup_module, "BACKEND", "postgres")
    with pytest.raises(RuntimeError, match="not sqlite"):
        backup_module.restore_sqlite("/some/path.db", confirm=True)


def test_prune_old_backups_keeps_only_the_newest_n(isolated_backup_env):
    auth_db, backup_dir = isolated_backup_env
    for _ in range(10):
        backup_module.backup_sqlite()

    assert len(backup_module.list_backups()) == 10

    result = backup_module.prune_old_backups(keep_last_n=3)

    assert result["kept"] == 3
    assert result["deleted_count"] == 7
    assert len(backup_module.list_backups()) == 3


def test_prune_old_backups_never_deletes_more_than_exist(isolated_backup_env):
    backup_module.backup_sqlite()
    result = backup_module.prune_old_backups(keep_last_n=100)
    assert result["deleted_count"] == 0
    assert result["kept"] == 1


def test_list_backups_reports_real_file_sizes(isolated_backup_env):
    backup_module.backup_sqlite()
    backups = backup_module.list_backups()
    assert len(backups) == 1
    assert backups[0]["size_bytes"] > 0
