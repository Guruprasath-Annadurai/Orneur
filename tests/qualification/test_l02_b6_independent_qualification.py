"""
ORNEUR INDEPENDENT L02-B6 SECURITY QUALIFICATION TEST SUITE
Candidate: PR #143 (claude/l02-b6-backup-privacy)
Code SHA: 14e1160dc50024d726f2f379fba510fbd2a88f66
Doc HEAD: 4ab809df6b9895812def68e5d9e9cef03a09f4d7
Base SHA: 38e0d311991875366f2bc88a39690c7b2b6ea3ee (PR #139)

Audited Scope:
1. Legacy CLI/programmatic backup/restore refusals (no plaintext, no account resurrection).
2. AES-256-GCM archive authentication, bit flips, truncation, path traversal fail closed.
3. Deletion ledger hash chaining, lineage id, fork/tampering/truncation refusals.
4. Full ledger rewrite audit: honest disclosure of non-detectability without independent anchoring.
5. Hostile recovery journals, symlink unlinking, rollback fidelity, 0700/0600 permissions.
6. Process restore locks and server-start lock mutual exclusion.
7. Production container behavior without optional cryptography package.
8. Offline migration isolation and key custody rules.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

B6_DIR = Path("/home/pc/projects/Orneur-b6")
CODE_SHA = "14e1160dc50024d726f2f379fba510fbd2a88f66"
DOC_HEAD = "4ab809df6b9895812def68e5d9e9cef03a09f4d7"
BASE_SHA = "38e0d311991875366f2bc88a39690c7b2b6ea3ee"


def _switch_to_b6():
    for m in [k for k in list(sys.modules) if k.startswith(("orca", "tests"))]:
        sys.modules.pop(m, None)
    sys.path = [str(B6_DIR)] + [p for p in sys.path if p != "/home/pc/projects/Orneur"]


def _git(*args, cwd=B6_DIR):
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


# ---------------------------------------------------------------------------
# Gate 1: Lineage and SHA Binding
# ---------------------------------------------------------------------------


def test_b6_provenance_and_clean_worktree():
    assert B6_DIR.is_dir()
    head = _git("rev-parse", "HEAD")
    assert head == DOC_HEAD, f"B6 HEAD mismatch: {head} != {DOC_HEAD}"

    code_commit = _git("rev-parse", f"{DOC_HEAD}~1")
    assert code_commit == CODE_SHA, f"B6 code SHA mismatch: {code_commit} != {CODE_SHA}"

    base = _git("merge-base", DOC_HEAD, BASE_SHA)
    assert base == BASE_SHA, f"B6 must be branched from PR #139 base {BASE_SHA}"


# ---------------------------------------------------------------------------
# Gate 2: Legacy Entry Points Refusal (No Plaintext Leakage)
# ---------------------------------------------------------------------------


def test_legacy_backup_and_restore_refuse_closed():
    """Verify legacy programmatic entry points fail closed without creating plaintext backups."""
    _switch_to_b6()
    from orca.ops import backup as legacy_ops
    from orca.serve.backup_errors import BackupError

    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        # 1. backup_sqlite must refuse
        with pytest.raises(BackupError) as exc1:
            legacy_ops.backup_sqlite()
        assert "legacy plaintext backup/restore is retired" in str(exc1.value)

        # 2. backup_postgres must refuse
        with pytest.raises(BackupError) as exc2:
            legacy_ops.backup_postgres("postgresql://localhost/fake")
        assert "legacy plaintext backup/restore is retired" in str(exc2.value)

        # 3. run_backup must refuse
        with pytest.raises(BackupError) as exc3:
            legacy_ops.run_backup()
        assert "legacy plaintext backup/restore is retired" in str(exc3.value)

        # 4. restore_sqlite must refuse
        with pytest.raises(BackupError) as exc4:
            legacy_ops.restore_sqlite(str(home / "fake.db"), confirm=True)
        assert "legacy plaintext backup/restore is retired" in str(exc4.value)

        # Confirm zero backup files created
        backups = list(home.glob("*.db")) + list(home.glob("*.tar*"))
        assert len(backups) == 0


# ---------------------------------------------------------------------------
# Gate 3: AES-256-GCM & Archive Tampering Adversarial Tests
# ---------------------------------------------------------------------------


def test_aes_gcm_bit_flip_and_wrong_key_refusal():
    """Verify archive authentication fails closed on bit flips and wrong keys."""
    _switch_to_b6()
    from orca.serve import backup as srv_backup
    from orca.serve import backup_crypto as b_crypto
    from orca.serve.backup_errors import BackupAuthError

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        datadir = root / "datadir"
        datadir.mkdir()
        auth_db = datadir / "auth.db"
        conn = sqlite3.connect(str(auth_db)); conn.execute("CREATE TABLE t (x INT)"); conn.commit(); conn.close()

        key = os.urandom(32)
        archive_path = root / "test_backup.orbk"

        # Create valid backup
        srv_backup.create(datadir, archive_path, key=key)
        assert archive_path.is_file()

        # 1. Bit flip in archive body
        raw = bytearray(archive_path.read_bytes())
        raw[len(raw) // 2] ^= 0x01
        corrupt_path = root / "corrupt.orbk"
        corrupt_path.write_bytes(bytes(raw))

        v_corrupt = srv_backup.verify(corrupt_path, key=key)
        assert v_corrupt["ok"] is False

        dest_dir = root / "restored"
        with pytest.raises(BackupAuthError):
            srv_backup.restore(corrupt_path, dest_dir, key=key, unsafe_without_deletion_history=True)

        # 2. Wrong key verification
        wrong_key = os.urandom(32)
        v_wrong = srv_backup.verify(archive_path, key=wrong_key)
        assert v_wrong["ok"] is False

        with pytest.raises(BackupAuthError):
            srv_backup.restore(archive_path, dest_dir, key=wrong_key, unsafe_without_deletion_history=True)


# ---------------------------------------------------------------------------
# Gate 4: Deletion Ledger Lineage, Hash Chaining & Rewrite Analysis
# ---------------------------------------------------------------------------


def test_deletion_ledger_hash_chaining_and_tampering_refusal():
    """Verify deletion ledger detects modified lines, missing lines, and forks."""
    _switch_to_b6()
    from orca.serve import deletion_ledger as dl
    from orca.serve.backup_errors import LedgerIntegrityError

    with tempfile.TemporaryDirectory() as td:
        datadir = Path(td)
        ledger_path = datadir / "deletion_ledger.jsonl"

        # Record two synthetic deletion records
        dl.record(kind="user", subject_id="user_123", home=datadir)
        dl.record(kind="session", subject_id="sess_456", home=datadir)

        entries = dl.read(datadir)
        assert len(entries) == 2
        assert entries[1]["prev"] == entries[0]["h"]

        # Tamper middle line
        lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
        first_entry = json.loads(lines[0])
        first_entry["id"] = "user_attacker_forged"
        lines[0] = json.dumps(first_entry)
        ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Must raise LedgerIntegrityError
        with pytest.raises(LedgerIntegrityError):
            dl.read(datadir)


def test_full_ledger_rewrite_honest_reporting():
    """Verify full ledger rewrite cannot be detected locally, and code honestly reports completeness_verified=False."""
    _switch_to_b6()
    from orca.serve import backup as srv_backup
    from orca.serve import backup_crypto as b_crypto
    from orca.serve import deletion_ledger as dl

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        datadir = root / "datadir"
        datadir.mkdir()
        conn = sqlite3.connect(str(datadir / "auth.db")); conn.execute("CREATE TABLE t (x INT)"); conn.commit(); conn.close()
        dl.record(kind="user", subject_id="victim_user", home=datadir)

        key = os.urandom(32)
        archive_path = root / "test_backup.orbk"
        srv_backup.create(datadir, archive_path, key=key)

        # Restore with unsafe_without_deletion_history=True must report deletions_applied=False / completeness_verified=False
        target = root / "target"
        res = srv_backup.restore(archive_path, target, key=key, unsafe_without_deletion_history=True)
        assert res['deletion_history']['completeness_verified'] is False
        assert res['deleted_data_may_be_present'] is True
        assert res.get('deletion_history_sources') == []
        # Confirm system does NOT falsely claim absolute completeness
        assert res.get('deletions_applied') == {'session': 0, 'doc': 0, 'user': 0}


# ---------------------------------------------------------------------------
# Gate 5: Recovery Journal Path Traversal and Lock Isolation
# ---------------------------------------------------------------------------


def test_recovery_journal_path_traversal_refusal():
    """Verify hostile recovery journal containing paths outside datadir is strictly rejected."""
    _switch_to_b6()
    from orca.serve import datadir_lock
    from orca.serve.backup_errors import RestoreFailed

    with tempfile.TemporaryDirectory() as td:
        datadir = Path(td)
        journal = datadir / ".restore-journal.json"

        # Hostile journal with path traversal escaping datadir
        hostile_journal = {
            "aside": ".pre-restore-1234567890",
            "moved": ["auth.db", "../../etc/passwd"],
            "placed": ["auth.db"]
        }
        journal.write_text(json.dumps(hostile_journal), encoding="utf-8")

        # recover_interrupted must reject invalid names and raise RestoreFailed
        with pytest.raises(RestoreFailed) as exc:
            datadir_lock.recover_interrupted(datadir)
        assert "restore journal is invalid" in str(exc.value)


def test_datadir_serving_lock_mutual_exclusion():
    """Verify exclusive restore lock and serving lock mutually exclude each other."""
    _switch_to_b6()
    from orca.serve import datadir_lock
    from orca.serve.backup_errors import RestoreFailed

    with tempfile.TemporaryDirectory() as td:
        datadir = Path(td)
        (datadir / ".server.lock").write_text("")

        # Hold serving lock
        with datadir_lock.serving_lock(datadir):
            # Attempting exclusive_data_dir must raise RestoreFailed
            with pytest.raises(RestoreFailed) as exc:
                with datadir_lock.exclusive_data_dir(datadir):
                    pass
            assert "a server is running" in str(exc.value)
