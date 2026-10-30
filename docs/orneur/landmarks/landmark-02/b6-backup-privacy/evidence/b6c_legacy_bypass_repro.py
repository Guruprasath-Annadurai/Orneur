"""L02-B6 corrective -- reproduction of the LEGACY backup/restore bypass on the PR #143 candidate (ba36e74 / b1c56b9), before any fix.

`orca/ops/backup.py` + the legacy CLI (`orca backup`, `orca restore`) still produce plaintext copies of the accounts database and restore one over the live database
without consulting deletion history. Each test asserts the SECURE property and is expected to FAIL while the bypass exists. Synthetic accounts only.
Run (copy into tests/ so conftest fixtures apply):  pytest tests/b6c_legacy_bypass_repro.py -p no:cacheprovider -v
"""
from __future__ import annotations

import sqlite3
import time

import pytest

CANARY_EMAIL = "legacy-canary-customer-31337@example.com"


@pytest.fixture
def legacy_env(tmp_path, monkeypatch):
    from orca.ops import backup as legacy

    auth_db = tmp_path / "live" / "auth.db"
    auth_db.parent.mkdir()
    c = sqlite3.connect(str(auth_db))
    c.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
    c.execute("INSERT INTO users VALUES ('u-victim', ?)", (CANARY_EMAIL,))
    c.execute("INSERT INTO users VALUES ('u-other', 'other@example.com')")
    c.commit()
    c.close()
    bdir = tmp_path / "backups"
    bdir.mkdir()
    monkeypatch.setattr(legacy, "AUTH_DB", auth_db)
    monkeypatch.setattr(legacy, "BACKUP_DIR", bdir)
    monkeypatch.setattr(legacy, "BACKEND", "sqlite")
    return legacy, auth_db, bdir


def _emails(db):
    c = sqlite3.connect(str(db))
    try:
        return {r[0] for r in c.execute("SELECT email FROM users")}
    finally:
        c.close()


def test_L1_the_legacy_programmatic_backup_does_not_write_customer_data_in_plaintext(legacy_env):
    legacy, auth_db, bdir = legacy_env
    try:
        legacy.run_backup()
    except Exception:
        pass                                                      # refusing is the secure outcome
    assert not any(CANARY_EMAIL.encode() in p.read_bytes() for p in bdir.iterdir()), "plaintext customer email in a legacy backup file"


def test_L1b_the_legacy_cli_backup_command_does_not_write_a_plaintext_backup(legacy_env):
    from typer.testing import CliRunner

    from orca.cli import app

    legacy, auth_db, bdir = legacy_env
    r = CliRunner().invoke(app, ["backup", "--no-prune"])
    assert r.exit_code != 0 and not any(bdir.iterdir()), f"exit={r.exit_code}, files={[p.name for p in bdir.iterdir()]}"


def test_L2_the_legacy_restore_does_not_resurrect_an_account_deleted_after_the_backup(legacy_env):
    from orca.serve import deletion_ledger as ledger

    legacy, auth_db, bdir = legacy_env
    old = bdir / "auth_backup_20200101T000000Z.db"
    s, d = sqlite3.connect(str(auth_db)), sqlite3.connect(str(old))
    s.backup(d)
    s.close()
    d.close()
    time.sleep(0.01)
    c = sqlite3.connect(str(auth_db))                              # the customer deletes the account afterwards
    c.execute("DELETE FROM users WHERE id='u-victim'")
    c.commit()
    c.close()
    ledger.record("user", "u-victim", "u-victim", home=auth_db.parent)
    assert CANARY_EMAIL not in _emails(auth_db)
    try:
        legacy.restore_sqlite(str(old), confirm=True)
    except Exception:
        pass                                                      # refusing is the secure outcome
    assert CANARY_EMAIL not in _emails(auth_db), "the deleted account is back after a legacy restore"


def test_L2b_the_legacy_cli_restore_does_not_resurrect_a_deleted_account(legacy_env):
    from typer.testing import CliRunner

    from orca.cli import app
    from orca.serve import deletion_ledger as ledger

    legacy, auth_db, bdir = legacy_env
    old = bdir / "auth_backup_20200101T000000Z.db"
    s, d = sqlite3.connect(str(auth_db)), sqlite3.connect(str(old))
    s.backup(d)
    s.close()
    d.close()
    c = sqlite3.connect(str(auth_db))
    c.execute("DELETE FROM users WHERE id='u-victim'")
    c.commit()
    c.close()
    ledger.record("user", "u-victim", "u-victim", home=auth_db.parent)
    # the CLI imports AUTH_DB / BACKEND from the legacy module at call time, so the monkeypatched values apply
    import orca.auth.db as authdb

    authdb.BACKEND = "sqlite"
    CliRunner().invoke(app, ["restore", str(old), "--yes"])
    assert CANARY_EMAIL not in _emails(auth_db), "the deleted account is back after `orca restore`"
