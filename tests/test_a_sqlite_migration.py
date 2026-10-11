"""Workstream A -- SQLite upgrade from the pre-G-006 schema: data preserved, automatic pre-migration backup, idempotence, and a tested rollback."""
from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parent / "fixtures" / "legacy_auth_schema_pre_g006_sqlite.sql"
NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("ORNEUR_HOME", str(home))
    monkeypatch.delenv("ORCA_HOME", raising=False)
    monkeypatch.delenv("ORNEUR_DATABASE_URL", raising=False)
    monkeypatch.delenv("ORCA_DATABASE_URL", raising=False)
    path = home / "auth.db"
    con = sqlite3.connect(path)
    con.executescript(FIX.read_text())
    con.execute("INSERT INTO users (id,email,name,password_hash,tier,role,created_at,signup_seq) VALUES ('o1','o@example.com','o','h','free','owner',?,1)", (NOW,))
    con.execute("INSERT INTO users (id,email,name,password_hash,tier,role,created_at,signup_seq) VALUES ('u1','u@example.com','u','h','pro','member',?,2)", (NOW,))
    con.execute("INSERT INTO user_sessions (user_id,session_id,created_at) VALUES ('o1','dup',?)", ("2026-01-01T00:00:01+00:00",))
    con.execute("INSERT INTO user_sessions (user_id,session_id,created_at) VALUES ('u1','dup',?)", ("2026-01-01T00:00:09+00:00",))
    con.execute("INSERT INTO user_sessions (user_id,session_id,created_at) VALUES ('u1','solo',?)", (NOW,))
    con.commit()
    con.close()
    return path


def _upgrade(path, monkeypatch):
    import importlib

    import orca.auth.db as db
    monkeypatch.setattr(db, "AUTH_DB", path)
    db.init_db()
    return db


def test_upgrade_preserves_every_legacy_row_and_collapses_duplicate_owners(legacy_db, monkeypatch):
    _upgrade(legacy_db, monkeypatch)
    con = sqlite3.connect(legacy_db)
    assert {r[0]: r[1] for r in con.execute("SELECT id, role FROM users")} == {"o1": "owner", "u1": "member"}
    assert [r[0] for r in con.execute("SELECT user_id FROM user_sessions WHERE session_id='dup'")] == ["o1"]      # earliest claim wins
    assert con.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0] == 2
    assert con.execute("SELECT owner_user_id, method FROM owner_bootstrap WHERE id=1").fetchone() == ("o1", "legacy_existing_owner")
    assert con.execute("SELECT tokens_valid_after FROM users WHERE id='u1'").fetchone()[0] == 0


def test_an_automatic_private_backup_is_taken_before_the_first_migration(legacy_db, monkeypatch):
    _upgrade(legacy_db, monkeypatch)
    backups = sorted(legacy_db.parent.glob("auth.db.pre-migration-*.bak"))
    assert len(backups) == 1 and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    con = sqlite3.connect(backups[0])
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "owner_bootstrap" not in tables and "session_storage_keys" not in tables         # the backup is the PRE-migration state
    assert con.execute("SELECT COUNT(*) FROM user_sessions WHERE session_id='dup'").fetchone()[0] == 2    # duplicates intact in the backup
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_the_migration_is_idempotent_and_does_not_take_a_second_backup(legacy_db, monkeypatch):
    db = _upgrade(legacy_db, monkeypatch)
    db.init_db()
    db.init_db()
    assert len(list(legacy_db.parent.glob("auth.db.pre-migration-*.bak"))) == 1
    con = sqlite3.connect(legacy_db)
    assert con.execute("SELECT COUNT(*) FROM owner_bootstrap").fetchone()[0] == 1


def test_a_fresh_install_takes_no_backup(tmp_path, monkeypatch):
    home = tmp_path / "fresh"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("ORNEUR_HOME", str(home))
    monkeypatch.delenv("ORCA_HOME", raising=False)
    monkeypatch.delenv("ORNEUR_DATABASE_URL", raising=False)
    monkeypatch.delenv("ORCA_DATABASE_URL", raising=False)
    _upgrade(home / "auth.db", monkeypatch)
    assert list(home.glob("auth.db.pre-migration-*.bak")) == []


def test_rollback_is_restoring_the_backup_and_the_previous_release_queries_work_on_it(legacy_db, monkeypatch):
    _upgrade(legacy_db, monkeypatch)
    backup = next(legacy_db.parent.glob("auth.db.pre-migration-*.bak"))
    restored = legacy_db.parent / "restored.db"
    restored.write_bytes(backup.read_bytes())
    con = sqlite3.connect(restored)
    # the statements the previous release issues
    con.execute("INSERT INTO users (id,email,name,password_hash,tier,role,created_at,signup_seq) VALUES ('n1','n@example.com','n','h','free','member',?,3)", (NOW,))
    assert con.execute("SELECT id,email,name,password_hash,tier,role,created_at,verified,stripe_customer_id,totp_secret,totp_enabled,signup_seq FROM users WHERE email='n@example.com'").fetchone()[0] == "n1"
    assert con.execute("SELECT user_id FROM user_sessions WHERE session_id='solo'").fetchone()[0] == "u1"


def test_the_new_release_can_re_upgrade_a_restored_backup(legacy_db, monkeypatch, tmp_path):
    _upgrade(legacy_db, monkeypatch)
    backup = next(legacy_db.parent.glob("auth.db.pre-migration-*.bak"))
    again = legacy_db.parent / "again.db"
    again.write_bytes(backup.read_bytes())
    db = _upgrade(again, monkeypatch)
    con = sqlite3.connect(again)
    assert con.execute("SELECT COUNT(*) FROM owner_bootstrap").fetchone()[0] == 1 and len(list(again.parent.glob("again.db.pre-migration-*.bak"))) == 1


def test_the_previous_releases_data_works_with_the_new_code_end_to_end(legacy_db, monkeypatch):
    """Not just schema: login, session ownership and the bootstrap guard behave on migrated legacy data."""
    db = _upgrade(legacy_db, monkeypatch)
    import orca.auth.store as store
    monkeypatch.setattr(store, "get_conn", db.get_conn)
    assert store.get_user_by_email("u@example.com").tier == "pro"
    assert store.claim_session("dup", "o1") is True and store.claim_session("dup", "u1") is False
    from orca.auth import bootstrap
    monkeypatch.setattr(bootstrap, "get_conn", db.get_conn)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.issue_token("new-owner@example.com")                # an install that already has an owner can never be taken over
