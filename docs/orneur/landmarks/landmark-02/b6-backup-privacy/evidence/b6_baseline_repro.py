"""L02-B6 -- baseline reproduction of the backup privacy / restoration risks, against the UNMODIFIED `orca/serve/backup.py` at 38e0d31.

Each test asserts the SECURE property and is expected to FAIL on the baseline where the risk is real; a test that passes on the baseline disproves that suspected risk
(recorded as such). Synthetic data only. Run (from a repository checkout, with this file copied into tests/ so conftest fixtures apply):
    pytest tests/b6_baseline_repro.py -p no:cacheprovider -v
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import uuid
from pathlib import Path

import pytest

CANARY_EMAIL = "canary-customer-7f3a@example.com"
CANARY_TEXT = "CANARY-SECRET-QUARTERLY-NUMBERS-91827"


def _home(tmp_path) -> Path:
    from orca.serve import conversations

    home = tmp_path / "home"
    (home / "memory" / "conversations").mkdir(parents=True)
    (home / "docs").mkdir()
    return home


@pytest.fixture
def live(isolated_home, tmp_path, monkeypatch):
    """A synthetic data directory whose transcript database is the real schema, wired as THE live database."""
    from orca.serve import conversations

    home = _home(tmp_path)
    monkeypatch.setattr(conversations, "_dir", lambda: home / "memory" / "conversations")
    conversations._SCHEMA_READY.clear()
    auth = sqlite3.connect(str(home / "auth.db"))
    auth.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT, password_hash TEXT)")
    auth.execute("INSERT INTO users VALUES (?,?,?)", ("u1", CANARY_EMAIL, "pbkdf2$synthetic"))
    auth.commit()
    auth.close()
    (home / "docs" / "kw_aaaa.jsonl").write_text(json.dumps({"doc_id": "d1", "text": CANARY_TEXT}) + "\n")
    return home


def _commit(sid, uid="u1", text=CANARY_TEXT):
    from orca.serve import conversations

    tok = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, uid, tok)
    assert auth is not None
    r = conversations.commit_turn(sid, text, "reply", user_id=uid, turn_id=uuid.uuid4().hex, fence_token=tok, epoch=auth.epoch)
    assert r.ok, r.reason


def _all_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


def test_R1_a_backup_does_not_expose_customer_data_in_plaintext(live, tmp_path):
    from orca.serve import backup

    _commit("s1")
    dest = tmp_path / "bk"
    backup.create(live, dest)
    blob = _all_bytes(dest)
    assert CANARY_EMAIL.encode() not in blob, "account email readable in the backup"
    assert CANARY_TEXT.encode() not in blob, "conversation / document text readable in the backup"


def test_R1b_backup_files_are_not_readable_by_other_local_users(live, tmp_path):
    from orca.serve import backup

    for p in live.rglob("*"):
        if p.is_file():
            p.chmod(0o644)                                        # a typical umask-022 deployment
    dest = tmp_path / "bk"
    backup.create(live, dest)
    loose = [str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file() and p.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH)]
    assert not loose, loose


def test_R2_restoring_an_older_backup_does_not_resurrect_a_conversation_deleted_afterwards(live, tmp_path):
    from orca.serve import backup, conversations, deletions

    _commit("s-deleted")
    dest = tmp_path / "bk"
    backup.create(live, dest)                                     # the customer still has the conversation here
    deletions.begin("s-deleted", "u1")                            # ... and deletes it afterwards
    deletions.run("s-deleted", "u1")
    assert deletions.is_tombstoned("s-deleted")
    backup.restore(dest, live, overwrite=True)                    # disaster recovery from the older backup
    conversations._SCHEMA_READY.clear()
    conn = conversations._turns_conn()
    try:
        rows = conn.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", ("s-deleted",)).fetchone()[0]
    finally:
        conn.close()
    assert deletions.is_tombstoned("s-deleted") and rows == 0, "the deleted conversation is accessible / present again"


def test_R3_an_interrupted_restore_leaves_either_the_old_or_the_new_directory_never_a_mixture(live, tmp_path, monkeypatch):
    from orca.serve import backup

    _commit("s-old")
    dest = tmp_path / "bk"
    backup.create(live, dest)
    (live / "docs" / "kw_aaaa.jsonl").write_text("CHANGED-AFTER-BACKUP\n")      # the live directory has moved on
    (live / "extra-after-backup.txt").write_text("x")

    def digest(root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "MANIFEST" not in p.name}

    old = digest(live)
    real_replace, calls = os.replace, {"n": 0}

    def crash(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated power loss")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(Exception):
        backup.restore(dest, live, overwrite=True)
    monkeypatch.setattr(os, "replace", real_replace)
    now = digest(live)
    restored = digest(dest)
    assert now == old or all(now.get(k) == v for k, v in restored.items()), "a mixture of old and restored files"


def test_R4a_verify_rejects_a_backup_whose_manifest_was_rewritten_to_match_tampered_files(live, tmp_path):
    from orca.serve import backup

    dest = tmp_path / "bk"
    backup.create(live, dest)
    victim = dest / "docs" / "kw_aaaa.jsonl"
    victim.write_text(json.dumps({"doc_id": "d1", "text": "ATTACKER-CONTROLLED"}) + "\n")
    m = json.loads((dest / "MANIFEST.json").read_text())
    m["files"]["docs/kw_aaaa.jsonl"]["sha256"] = hashlib.sha256(victim.read_bytes()).hexdigest()
    (dest / "MANIFEST.json").write_text(json.dumps(m))
    assert backup.verify(dest)["ok"] is False, "an attacker who can write the backup can also rewrite its manifest"


def test_R4b_verify_requires_the_core_components_to_be_present(live, tmp_path):
    from orca.serve import backup

    _commit("s1")
    dest = tmp_path / "bk"
    backup.create(live, dest)
    (dest / "auth.db").unlink()
    m = json.loads((dest / "MANIFEST.json").read_text())
    m["files"].pop("auth.db")
    (dest / "MANIFEST.json").write_text(json.dumps(m))
    assert backup.verify(dest)["ok"] is False, "a backup without the accounts database verifies as complete"


def test_R4c_a_corrupt_or_missing_manifest_is_a_controlled_refusal(live, tmp_path):
    from orca.serve import backup

    dest = tmp_path / "bk"
    backup.create(live, dest)
    (dest / "MANIFEST.json").write_text("{ not json")
    v = backup.verify(dest)                                       # verification reports; it does not crash the operator tool with a traceback
    assert v["ok"] is False and v["problems"]
    (dest / "MANIFEST.json").unlink()
    v = backup.verify(dest)
    assert v["ok"] is False and v["problems"]


def test_R4d_a_backup_with_unlisted_extra_files_is_not_reported_as_exactly_what_was_made(live, tmp_path):
    from orca.serve import backup

    dest = tmp_path / "bk"
    backup.create(live, dest)
    (dest / "planted.bin").write_bytes(b"not in the manifest")
    assert backup.verify(dest)["ok"] is False, "a file outside the manifest is silently accepted (and restore would copy it)"
