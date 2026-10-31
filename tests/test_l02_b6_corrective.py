"""L02-B6 corrective -- the legacy backup/restore bypass, the deletion ledger under attack, journal validation, restored-file permissions, concurrent restores and a
running server. Written BEFORE the fix; the failing run on b1c56b9 is preserved in docs/orneur/landmarks/landmark-02/b6-backup-privacy/evidence/.

Honest framing used throughout: the ledger is an ordinary editable file. These tests prove what the code CAN detect (edits, removals, truncation relative to something
recorded elsewhere, forgery by naive edits, cross-lineage exports) and pin down what it CANNOT (a consistent rewrite by someone with write access, or entries removed after
the last off-host copy). They never assert tamper-proofness.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path

import pytest

from orca.serve import backup, deletion_ledger as ledger
from tests.test_l02_b6_backup import (CANARY_EMAIL, CANARY_TEXT, _commit, _populated_target, _rows, _snapshot, _tomb, key, other_key, world)  # noqa: F401


def _mk(world, tmp_path, key, name="bk.orbk"):
    out = tmp_path / name
    backup.create(world.home, out, key=key)
    return out


# ═══ A. legacy entry points fail closed ═══════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def legacy_env(tmp_path, monkeypatch):
    from orca.ops import backup as legacy

    auth_db = tmp_path / "live" / "auth.db"
    auth_db.parent.mkdir()
    c = sqlite3.connect(str(auth_db))
    c.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
    c.execute("INSERT INTO users VALUES ('u-victim', ?)", (CANARY_EMAIL,))
    c.commit()
    c.close()
    bdir = tmp_path / "backups"
    bdir.mkdir()
    monkeypatch.setattr(legacy, "AUTH_DB", auth_db)
    monkeypatch.setattr(legacy, "BACKUP_DIR", bdir)
    monkeypatch.setattr(legacy, "BACKEND", "sqlite")
    return legacy, auth_db, bdir


def test_every_legacy_programmatic_entry_point_refuses_and_writes_nothing(legacy_env):
    legacy, auth_db, bdir = legacy_env
    for call in (legacy.backup_sqlite, legacy.run_backup, lambda: legacy.backup_postgres("postgresql://x/y"), lambda: legacy.restore_sqlite(str(auth_db), confirm=True)):
        with pytest.raises(backup.BackupError, match="data-backup"):
            call()
    assert list(bdir.iterdir()) == []


def test_the_legacy_cli_commands_refuse_and_point_to_the_secure_ones(legacy_env):
    from typer.testing import CliRunner

    from orca.cli import app

    legacy, auth_db, bdir = legacy_env
    runner = CliRunner()
    for args in (["backup"], ["backup", "--no-prune", "--keep", "3"], ["restore", str(auth_db), "--yes"]):
        r = runner.invoke(app, args)
        assert r.exit_code == 1 and "data-backup" in r.output, (args, r.output)
    assert list(bdir.iterdir()) == []
    assert runner.invoke(app, ["backups"]).exit_code == 0           # listing existing files is read-only and stays available


def test_a_legacy_restore_cannot_resurrect_a_deleted_account(legacy_env):
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
    with pytest.raises(backup.BackupError):
        legacy.restore_sqlite(str(old), confirm=True)
    c = sqlite3.connect(str(auth_db))
    try:
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    finally:
        c.close()


def test_listing_and_pruning_legacy_backups_still_work_so_they_can_be_retired(legacy_env):
    legacy, auth_db, bdir = legacy_env
    for i in range(5):
        (bdir / f"auth_backup_2020010{i}T000000Z.db").write_bytes(b"x" * (i + 1))
    assert len(legacy.list_backups()) == 5
    assert legacy.prune_old_backups(keep_last_n=2)["deleted_count"] == 3


# ═══ B. offline migration of pre-existing plaintext backups ═════════════════════════════════════════════════════════════════════

def _legacy_file(tmp_path, with_deleted_user=True):
    p = tmp_path / "legacy" / "auth_backup_20200101T000000Z.db"
    p.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
    c.execute("INSERT INTO users VALUES ('u-old', 'old@example.com')")
    c.execute("INSERT INTO users VALUES ('u-gone', ?)", (CANARY_EMAIL,))
    c.commit()
    c.close()
    return p


def test_import_legacy_wraps_a_plaintext_backup_into_an_encrypted_archive_without_touching_any_live_directory(world, tmp_path, key):
    legacy = _legacy_file(tmp_path)
    out = tmp_path / "migrated" / "legacy.orbk"
    live_before = _snapshot(world.home)
    r = backup.import_legacy(legacy, out, key=key, live_home=world.home)
    assert out.exists() and r["origin"] == "legacy_plaintext_import" and CANARY_EMAIL.encode() not in out.read_bytes()
    assert _snapshot(world.home) == live_before, "the live data directory is never read or written by the migration"
    assert backup.verify(out, key=key)["ok"] is True and legacy.exists(), "the plaintext original is left for the operator to destroy deliberately"


def test_import_legacy_is_offline_only(world, tmp_path, key):
    legacy = _legacy_file(tmp_path)
    inside = world.home / "legacy.db"
    inside.write_bytes(legacy.read_bytes())
    with pytest.raises(backup.BackupError, match="outside the live"):
        backup.import_legacy(inside, tmp_path / "o.orbk", key=key, live_home=world.home)               # source inside the live directory
    with pytest.raises(backup.BackupError, match="outside the live"):
        backup.import_legacy(legacy, world.home / "o.orbk", key=key, live_home=world.home)             # output inside the live directory
    fd = os.open(str(world.home / ".server.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_SH)                                                                     # a server is running
    try:
        with pytest.raises(backup.BackupError, match="server"):
            backup.import_legacy(legacy, tmp_path / "o2.orbk", key=key, live_home=world.home)
    finally:
        os.close(fd)
    for bad in (b"", b"not a database" * 100):
        junk = tmp_path / "junk.db"
        junk.write_bytes(bad)
        with pytest.raises(backup.BackupError):
            backup.import_legacy(junk, tmp_path / "o3.orbk", key=key, live_home=world.home)
    assert not (tmp_path / "o3.orbk").exists()


def test_a_migrated_legacy_archive_still_cannot_restore_without_deletion_history_and_still_re_applies_deletions(world, tmp_path, key):
    legacy = _legacy_file(tmp_path)
    out = tmp_path / "legacy.orbk"
    backup.import_legacy(legacy, out, key=key, live_home=None)
    with pytest.raises(backup.DeletionHistoryUnavailable):
        backup.restore(out, tmp_path / "fresh", key=key)
    ledger.record("user", "u-gone", "u-gone", home=world.home)
    export = tmp_path / "exp.json"
    time.sleep(0.02)
    ledger.export(world.home, export, key)
    r = backup.restore(out, tmp_path / "fresh", key=key, deletion_ledger=export)
    c = sqlite3.connect(str(tmp_path / "fresh" / "auth.db"))
    try:
        assert [x[0] for x in c.execute("SELECT id FROM users")] == ["u-old"] and r["deletions_applied"]["user"] == 1
    finally:
        c.close()
    assert CANARY_EMAIL.encode() not in (tmp_path / "fresh" / "auth.db").read_bytes()


def test_an_export_taken_before_the_import_cannot_cover_it(world, tmp_path, key):
    export = tmp_path / "early.json"
    ledger.export(world.home, export, key)
    time.sleep(0.02)
    out = tmp_path / "legacy.orbk"
    backup.import_legacy(_legacy_file(tmp_path), out, key=key, live_home=None)
    with pytest.raises(backup.DeletionHistoryUnavailable, match="older"):
        backup.restore(out, tmp_path / "fresh", key=key, deletion_ledger=export)


# ═══ C. the ledger under attack ═══════════════════════════════════════════════════════════════════════════════════════════════

def _setup_deleted(world, tmp_path, key):
    from orca.serve import deletions

    world.commit("s-a", world.ua.id)
    out = _mk(world, tmp_path, key)
    deletions.begin("s-a", world.ua.id)                              # deleted after the backup
    deletions.run("s-a", world.ua.id)
    return out


def test_removing_the_ledger_then_backing_up_again_does_not_make_an_empty_history_look_authoritative(world, tmp_path, key):
    old = _setup_deleted(world, tmp_path, key)
    ledger.path(world.home).unlink()
    backup.create(world.home, tmp_path / "newer.orbk", key=key)
    with pytest.raises(backup.BackupError):
        backup.restore(old, world.home, key=key, overwrite=True)
    assert _rows(world.home, "s-a") == 0


def test_a_ledger_truncated_to_nothing_or_to_garbage_is_refused_not_trusted(world, tmp_path, key):
    old = _setup_deleted(world, tmp_path, key)
    for content in ("", "\n", "garbage\n", "{}\n", '{"kind":"session","id":"x"}\n'):
        ledger.path(world.home).write_text(content)
        with pytest.raises(backup.BackupError):
            backup.restore(old, world.home, key=key, overwrite=True)
    assert _rows(world.home, "s-a") == 0


def test_a_forged_unchained_line_is_rejected_instead_of_being_applied(world, tmp_path, key):
    world.commit("s-b", world.ub.id, "B's note")
    out = _mk(world, tmp_path, key)
    with open(ledger.path(world.home), "a") as f:
        f.write(json.dumps({"at": time.time(), "kind": "session", "id": "s-b", "user_id": world.ub.id, "session_id": "s-b"}) + "\n")    # naive forgery: delete B's conversation
    with pytest.raises(backup.BackupError):
        backup.restore(out, world.home, key=key, overwrite=True)
    assert _rows(world.home, "s-b") == 1, "nothing was applied"


def test_editing_removing_or_reordering_a_middle_entry_breaks_the_chain(world, tmp_path, key):
    for i in range(4):
        ledger.record("session", f"s{i}", "u", f"s{i}", home=world.home)
    lines = ledger.path(world.home).read_text().splitlines()
    assert len(lines) == 5                                           # genesis + 4
    original = "\n".join(lines) + "\n"
    for variant in (lines[:2] + lines[3:], lines[:2] + [lines[3], lines[2]] + lines[4:], lines[:2] + [lines[2].replace('"s1"', '"s9"')] + lines[3:]):
        ledger.path(world.home).write_text("\n".join(variant) + "\n")
        with pytest.raises(ledger.LedgerIntegrityError):
            ledger.read(world.home)
    ledger.path(world.home).write_text(original)
    assert len(ledger.read(world.home)) == 4


def test_a_live_ledger_that_is_shorter_than_an_export_is_treated_as_truncated(world, tmp_path, key):
    ledger.record("session", "s-1", "u", "s-1", home=world.home)
    out = _mk(world, tmp_path, key)
    ledger.record("session", "s-2", "u", "s-2", home=world.home)
    ledger.record("session", "s-3", "u", "s-3", home=world.home)
    time.sleep(0.02)
    export = tmp_path / "exp.json"
    ledger.export(world.home, export, key)                           # an off-host copy that knows s-2 and s-3
    lines = ledger.path(world.home).read_text().splitlines()
    ledger.path(world.home).write_text("\n".join(lines[:2]) + "\n")  # attacker cuts the live file back to a VALID prefix
    with pytest.raises(backup.BackupError, match="truncated|behind|fork"):
        backup.restore(out, world.home, key=key, deletion_ledger=export, overwrite=True)


def test_an_export_from_another_ledger_lineage_is_refused(world, tmp_path, key):
    ledger.record("session", "s-1", "u", "s-1", home=world.home)
    out = _mk(world, tmp_path, key)
    other = world.home.parent / "other-system"
    ledger.record("session", "s-1", "u", "s-1", home=other)
    time.sleep(0.02)
    export = tmp_path / "other.json"
    ledger.export(other, export, key)
    with pytest.raises(backup.BackupError, match="lineage"):
        backup.restore(out, tmp_path / "fresh", key=key, deletion_ledger=export)
    assert not (tmp_path / "fresh").exists()


def test_what_cannot_be_detected_is_reported_as_not_verified_never_as_complete(world, tmp_path, key):
    """A consistent rewrite, or entries removed after the last off-host copy, cannot be detected locally. The result must say so."""
    ledger.record("session", "s-1", "u", "s-1", home=world.home)
    out = _mk(world, tmp_path, key)
    r = backup.restore(out, world.home, key=key, overwrite=True)
    h = r["deletion_history"]
    assert h["completeness_verified"] is False and h["live_ledger_authenticated"] is False and h["off_host_anchor"] is False
    assert "NOT" in h["statement"].upper() and "tamper" in h["statement"].lower()
    export = tmp_path / "exp.json"
    time.sleep(0.02)
    ledger.export(world.home, export, key)
    r2 = backup.restore(out, tmp_path / "fresh", key=key, deletion_ledger=world.home and export)
    assert r2["deletion_history"]["completeness_verified"] is False and r2["deletion_history"]["export_generated_at"] > 0


def test_ledger_entries_chain_and_survive_concurrent_appends(tmp_path):
    home = tmp_path / "h"
    threads = [threading.Thread(target=lambda i=i: [ledger.record("session", f"s{i}-{n}", "u", home=home) for n in range(20)]) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ledger.read(home)) == 120
    info = ledger.chain_info(home)
    assert info["count"] == 121 and len(info["head"]) == 64 and info["ledger_id"]


# ═══ D. recovery journal, permissions, concurrency, running server ═════════════════════════════════════════════════════════════

def test_a_tampered_journal_cannot_make_recovery_delete_or_move_anything_outside_the_data_directory(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("precious")
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.db").write_text("live")
    for evil in ({"aside": ".pre-restore-aaaaaaaaaa", "moved": [], "placed": ["../victim"]},
                 {"aside": ".pre-restore-aaaaaaaaaa", "moved": ["../victim"], "placed": []},
                 {"aside": "../victim", "moved": [], "placed": []},
                 {"aside": ".pre-restore-aaaaaaaaaa", "moved": ["/etc"], "placed": []},
                 {"aside": ".pre-restore-aaaaaaaaaa", "moved": ["a/b"], "placed": []},
                 {"aside": ".pre-restore-aaaaaaaaaa", "moved": [".."], "placed": []},
                 {"aside": ".pre-restore-aaaaaaaaaa", "moved": [], "placed": [str(victim)]},
                 {"aside": 5, "moved": "x", "placed": None}, [], "just a string"):
        (home / backup.JOURNAL).write_text(json.dumps(evil))
        with pytest.raises(backup.RestoreFailed, match="journal"):
            backup.recover_interrupted(home)
        assert (victim / "keep.txt").read_text() == "precious" and (home / "auth.db").read_text() == "live"
        assert backup.restore_pending(home), "an invalid journal stays pending: the directory is not declared healthy"
    (home / backup.JOURNAL).write_text("{ not json")
    with pytest.raises(backup.RestoreFailed, match="journal"):
        backup.recover_interrupted(home)


def test_a_symlink_in_place_of_a_restored_entry_is_unlinked_not_followed(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("precious")
    home = tmp_path / "home"
    aside = home / ".pre-restore-bbbbbbbbbb"
    aside.mkdir(parents=True)
    (home / "docs").symlink_to(victim)
    (home / backup.JOURNAL).write_text(json.dumps({"aside": ".pre-restore-bbbbbbbbbb", "moved": [], "placed": ["docs"]}))
    backup.recover_interrupted(home)
    assert (victim / "keep.txt").read_text() == "precious" and not (home / "docs").exists()


def test_restored_files_and_directories_are_private(world, tmp_path, key):
    world.commit("s-a", world.ua.id)
    for p in world.home.rglob("*"):
        if p.is_file():
            p.chmod(0o666)
    out = _mk(world, tmp_path, key)
    ledger.ensure(world.home)
    fresh = tmp_path / "fresh"
    backup.restore(out, fresh, key=key, unsafe_without_deletion_history=True)
    loose = [str(p.relative_to(fresh)) for p in fresh.rglob("*") if (p.is_file() and p.stat().st_mode & 0o077) or (p.is_dir() and p.stat().st_mode & 0o077)]
    assert not loose and (fresh.stat().st_mode & 0o777) == 0o700, loose
    target = _populated_target(world, tmp_path)
    backup.restore(out, target, key=key, overwrite=True)
    loose = [str(p.relative_to(target)) for p in target.rglob("*") if ".pre-restore" not in str(p) and p.stat().st_mode & 0o077 and p != target]
    assert not [x for x in loose if not x.startswith(("vault", "extra-live.txt"))], loose          # untouched live files keep the operator's modes


def test_two_concurrent_restores_into_the_same_target_cannot_interleave(world, tmp_path, key, monkeypatch):
    ledger.ensure(world.home)
    out = _mk(world, tmp_path, key)
    target = _populated_target(world, tmp_path)
    entered, release = threading.Event(), threading.Event()
    real = backup._health_check

    def slow(root, entries):
        entered.set()
        release.wait(20)
        return real(root, entries)

    monkeypatch.setattr(backup, "_health_check", slow)
    results = {}

    def first():
        try:
            results["first"] = backup.restore(out, target, key=key, overwrite=True)
        except Exception as exc:
            results["first"] = exc

    t = threading.Thread(target=first)
    t.start()
    assert entered.wait(20)
    with pytest.raises(backup.RestoreFailed, match="in progress"):
        backup.restore(out, target, key=key, overwrite=True)
    release.set()
    t.join(30)
    assert isinstance(results["first"], dict), results
    assert not backup.restore_pending(target)


def test_a_restore_refuses_while_a_server_is_running_and_a_server_refuses_to_start_during_a_restore(world, tmp_path, key):
    ledger.ensure(world.home)
    out = _mk(world, tmp_path, key)
    target = _populated_target(world, tmp_path)
    fd = os.open(str(target / ".server.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_SH)                                   # what a running server holds
    before = _snapshot(target)
    try:
        with pytest.raises(backup.RestoreFailed, match="server"):
            backup.restore(out, target, key=key, overwrite=True)
    finally:
        os.close(fd)
    assert _snapshot(target) == before
    with backup.exclusive_data_dir(target):                          # what a restore holds during the swap
        with pytest.raises(backup.RestoreFailed, match="restore"):
            with backup.serving_lock(target):
                pass
    with backup.serving_lock(target):                                # and a normal start is fine
        with pytest.raises(backup.RestoreFailed, match="server"):
            with backup.exclusive_data_dir(target):
                pass


def test_the_application_takes_the_serving_lock_on_startup(isolated_home, monkeypatch):
    from fastapi.testclient import TestClient

    from orca.config import ORCA_HOME
    from orca.serve import streaming
    from orca.serve.api import app

    # leaving the application's lifespan shuts the process-wide streaming pool down (correct for a server, fatal for the rest of the test session)
    monkeypatch.setattr(streaming, "shutdown_streaming_pool", lambda wait=False: None)

    lock = Path(ORCA_HOME) / ".server.lock"
    with TestClient(app):
        fd = os.open(str(lock), os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)      # a restore could not start now
        finally:
            os.close(fd)


def test_the_serving_lock_and_journal_files_are_not_part_of_a_backup(world, tmp_path, key):
    (world.home / ".server.lock").write_text("")
    out = _mk(world, tmp_path, key)
    manifest = backup._extract(out, key, tmp_path / "stage")
    assert ".server.lock" not in manifest["files"]
