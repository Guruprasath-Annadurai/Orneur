"""L02-B6 -- backup privacy and restoration safety (synthetic customer data only; test-only keys in a temp directory).

Negative-before-positive: the baseline behaviour is reproduced by docs/orneur/landmarks/landmark-02/b6-backup-privacy/evidence/b6_baseline_repro.py (8 of 8 fail on 38e0d31).
This file proves the replacement: encrypted+authenticated archives, fail-closed key handling, a deletion-aware restore that refuses without authoritative history, and a
restore that is all-or-nothing.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest

from orca.serve import backup, deletion_ledger as ledger
from orca.serve.backup import BackupAuthError, BackupIncompleteError, BackupKeyError, DeletionHistoryUnavailable, RestoreFailed
from orca.serve.backup_crypto import CHUNK, EncryptedWriter

CANARY_EMAIL = "canary-customer-7f3a@example.com"
CANARY_TEXT = "CANARY-SECRET-QUARTERLY-NUMBERS-91827"
CANARY_DOC = "CANARY-DOCUMENT-BODY-55501"


def _keyfile(tmp_path, name="k.key", mode=0o600) -> Path:
    d = tmp_path / "keys"
    d.mkdir(exist_ok=True)
    p = d / name
    backup.write_new_key(p) if not p.exists() else None
    p.chmod(mode)
    return p


@pytest.fixture
def key(tmp_path):
    return backup.load_key(_keyfile(tmp_path))


@pytest.fixture
def other_key(tmp_path):
    return backup.load_key(_keyfile(tmp_path, "other.key"))


@pytest.fixture
def world(isolated_home, tmp_path, monkeypatch):
    """A synthetic data directory laid out like a deployment, wired as THE live one: real auth schema (copied from the isolated database), real transcript schema,
    real document registry location, ledger in the directory."""
    from orca.auth import db as authdb
    from orca.auth.store import create_user
    from orca.docs import store as docs_store
    from orca.serve import conversations

    ua = create_user(f"a-{uuid.uuid4().hex[:6]}@example.com", "correcthorsebatterystaple", "A")
    ub = create_user(CANARY_EMAIL, "correcthorsebatterystaple", "B")
    home = tmp_path / "home"
    (home / "memory" / "conversations").mkdir(parents=True)
    (home / "docs").mkdir()
    s, d = sqlite3.connect(str(authdb.AUTH_DB)), sqlite3.connect(str(home / "auth.db"))
    s.backup(d)
    s.close()
    d.close()
    monkeypatch.setattr(conversations, "_dir", lambda: home / "memory" / "conversations")
    conversations._SCHEMA_READY.clear()
    monkeypatch.setattr(ledger, "_default_home", lambda: home)
    monkeypatch.setattr(docs_store, "_REGISTRY_FILE", home / "docs" / "registry.json")
    (home / "docs" / "kw_aaaa.jsonl").write_text(json.dumps({"doc_id": "d1", "text": CANARY_DOC}) + "\n")
    (home / "docs" / "registry.json").write_text(json.dumps({"s-a": [{"doc_id": "d1", "filename": "f.txt", "state": "ready"}]}))
    w = type("W", (), {})()
    w.home, w.ua, w.ub = home, ua, ub
    w.commit = lambda sid, uid, text=CANARY_TEXT: _commit(sid, uid, text)
    return w


def _commit(sid, uid, text):
    from orca.serve import conversations

    tok = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, uid, tok)
    assert auth is not None
    r = conversations.commit_turn(sid, text, "reply", user_id=uid, turn_id=uuid.uuid4().hex, fence_token=tok, epoch=auth.epoch)
    assert r.ok, r.reason


def _snapshot(root: Path) -> dict:
    import hashlib

    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and p.name != ".server.lock"}   # the empty lock file is not data


def _rows(home, sid):
    c = sqlite3.connect(str(home / "memory" / "conversations" / "turns.db"))
    try:
        return c.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", (sid,)).fetchone()[0]
    finally:
        c.close()


def _tomb(home, sid):
    c = sqlite3.connect(str(home / "memory" / "conversations" / "turns.db"))
    try:
        return c.execute("SELECT state FROM session_deletions WHERE session_id=?", (sid,)).fetchone()
    finally:
        c.close()


# ── 1. privacy: nothing readable at rest ────────────────────────────────────────────────────────────────────────────────────────

def test_the_archive_contains_no_customer_data_in_the_clear_and_is_private(world, tmp_path, key):
    world.commit("s-a", world.ua.id)
    out = tmp_path / "out" / "bk.orbk"
    made = backup.create(world.home, out, key=key)
    blob = out.read_bytes()
    for needle in (CANARY_EMAIL, CANARY_TEXT, CANARY_DOC, "SQLite format 3", "users", "conversation_turns"):
        assert needle.encode() not in blob, needle
    assert (out.stat().st_mode & 0o777) == 0o600 and made["files"] >= 3
    assert sorted(p.name for p in out.parent.iterdir()) == ["bk.orbk"], "no partial or scratch file is left beside the archive"


def test_the_deletion_ledger_is_not_part_of_the_backup(world, tmp_path, key):
    ledger.record("session", "s-x", "u", "s-x", home=world.home)
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    stage = tmp_path / "stage"
    manifest = backup._extract(out, key, stage)
    assert ledger.LEDGER_NAME not in manifest["files"] and not (stage / ledger.LEDGER_NAME).exists()


# ── 2. key custody fails closed ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_key_provisioned_means_no_backup_and_nothing_is_generated(world, tmp_path, monkeypatch):
    monkeypatch.delenv("ORNEUR_BACKUP_KEY_FILE", raising=False)
    with pytest.raises(BackupKeyError):
        backup.load_key(None)
    assert not list(tmp_path.glob("**/*.key"))


def test_unsafe_or_malformed_key_files_are_refused(world, tmp_path):
    p = _keyfile(tmp_path, "loose.key", mode=0o644)
    with pytest.raises(BackupKeyError, match="group or other"):
        backup.load_key(p)
    short = tmp_path / "keys" / "short.key"
    short.write_text("c2hvcnQ\n")
    short.chmod(0o600)
    with pytest.raises(BackupKeyError):
        backup.load_key(short)
    junk = tmp_path / "keys" / "junk.key"
    junk.write_text("!!!not base64!!!")
    junk.chmod(0o600)
    with pytest.raises(BackupKeyError):
        backup.load_key(junk)
    with pytest.raises(BackupKeyError, match="missing"):
        backup.load_key(tmp_path / "keys" / "absent.key")


def test_the_key_must_not_live_inside_the_data_directory_or_next_to_the_backup(world, tmp_path):
    inside = world.home / "k.key"
    backup.write_new_key(inside)
    with pytest.raises(BackupKeyError, match="inside"):
        backup.load_key(inside, forbid_inside=[world.home])
    dest = tmp_path / "bk-dir"
    dest.mkdir()
    beside = dest / "k.key"
    backup.write_new_key(beside)
    with pytest.raises(BackupKeyError, match="inside"):
        backup.load_key(beside, forbid_inside=[dest])


def test_keygen_writes_a_private_key_once_and_never_overwrites(tmp_path):
    p = tmp_path / "new.key"
    backup.write_new_key(p)
    assert (p.stat().st_mode & 0o777) == 0o600 and len(backup.load_key(p)) == 32
    with pytest.raises(FileExistsError):
        backup.write_new_key(p)


def test_a_wrong_key_cannot_verify_or_restore_and_the_target_is_untouched(world, tmp_path, key, other_key):
    world.commit("s-a", world.ua.id)
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    v = backup.verify(out, key=other_key)
    assert v["ok"] is False and "authentication" in v["problems"][0]
    target = tmp_path / "target"
    ledger.ensure(target)
    before = _snapshot(target)
    with pytest.raises(BackupAuthError):
        backup.restore(out, target, key=other_key, overwrite=True)
    assert _snapshot(target) == before and not list(tmp_path.glob(".target.restore-*")) and not backup.restore_pending(target)


# ── 3. tampering, truncation and junk fail closed ───────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def archive(world, tmp_path, key):
    world.commit("s-a", world.ua.id)
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    return out


@pytest.mark.parametrize("where", ["header", "salt", "first_frame", "middle", "last_byte"])
def test_flipping_a_single_bit_anywhere_is_detected(archive, key, where):
    data = bytearray(archive.read_bytes())
    pos = {"header": 2, "salt": 8, "first_frame": 40, "middle": len(data) // 2, "last_byte": len(data) - 1}[where]
    data[pos] ^= 0x01
    archive.write_bytes(bytes(data))
    assert backup.verify(archive, key=key)["ok"] is False


@pytest.mark.parametrize("cut", [1, 16, 100, "frame"])
def test_a_truncated_archive_is_detected_even_at_a_frame_boundary(archive, key, cut):
    data = archive.read_bytes()
    if cut == "frame":
        n = int.from_bytes(data[25:29], "big")
        data = data[:29 + n] if 29 + n < len(data) else data[:-1]
    else:
        data = data[:-cut]
    archive.write_bytes(data)
    assert backup.verify(archive, key=key)["ok"] is False


def test_appended_data_reordered_frames_empty_and_foreign_files_are_refused(archive, key, tmp_path):
    data = archive.read_bytes()
    archive.write_bytes(data + b"\x00" * 7)
    assert backup.verify(archive, key=key)["ok"] is False
    # swap the first two frames (needs at least two)
    frames, pos = [], 25
    while pos < len(data):
        n = int.from_bytes(data[pos:pos + 4], "big")
        frames.append(data[pos:pos + 4 + n])
        pos += 4 + n
    if len(frames) >= 2:
        frames[0], frames[1] = frames[1], frames[0]
        archive.write_bytes(data[:25] + b"".join(frames))
        assert backup.verify(archive, key=key)["ok"] is False
    for junk in (b"", b"ORBK", os.urandom(4096), b"PK\x03\x04" + b"\x00" * 100):
        f = tmp_path / "junk.bin"
        f.write_bytes(junk)
        assert backup.verify(f, key=key)["ok"] is False
    assert backup.verify(tmp_path / "does-not-exist.orbk", key=key)["ok"] is False


# ── 4. a valid-key archive can still be incomplete: it must not restore ─────────────────────────────────────────────────────────

def _forge(path, key, records, manifest):
    """An archive that AUTHENTICATES (the attacker has the key, or a buggy writer made it) but is not a complete backup."""
    with open(path, "wb") as raw:
        w = EncryptedWriter(raw, key)
        for rel, body in records:
            meta = json.dumps({"path": rel, "size": len(body), "kind": "file_copy"}).encode()
            w.write(b"F" + len(meta).to_bytes(4, "big") + meta + body)
        if manifest is not None:
            blob = json.dumps(manifest).encode()
            w.write(b"M" + len(blob).to_bytes(4, "big") + blob)
        w.close()


def _sqlite_bytes(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE t (x)")
    c.commit()
    c.close()
    return p.read_bytes()


def test_authenticated_but_malformed_archives_are_refused(tmp_path, key):
    import hashlib

    db = _sqlite_bytes(tmp_path)
    good = {"sha256": hashlib.sha256(db).hexdigest(), "size": len(db), "kind": "sqlite_online_backup"}
    base = {"format": backup.FORMAT, "created_at": "x", "created_epoch": 1, "consistent": True}
    cases = {
        "no manifest": ([("auth.db", db)], None),
        "manifest lists a missing file": ([], {**base, "files": {"auth.db": good}, "core": ["auth.db"]}),
        "unlisted extra file": ([("auth.db", db), ("planted.bin", b"x")], {**base, "files": {"auth.db": good}, "core": ["auth.db"]}),
        "hash mismatch": ([("auth.db", db)], {**base, "files": {"auth.db": {**good, "sha256": "0" * 64}}, "core": ["auth.db"]}),
        "no core database": ([("docs/a.txt", b"hi")], {**base, "files": {"docs/a.txt": {"sha256": hashlib.sha256(b"hi").hexdigest(), "size": 2, "kind": "file_copy"}}, "core": []}),
        "core listed but absent": ([("docs/a.txt", b"hi")], {**base, "files": {"docs/a.txt": {"sha256": hashlib.sha256(b"hi").hexdigest(), "size": 2, "kind": "file_copy"}}, "core": ["auth.db"]}),
        "corrupt database": ([("auth.db", b"this is not sqlite" * 50)], {**base, "files": {"auth.db": {"sha256": hashlib.sha256(b"this is not sqlite" * 50).hexdigest(), "size": 900, "kind": "sqlite_online_backup"}}, "core": ["auth.db"]}),
        "wrong format": ([("auth.db", db)], {**base, "format": "orneur-backup/1", "files": {"auth.db": good}, "core": ["auth.db"]}),
    }
    for name, (records, manifest) in cases.items():
        out = tmp_path / f"{name.replace(' ', '_')}.orbk"
        _forge(out, key, records, manifest)
        assert backup.verify(out, key=key)["ok"] is False, name


@pytest.mark.parametrize("evil", ["../escape.txt", "/abs/escape.txt", "a/../../escape.txt", ".restore-journal.json", ".pre-restore-x/auth.db", ledger.LEDGER_NAME])
def test_path_traversal_and_reserved_names_in_an_archive_are_refused(tmp_path, key, evil):
    out = tmp_path / "evil.orbk"
    _forge(out, key, [(evil, b"pwned")], {"format": backup.FORMAT, "files": {}, "core": []})
    assert backup.verify(out, key=key)["ok"] is False
    target = tmp_path / "t"
    with pytest.raises(BackupError_()):
        backup.restore(out, target, key=key, unsafe_without_deletion_history=True)
    assert not (tmp_path / "escape.txt").exists() and not Path("/abs/escape.txt").exists()


def BackupError_():
    return backup.BackupError


def test_a_home_with_no_core_database_cannot_be_backed_up(tmp_path, key):
    empty = tmp_path / "empty"
    (empty / "docs").mkdir(parents=True)
    (empty / "docs" / "x.txt").write_text("x")
    with pytest.raises(BackupIncompleteError):
        backup.create(empty, tmp_path / "bk.orbk", key=key)
    assert not (tmp_path / "bk.orbk").exists() and not list(tmp_path.glob("bk.orbk.*"))


# ── 5. deleted data is not resurrected ──────────────────────────────────────────────────────────────────────────────────────────

def test_a_conversation_deleted_after_the_backup_stays_deleted_after_restore_in_place(world, tmp_path, key):
    from orca.serve import deletions

    world.commit("s-a", world.ua.id)
    world.commit("s-b", world.ub.id, "B's own private note")
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    deletions.begin("s-a", world.ua.id)                    # the customer deletes AFTER the backup ...
    deletions.run("s-a", world.ua.id)
    assert _rows(world.home, "s-a") == 0
    r = backup.restore(out, world.home, key=key, overwrite=True)      # ... disaster recovery from the older archive
    assert r["deletion_history_sources"] == ["live_ledger"] and r["deletions_applied"]["session"] == 1
    assert _rows(world.home, "s-a") == 0 and _tomb(world.home, "s-a") is not None
    assert _rows(world.home, "s-b") == 1, "tenant isolation: the other customer's conversation is restored intact"
    assert _tomb(world.home, "s-b") is None
    raw = (world.home / "memory/conversations/turns.db").read_bytes()
    assert raw.count(CANARY_TEXT.encode()) == 0, "deleted text must not linger in freed database pages of the restored file"


def test_a_deleted_document_and_a_deleted_account_stay_deleted(world, tmp_path, key):
    from orca.auth.store import get_user_by_id
    from orca.docs import store as docs_store

    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    assert docs_store.mark_doc_deleting("s-a", "d1") is True          # real hook -> ledger
    ledger.record("user", world.ub.id, world.ub.id, home=world.home)   # account deletion's own hook is covered separately below
    r = backup.restore(out, world.home, key=key, overwrite=True)
    assert r["deletions_applied"]["doc"] == 1 and r["deletions_applied"]["user"] == 1
    reg = json.loads((world.home / "docs" / "registry.json").read_text())
    assert reg["s-a"] == [] and CANARY_DOC not in (world.home / "docs" / "kw_aaaa.jsonl").read_text()
    c = sqlite3.connect(str(world.home / "auth.db"))
    try:
        assert c.execute("SELECT COUNT(*) FROM users WHERE id=?", (world.ub.id,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM users WHERE id=?", (world.ua.id,)).fetchone()[0] == 1, "tenant isolation: the other account survives"
    finally:
        c.close()
    assert CANARY_EMAIL.encode() not in (world.home / "auth.db").read_bytes(), "the deleted account's email must not linger in freed pages"


def test_account_deletion_writes_the_ledger_before_destroying_anything(isolated_home):
    from orca.auth.store import create_user
    from orca.serve import account_delete

    u = create_user(f"x-{uuid.uuid4().hex[:6]}@example.com", "correcthorsebatterystaple", "X")
    account_delete.delete_account(u.id)
    assert any(e["kind"] == "user" and e["id"] == u.id for e in ledger.read())


def test_restore_refuses_when_no_authoritative_deletion_history_exists(world, tmp_path, key):
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    fresh = tmp_path / "new-machine"
    with pytest.raises(DeletionHistoryUnavailable):
        backup.restore(out, fresh, key=key)
    assert not fresh.exists() and not list(tmp_path.glob(".new-machine.restore-*"))


def test_a_deletion_history_export_carries_the_history_to_a_new_machine(world, tmp_path, key):
    from orca.serve import deletions

    world.commit("s-a", world.ua.id)
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    deletions.begin("s-a", world.ua.id)
    export = tmp_path / "elsewhere" / "deletions.json"
    export.parent.mkdir()
    meta = ledger.export(world.home, export, key)
    assert meta["entries"] >= 1
    assert CANARY_TEXT not in export.read_text() and CANARY_EMAIL not in export.read_text(), "identifiers only, never content"
    fresh = tmp_path / "new-machine"
    r = backup.restore(out, fresh, key=key, deletion_ledger=export)
    assert r["deletion_history_sources"] == ["export"] and _rows(fresh, "s-a") == 0 and _tomb(fresh, "s-a") is not None
    assert (fresh / ledger.LEDGER_NAME).exists(), "the history travels with the restored directory"


def test_a_stale_modified_or_wrongly_keyed_export_is_refused(world, tmp_path, key, other_key):
    export = tmp_path / "old.json"
    ledger.export(world.home, export, key)                            # taken BEFORE the backup below
    time.sleep(0.02)
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    with pytest.raises(DeletionHistoryUnavailable, match="older"):
        backup.restore(out, tmp_path / "t1", key=key, deletion_ledger=export)
    ledger.record("session", "s-erased", "u", "s-erased", home=world.home)
    fresh_export = tmp_path / "new.json"
    ledger.export(world.home, fresh_export, key)
    doc = json.loads(fresh_export.read_text())
    doc["lines"] = doc["lines"][:-1]                                  # an attacker erasing the newest history
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(doc))
    with pytest.raises(BackupAuthError):
        backup.restore(out, tmp_path / "t2", key=key, deletion_ledger=tampered)
    with pytest.raises(BackupAuthError):
        backup.restore(out, tmp_path / "t3", key=other_key, deletion_ledger=fresh_export)
    for t in ("t1", "t2", "t3"):
        assert not (tmp_path / t).exists()


def test_the_explicit_unsafe_override_restores_but_never_claims_deletions_were_honoured(world, tmp_path, key):
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    fresh = tmp_path / "dr"
    r = backup.restore(out, fresh, key=key, unsafe_without_deletion_history=True)
    assert r["deleted_data_may_be_present"] is True and r["deletion_history_sources"] == []
    assert not (fresh / ledger.LEDGER_NAME).exists(), "an empty ledger would later pass for authoritative history"
    with pytest.raises(DeletionHistoryUnavailable):                   # and the restored directory is not treated as having history
        backup.restore(out, tmp_path / "dr2", key=key)


def test_a_failed_ledger_write_refuses_the_deletion_instead_of_losing_the_record(world, monkeypatch):
    from orca.docs import store as docs_store

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ledger, "record", boom)
    before = (world.home / "docs" / "registry.json").read_text()
    with pytest.raises(OSError):
        docs_store.mark_doc_deleting("s-a", "d1")
    assert (world.home / "docs" / "registry.json").read_text() == before, "the document is still served: the deletion can be retried"


def test_ledger_survives_concurrent_appends_and_a_torn_last_line(tmp_path):
    home = tmp_path / "h"
    threads = [threading.Thread(target=lambda i=i: [ledger.record("session", f"s{i}-{n}", "u", home=home) for n in range(25)]) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ledger.read(home)) == 200
    with open(ledger.path(home), "a") as f:
        f.write('{"at": 1, "kind": "sess')                            # crash mid-append: never returned success, so it is ignored
    assert len(ledger.read(home)) == 200
    ledger.record("session", "after-crash", "u", home=home)           # and the next append repairs the tail instead of corrupting the chain
    assert len(ledger.read(home)) == 201 and ledger.chain_info(home)["count"] == 202
    with open(ledger.path(home), "a") as f:
        f.write("TRAILING GARBAGE\n")
    with pytest.raises(ledger.LedgerIntegrityError):
        ledger.read(home)                                             # a corrupt line in the body is not trusted


# ── 6. all-or-nothing restore ───────────────────────────────────────────────────────────────────────────────────────────────────

def _populated_target(world, tmp_path):
    t = tmp_path / "live"
    t.mkdir()
    (t / "auth.db").write_bytes(b"LIVE-AUTH")
    (t / "extra-live.txt").write_text("live only")
    (t / "vault").mkdir()
    (t / "vault" / "secret").write_text("never backed up, never replaced")
    import shutil

    shutil.copy2(ledger.path(world.home), ledger.path(t))      # the same machine's own ledger lineage; an unrelated lineage is (correctly) refused
    ledger.record("session", "s-live", "u", home=t)
    return t


def test_a_failure_at_any_step_of_the_swap_rolls_back_to_the_exact_previous_state(world, tmp_path, key, monkeypatch):
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    for crash_at in range(1, 9):
        t = _populated_target(world, tmp_path / f"r{crash_at}") if (tmp_path / f"r{crash_at}").mkdir() is None else None
        before = _snapshot(t)
        real, n = os.replace, {"n": 0}

        def failing(src, dst, *a, _n=n, _at=crash_at, **k):
            if ".restore-" in str(src) or ".pre-restore-" in str(dst) or str(src).endswith(".pre-restore") or "restore-journal" in str(dst) or "pre-restore" in str(src):
                _n["n"] += 1
                if _n["n"] == _at:
                    raise OSError("simulated power loss")
            return real(src, dst, *a, **k)

        monkeypatch.setattr(os, "replace", failing)
        try:
            with pytest.raises(OSError):
                backup.restore(out, t, key=key, overwrite=True)
        finally:
            monkeypatch.setattr(os, "replace", real)
        assert _snapshot(t) == before, f"crash at step {crash_at}: not the previous state"
        assert not backup.restore_pending(t) and not list(t.glob(".pre-restore-*"))


def test_a_hard_crash_leaves_a_journal_that_blocks_use_until_recovered_and_recovery_is_exact(world, tmp_path, key, monkeypatch, client=None):
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    t = _populated_target(world, tmp_path)
    before = _snapshot(t)
    real = os.replace
    n = {"n": 0}

    def crash(src, dst, *a, **k):
        if ".restore-" in str(src) and ".pre-restore-" not in str(dst):          # while placing restored files
            n["n"] += 1
            if n["n"] == 2:
                raise OSError("power loss")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", crash)
    monkeypatch.setattr(backup, "recover_interrupted", lambda home: {"recovered": False})        # the process died: no in-process rollback
    with pytest.raises(OSError):
        backup.restore(out, t, key=key, overwrite=True)
    monkeypatch.undo() if False else None
    monkeypatch.setattr(os, "replace", real)
    assert backup.restore_pending(t)
    assert _snapshot(t) != before, "mid-swap: a mixture exists on disk, which is exactly why it is flagged"
    with pytest.raises(RestoreFailed, match="did not finish"):
        backup.restore(out, t, key=key, overwrite=True)
    monkeypatch.undo()
    r = backup.recover_interrupted(t)
    assert r["recovered"] is True and _snapshot(t) == before and not backup.restore_pending(t)
    assert backup.recover_interrupted(t) == {"recovered": False}      # idempotent


def test_readiness_reports_not_ready_while_a_restore_is_unfinished(world, monkeypatch, client=None):
    from fastapi.testclient import TestClient

    from orca.serve import backup as b
    from orca.serve.api import app

    monkeypatch.setattr(b, "restore_pending", lambda home: True)
    r = TestClient(app).get("/readyz")
    assert r.status_code == 503 and r.json()["dependencies"]["restore"]["status"] == "interrupted"


def test_a_failed_restore_into_a_fresh_directory_leaves_nothing_behind(world, tmp_path, key, monkeypatch):
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    fresh = tmp_path / "fresh"
    monkeypatch.setattr(backup, "_health_check", lambda root, entries: ["injected failure"])
    with pytest.raises(RestoreFailed):
        backup.restore(out, fresh, key=key, unsafe_without_deletion_history=True)
    assert not fresh.exists() and not list(tmp_path.glob(".fresh.restore-*"))


def test_the_post_restore_health_check_blocks_a_directory_that_still_contains_deleted_data(world, tmp_path, key, monkeypatch):
    from orca.serve import deletions

    world.commit("s-a", world.ua.id)
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    deletions.begin("s-a", world.ua.id)
    t = _populated_target(world, tmp_path)
    ledger.record("session", "s-a", world.ua.id, "s-a", home=t)
    before = _snapshot(t)
    monkeypatch.setattr(backup, "_apply_deletions", lambda stage, entries: {"session": 0, "doc": 0, "user": 0})     # a regression that forgets to apply deletions
    with pytest.raises(RestoreFailed, match="health check"):
        backup.restore(out, t, key=key, overwrite=True)
    assert _snapshot(t) == before


def test_restore_keeps_what_the_backup_never_contained_and_refuses_a_populated_target_by_default(world, tmp_path, key):
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    t = _populated_target(world, tmp_path)
    with pytest.raises(FileExistsError):
        backup.restore(out, t, key=key)
    backup.restore(out, t, key=key, overwrite=True)
    assert (t / "vault" / "secret").read_text().startswith("never backed up"), "vault/ is outside the backup and outside the swap"
    assert (t / "auth.db").read_bytes()[:15] == b"SQLite format 3"
    assert (t / "extra-live.txt").read_text() == "live only", "a top-level file the backup never contained is left alone"
    leftovers = list(t.glob(".pre-restore-*"))
    assert len(leftovers) == 1 and (leftovers[0] / "auth.db").read_bytes() == b"LIVE-AUTH", "the previous state is kept for rollback until the operator removes it"


# ── 7. consistency ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_backup_taken_while_the_database_is_being_written_verifies_and_restores_a_consistent_database(world, tmp_path, key):
    world.commit("s-a", world.ua.id)
    stop = threading.Event()

    def writer():
        while not stop.is_set():
            c = sqlite3.connect(str(world.home / "memory/conversations/turns.db"), timeout=10)
            try:
                with c:
                    c.execute("INSERT INTO session_export_state (session_id, updated_at) VALUES (?, ?) ON CONFLICT DO NOTHING", (uuid.uuid4().hex, time.time()))
            finally:
                c.close()

    th = threading.Thread(target=writer)
    th.start()
    try:
        out = tmp_path / "bk.orbk"
        backup.create(world.home, out, key=key)
    finally:
        stop.set()
        th.join()
    assert backup.verify(out, key=key)["ok"] is True
    fresh = tmp_path / "fresh"
    backup.restore(out, fresh, key=key, unsafe_without_deletion_history=True)
    c = sqlite3.connect(str(fresh / "memory/conversations/turns.db"))
    try:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and c.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id='s-a'").fetchone()[0] == 1
    finally:
        c.close()


def test_a_file_that_changes_while_it_is_copied_marks_the_backup_inconsistent_and_restore_refuses_it(world, tmp_path, key, monkeypatch):
    vec = world.home / "memory" / "vectors"
    vec.mkdir()
    (vec / "segment.bin").write_bytes(b"a" * 100)
    import shutil

    real = shutil.copyfile

    def racing(src, dst, *a, **k):
        r = real(src, dst, *a, **k)
        if Path(src).name == "segment.bin":
            with open(src, "ab") as f:                                  # the live vector store is written during the copy
                f.write(b"more")
        return r

    monkeypatch.setattr(shutil, "copyfile", racing)
    out = tmp_path / "bk.orbk"
    made = backup.create(world.home, out, key=key)
    monkeypatch.setattr(shutil, "copyfile", real)
    assert made["consistent"] is False and made["unstable_files"] == ["memory/vectors/segment.bin"]
    assert backup.verify(out, key=key)["consistent"] is False
    with pytest.raises(BackupIncompleteError, match="changing"):
        backup.restore(out, tmp_path / "fresh", key=key, unsafe_without_deletion_history=True)
    assert not (tmp_path / "fresh").exists()
    backup.restore(out, tmp_path / "fresh2", key=key, unsafe_without_deletion_history=True, allow_inconsistent=True)


def test_an_interrupted_backup_leaves_no_archive_partial_file_or_plaintext_scratch(world, tmp_path, key, monkeypatch):
    monkeypatch.setattr(EncryptedWriter, "close", lambda self: (_ for _ in ()).throw(OSError("disk full")))
    out_dir = tmp_path / "o"
    with pytest.raises(OSError):
        backup.create(world.home, out_dir / "bk.orbk", key=key)
    assert list(out_dir.iterdir()) == []


# ── 8. recovery after restart ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_after_restart_the_deletion_sweep_finishes_what_the_restore_started(world, tmp_path, key):
    from orca.serve import deletions

    world.commit("s-a", world.ua.id)
    out = tmp_path / "bk.orbk"
    backup.create(world.home, out, key=key)
    deletions.begin("s-a", world.ua.id)
    backup.restore(out, world.home, key=key, overwrite=True)
    assert _tomb(world.home, "s-a")[0] == "revoked"
    assert deletions.is_tombstoned("s-a")                              # access is revoked the instant the restored directory is served
    assert deletions.resume_pending() >= 1
    assert deletions.get("s-a")["state"] in ("complete", "partial")


# ── 9. CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_cli_refuses_without_a_key_and_never_creates_one(isolated_home, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from orca.cli import app

    monkeypatch.delenv("ORNEUR_BACKUP_KEY_FILE", raising=False)
    out = tmp_path / "bk.orbk"
    r = CliRunner().invoke(app, ["data-backup", "create", str(out)])
    assert r.exit_code == 2 and not out.exists() and "key" in r.output.lower()


def test_the_cli_round_trip_with_a_provisioned_key(isolated_home, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from orca.cli import app
    from orca.config import ORCA_HOME

    runner = CliRunner()
    kf = tmp_path / "keys" / "k.key"
    kf.parent.mkdir()
    assert runner.invoke(app, ["data-backup", "keygen", str(kf)]).exit_code == 0
    assert runner.invoke(app, ["data-backup", "keygen", str(kf)]).exit_code != 0                       # no overwrite
    home = Path(ORCA_HOME)
    (home / "auth.db").parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(home / "auth.db"))
    c.execute("CREATE TABLE IF NOT EXISTS t (x)")
    c.commit()
    c.close()
    out = tmp_path / "out" / "bk.orbk"
    made = runner.invoke(app, ["data-backup", "create", str(out), "--key-file", str(kf)])
    assert made.exit_code == 0, made.output
    assert runner.invoke(app, ["data-backup", "verify", str(out), "--key-file", str(kf)]).exit_code == 0
    wrong = tmp_path / "keys" / "w.key"
    assert runner.invoke(app, ["data-backup", "keygen", str(wrong)]).exit_code == 0
    assert runner.invoke(app, ["data-backup", "verify", str(out), "--key-file", str(wrong)]).exit_code == 1
    loose = tmp_path / "keys" / "loose.key"
    loose.write_text(kf.read_text())
    loose.chmod(0o644)
    assert runner.invoke(app, ["data-backup", "verify", str(out), "--key-file", str(loose)]).exit_code == 2
