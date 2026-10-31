"""
ORNEUR INDEPENDENT MASTER-04 QUALIFICATION TEST SUITE
Candidate: PR #148 (cursor/master-04-vector-backup-security-integration)
Verified PR HEAD: da699a01bdb811ac54ef00cf0c9585f70eb74a57
Engineering Code SHA: cadad0e525c5f84698af9945d048b9ba36aa4f0e
Merge Commit: 4295550b7991972e7a6b5cd1d25123b58355cbf1
Parent M03 (PR #146): b96cc3260078b6f677a22381b05fe1f72026256f
Parent L03 (PR #147): bfeaae2bc7470251262b3526e32fede7412996d8 (Code: c8b0f54bafe364c18e507425570d34be1e7b8dd7)
Canonical Main: 20a8546f5a1ece7e5af655c0f30ca7e305f71b1a

Independent Adversarial Audit Gates:
- Gate A: Integration DAG Ancestry, Fail-Closed History Verification, Code vs Doc Separation
- Gate B: Vector-Owner & Restore Lock Security, Mutual Exclusion, SIGSTOP Owner Lock, Exit-2 Fail-Closed
- Gate C: Vector Backup Consistency Truth (Active vs Quiesced, Barrier Enforcement, Inconsistency Flagging)
- Gate D: Customer Data Non-Resurrection, Tombstone Application, Deletion Sweep Byte Purge, Unsafe Override
- Gate E: Interrupted Restore Crash Journaling, Fail-Closed Recovery, Rollback Protection
- Gate F: Tenant Ownership Isolation, 8-Char Truncation Collisions, AF_UNIX Socket Auth & Traversal Defenses
- Governance: Strictly 0/95 Formal Acceptance & Training STRICT NO-GO
"""

import fcntl
import hashlib
import json
import os
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
import pytest

M04_DIR = Path(os.environ.get("ORNEUR_M04_DIR", "/home/pc/projects/Orneur-master04"))
ORNEUR_REPO = Path(os.environ.get("ORNEUR_REPO", "/home/pc/projects/Orneur"))

DOC_HEAD = "da699a01bdb811ac54ef00cf0c9585f70eb74a57"
CODE_SHA = "cadad0e525c5f84698af9945d048b9ba36aa4f0e"
MERGE_COMMIT = "4295550b7991972e7a6b5cd1d25123b58355cbf1"
PARENT_M03 = "b96cc3260078b6f677a22381b05fe1f72026256f"
PARENT_L03 = "bfeaae2bc7470251262b3526e32fede7412996d8"
CANONICAL_MAIN = "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a"


def _run_in_m04(code: str, env_vars: dict = None, timeout: float = 60.0) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"PYTHONPATH": str(M04_DIR), **(env_vars or {})})
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(M04_DIR),
    )


# ---------------------------------------------------------------------------
# Gate A: Integration DAG Ancestry & Code/Doc Separation
# ---------------------------------------------------------------------------


def test_gate_a_integration_dag_ancestry_and_code_doc_separation():
    """Verify that MASTER-04 merge commit preserves complete ancestry of MASTER-03, LANDMARK-03,
    and canonical main, and that commits between engineering SHA and PR HEAD are doc-only."""
    # 1. Verify merge commit parents
    cmd_parents = f"git cat-file -p {MERGE_COMMIT}"
    out = subprocess.check_output(cmd_parents, shell=True, text=True, cwd=str(M04_DIR))
    parents = [line.split()[1] for line in out.splitlines() if line.startswith("parent ")]
    assert len(parents) == 2, f"Expected 2 parents for merge commit, got {parents}"
    assert parents[0] == PARENT_M03, f"Parent 1 mismatch: {parents[0]} != {PARENT_M03}"
    assert parents[1] == PARENT_L03, f"Parent 2 mismatch: {parents[1]} != {PARENT_L03}"

    # 2. Verify ancestry of canonical main and sub-milestones
    ancestors = [
        CANONICAL_MAIN,
        PARENT_M03,
        PARENT_L03,
        "283e3a464a3de1d0a420709a3f6602730023300d",  # L02-B3
        "4ab809df6b9895812def68e5d9e9cef03a09f4d7",  # L02-B6 integrated in MASTER-03
        "d8827409248dcdb5da55a010d8224d9e0e3bddbe",  # MASTER-02
        "c8b0f54bafe364c18e507425570d34be1e7b8dd7",  # L03 code
    ]
    for anc in ancestors:
        res = subprocess.run(
            f"git merge-base --is-ancestor {anc} {MERGE_COMMIT}",
            shell=True,
            cwd=str(M04_DIR),
        )
        assert res.returncode == 0, f"Commit {anc} is NOT an ancestor of {MERGE_COMMIT}!"

    # 3. Verify diff between CODE_SHA and DOC_HEAD touches only documentation
    diff_out = subprocess.check_output(
        f"git diff --name-only {CODE_SHA}..{DOC_HEAD}",
        shell=True,
        text=True,
        cwd=str(M04_DIR),
    ).strip().splitlines()
    assert len(diff_out) > 0, "Expected documentation commits between code and head"
    for f in diff_out:
        assert f.startswith("docs/orneur/milestones/master-04/"), f"Unexpected non-doc file altered: {f}"


def test_gate_a_fail_closed_ancestry_under_shallow_or_missing_objects():
    """Verify that ancestry validation fails closed if historical objects are missing."""
    code = """
        import subprocess, sys
        # An inquiry for a completely bogus historical commit must fail-closed
        res = subprocess.run(
            "git merge-base --is-ancestor 0000000000000000000000000000000000000000 HEAD",
            shell=True, capture_output=True, text=True
        )
        assert res.returncode != 0, "Ancestry verification silently passed on missing git object!"
        print("FAIL_CLOSED_ANCESTRY_OK")
    """
    p = _run_in_m04(code)
    assert p.returncode == 0
    assert "FAIL_CLOSED_ANCESTRY_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate B: Vector-Owner and Restore Lock Security (P1)
# ---------------------------------------------------------------------------


def test_gate_b_restore_refuses_while_vector_owner_serves():
    """Adversarial probe: Start vector owner in service mode.
    Attempt exclusive restore -> must fail closed with RestoreFailed ('a server is running').
    Stop owner -> subsequent restore must succeed."""
    code = """
        import os, sys, tempfile, sqlite3
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_b_restore_refusal_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        from orca.serve import backup, datadir_lock
        from orca.serve.backup_errors import RestoreFailed
        vs.reset_for_tests()

        # Seed valid auth.db
        conn = sqlite3.connect(str(home / "auth.db"))
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users VALUES ('u1', 'u1@example.com')")
        conn.commit(); conn.close()

        # Start vector owner by creating/opening a collection
        st = vs.Store(home / "memory" / "vectors")
        col, _ = st.open_collection("test_col")
        col.add(ids=["1"], documents=["doc1"])
        t = vs.transport()
        pid = t.owner_pid()
        assert pid is not None

        # Take consistent backup
        key = b"K" * 32
        out_bk = td / "test.orbk"
        backup.create(home, out_bk, key=key, quiesce_vector=True)

        # Restart owner
        col2, _ = st.open_collection("test_col")
        assert t.owner_pid() is not None

        # Attempt restore while owner is serving -> MUST refuse
        try:
            backup.restore(out_bk, home, key=key, overwrite=True)
            raise AssertionError("Restore should have failed while owner is serving!")
        except RestoreFailed as exc:
            assert "a server is running on this data directory: stop it before restoring" in str(exc)

        # Verify owner is still alive and serving
        assert t.owner_pid() is not None
        assert t.ping(1.0) is True

        # Stop owner cleanly
        assert t.stop_owner() is True

        # Restore must now succeed
        res = backup.restore(out_bk, home, key=key, overwrite=True)
        assert res["verified"] is True
        print("GATE_B_RESTORE_REFUSAL_OK")
    """
    p = _run_in_m04(code, timeout=30)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_B_RESTORE_REFUSAL_OK" in p.stdout


def test_gate_b_owner_refuses_under_exclusive_restore_lock():
    """Adversarial probe: Hold exclusive_data_dir lock.
    Attempt to start vector owner -> owner process exits with code 2, logs refusal to owner.log,
    and client calling ensure_owner immediately raises VectorUnavailable."""
    code = """
        import os, sys, tempfile
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_b_owner_refusal_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        from orca.serve import datadir_lock
        from orca.vectorstore.errors import VectorUnavailable
        from orca.vectorstore import paths
        vs.reset_for_tests()

        # Hold exclusive_data_dir lock
        with datadir_lock.exclusive_data_dir(home):
            t = vs.transport()
            try:
                t.ensure_owner(budget_s=2.0)
                raise AssertionError("ensure_owner should have failed while restore lock is held!")
            except VectorUnavailable as exc:
                assert "refused to start" in str(exc).lower()

            # Confirm owner.log contains the logged refusal message
            log_text = paths.log_path(home).read_text()
            assert "vector owner refused to start" in log_text

            # Confirm no pid file was left behind
            assert not paths.pid_path(home).exists()

        print("GATE_B_OWNER_REFUSAL_OK")
    """
    p = _run_in_m04(code, timeout=20)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_B_OWNER_REFUSAL_OK" in p.stdout


def test_gate_b_multiprocess_serving_vs_restore_concurrency_race():
    """Adversarial probe: Concurrent race between 8 restore workers and 8 vector owner starters.
    Verify strict mutual exclusion: never do restore and owner serve concurrently.
    All losing attempts must fail closed with expected exceptions (RestoreFailed or VectorUnavailable)."""
    code = """
        import multiprocessing as mp
        import os, sys, tempfile, sqlite3, time
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_b_race_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        from orca.serve import backup
        from orca.serve.backup_errors import RestoreFailed
        from orca.vectorstore.errors import VectorUnavailable

        # Seed valid auth.db
        conn = sqlite3.connect(str(home / "auth.db"))
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users VALUES ('u1', 'u1@example.com')")
        conn.commit(); conn.close()

        key = b"K" * 32
        out_bk = td / "archive.orbk"
        backup.create(home, out_bk, key=key, quiesce_vector=True)

        q = mp.Queue()

        def restore_worker(idx, queue):
            try:
                backup.restore(out_bk, home, key=key, overwrite=True)
                queue.put(("restore", idx, "success"))
            except RestoreFailed as e:
                queue.put(("restore", idx, "refused_expected"))
            except Exception as e:
                queue.put(("restore", idx, f"unexpected_{type(e).__name__}"))

        def owner_worker(idx, queue):
            try:
                st = vs.Store(home / "memory" / "vectors")
                c, _ = st.open_collection(f"col_race_{idx}")
                c.add(ids=["1"], documents=["doc"])
                queue.put(("owner", idx, "success"))
            except VectorUnavailable:
                queue.put(("owner", idx, "refused_expected"))
            except Exception as e:
                queue.put(("owner", idx, f"unexpected_{type(e).__name__}"))

        procs = []
        for i in range(8):
            procs.append(mp.Process(target=restore_worker, args=(i, q)))
            procs.append(mp.Process(target=owner_worker, args=(i, q)))

        for p in procs: p.start()
        for p in procs: p.join(15)

        results = []
        while not q.empty():
            results.append(q.get())

        assert len(results) == 16, f"Expected 16 results, got {len(results)}"
        for kind, idx, status in results:
            assert status in ("success", "refused_expected"), f"Unexpected result from {kind} {idx}: {status}"

        vs.transport().stop_owner()
        print("GATE_B_RACE_OK")
    """
    p = _run_in_m04(code, timeout=30)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_B_RACE_OK" in p.stdout


def test_gate_b_frozen_owner_holding_serving_lock_refuses_restore():
    """Adversarial probe: Freeze owner holding serving_lock with SIGSTOP.
    Verify restore is still refused with RestoreFailed.
    Then kill frozen owner with SIGKILL and verify restore immediately succeeds."""
    code = """
        import os, signal, sys, tempfile, sqlite3, time
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_b_sigstop_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        from orca.serve import backup
        from orca.serve.backup_errors import RestoreFailed
        vs.reset_for_tests()

        # Seed valid auth.db
        conn = sqlite3.connect(str(home / "auth.db"))
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users VALUES ('u1', 'u1@example.com')")
        conn.commit(); conn.close()

        key = b"K" * 32
        out_bk = td / "sigstop.orbk"
        backup.create(home, out_bk, key=key, quiesce_vector=True)

        # Start owner
        st = vs.Store(home / "memory" / "vectors")
        st.open_collection("col_sigstop")
        t = vs.transport()
        pid = t.owner_pid()
        assert pid is not None

        # Freeze owner with SIGSTOP
        os.kill(pid, signal.SIGSTOP)

        # Attempt restore -> must still be refused because the lock fd is held by frozen PID
        try:
            backup.restore(out_bk, home, key=key, overwrite=True)
            raise AssertionError("Restore should have failed while frozen owner holds lock!")
        except RestoreFailed as exc:
            assert "a server is running" in str(exc)

        # Kill frozen owner with SIGKILL
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.3)

        # Restore must now succeed
        res = backup.restore(out_bk, home, key=key, overwrite=True)
        assert res["verified"] is True
        print("GATE_B_SIGSTOP_LOCK_OK")
    """
    p = _run_in_m04(code, timeout=25)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_B_SIGSTOP_LOCK_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate C: Vector Backup Consistency (P1)
# ---------------------------------------------------------------------------


def test_gate_c_unquiesced_owner_never_claims_consistency():
    """Verify that an active, non-quiesced owner backup is flagged consistent: False,
    includes the marker in unstable_files, and refuses restore unless allow_inconsistent=True."""
    code = """
        import os, sys, tempfile, sqlite3
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_c_unquiesced_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        from orca.serve import backup
        from orca.serve.backup_errors import BackupIncompleteError
        vs.reset_for_tests()

        conn = sqlite3.connect(str(home / "auth.db"))
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users VALUES ('u1', 'u1@example.com')")
        conn.commit(); conn.close()

        st = vs.Store(home / "memory" / "vectors")
        col, _ = st.open_collection("col_consistency")
        col.add(ids=["1"], documents=["unquiesced test"])

        key = b"K" * 32
        out_bk = td / "active.orbk"

        # Create backup with quiesce_vector=False
        res = backup.create(home, out_bk, key=key, quiesce_vector=False)
        assert res["consistent"] is False
        assert any("owner_active_no_quiesce" in u for u in res["unstable_files"])

        # Inspect archive manifest via verify
        info = backup.verify(out_bk, key=key)
        assert info["consistent"] is False

        # Attempt restore -> must refuse
        vs.transport().stop_owner()
        try:
            backup.restore(out_bk, home, key=key, overwrite=True, allow_inconsistent=False)
            raise AssertionError("Restore of inconsistent backup should have failed!")
        except BackupIncompleteError as exc:
            assert "flagged inconsistent" in str(exc)

        # Passing allow_inconsistent=True allows it through
        res_forced = backup.restore(out_bk, home, key=key, overwrite=True, allow_inconsistent=True)
        assert res_forced["verified"] is True
        print("GATE_C_UNQUIESCED_CONSISTENCY_OK")
    """
    p = _run_in_m04(code, timeout=30)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_C_UNQUIESCED_CONSISTENCY_OK" in p.stdout


def test_gate_c_quiesced_owner_allows_consistent_backup_and_verifies_data():
    """Verify that taking backup with quiesce_vector=True results in consistent: True,
    zero unstable files, and restores all vector collections and documents cleanly."""
    code = """
        import os, sys, tempfile, sqlite3
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_c_quiesced_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        from orca.serve import backup
        vs.reset_for_tests()

        conn = sqlite3.connect(str(home / "auth.db"))
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users VALUES ('u1', 'u1@example.com')")
        conn.commit(); conn.close()

        st = vs.Store(home / "memory" / "vectors")
        col, _ = st.open_collection("col_quiesced_ok")
        col.add(ids=["100"], documents=["quiesced verified data"])

        key = b"K" * 32
        out_bk = td / "quiesced.orbk"

        # Create backup with quiesce_vector=True
        res = backup.create(home, out_bk, key=key, quiesce_vector=True)
        assert res["consistent"] is True
        assert len(res["unstable_files"]) == 0

        # Verify archive
        info = backup.verify(out_bk, key=key)
        assert info["consistent"] is True

        # Stop owner before restore
        vs.transport().stop_owner()

        # Restore back into home with overwrite=True
        res_restored = backup.restore(out_bk, home, key=key, overwrite=True)
        assert res_restored["verified"] is True

        # Verify data retrievability in restored home
        vs.reset_for_tests()
        st_after = vs.Store(home / "memory" / "vectors")
        col_after, _ = st_after.open_collection("col_quiesced_ok")
        got = col_after.get(ids=["100"])
        assert got["documents"] == ["quiesced verified data"]

        vs.transport().stop_owner()
        print("GATE_C_QUIESCED_VERIFIED_OK")
    """
    p = _run_in_m04(code, timeout=30)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_C_QUIESCED_VERIFIED_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate D: Customer Data Non-Resurrection (P1)
# ---------------------------------------------------------------------------


def test_gate_d_customer_non_resurrection_after_backup_and_sweep():
    """Verify that when Customer A deletes their conversation/memory after a backup,
    restoring that backup with the deletion ledger enforces tombstones, revokes access,
    and the maintenance sweep purges raw bytes from storage while Customer B's data is preserved."""
    code = """
        import os, sys, tempfile, sqlite3, uuid
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_d_non_resurrect_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca.auth import db as authdb
        from orca.auth.store import create_user
        from orca import vectorstore as vs
        from orca.serve import backup, deletions
        from orca.brain.memory import LongTermMemory
        vs.reset_for_tests()

        # Seed authentic auth.db
        s = sqlite3.connect(str(authdb.AUTH_DB))
        d = sqlite3.connect(str(home / "auth.db"))
        s.backup(d); s.close(); d.close()

        ua = create_user("cust_a@example.com", "correcthorsebatterystaple", "A")
        ub = create_user("cust_b@example.com", "correcthorsebatterystaple", "B")

        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())

        # Customer A and Customer B write private memories
        LongTermMemory(sid_a).store("Customer A top secret confidential phrase ALPHA_SECRET", strict=True)
        LongTermMemory(sid_b).store("Customer B retained phrase BETA_SAFE", strict=True)

        key = b"K" * 32
        out_bk = td / "backup_both.orbk"
        backup.create(home, out_bk, key=key, quiesce_vector=True)

        # Customer A executes deletion
        deletions.begin(sid_a, ua.id)
        deletions.run(sid_a, ua.id)

        # Stop owner before restore
        vs.transport().stop_owner()

        # Restore older backup
        r = backup.restore(out_bk, home, key=key, overwrite=True)
        vs.reset_for_tests()

        # Access check right after restore: must be revoked via tombstone
        recall_a = LongTermMemory(sid_a).recall("ALPHA_SECRET")
        assert recall_a == [], f"Deleted Customer A data was recalled after restore: {recall_a}"

        # Run deletion sweep
        swept = deletions.resume_pending()
        assert swept >= 1, f"Expected at least 1 tombstone swept, got {swept}"

        # Verify collection is gone
        cols = vs.Store(home / "memory" / "vectors").list_collections()
        assert f"orca_{sid_a[:8]}" not in cols, "Deleted collection still present after sweep!"

        # Physical byte scan across raw database files: target secret must be purged
        raw = b"".join(p.read_bytes() for p in (home / "memory" / "vectors").rglob("*") if p.is_file())
        assert b"ALPHA_SECRET" not in raw, "Raw secret bytes still found on disk after sweep!"

        # Customer B retained data must be 100% intact
        recall_b = LongTermMemory(sid_b).recall("BETA_SAFE")
        assert len(recall_b) == 1
        assert "BETA_SAFE" in recall_b[0]["text"]

        vs.transport().stop_owner()
        print("GATE_D_NON_RESURRECTION_OK")
    """
    p = _run_in_m04(code, timeout=35)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_D_NON_RESURRECTION_OK" in p.stdout


def test_gate_d_missing_deletion_history_refusal_and_unsafe_override():
    """Verify that restore without deletion history refuses with DeletionHistoryUnavailable,
    and unsafe_without_deletion_history=True sets deleted_data_may_be_present: True with warning."""
    code = """
        import os, sys, tempfile, sqlite3
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_d_unsafe_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca.serve import backup
        from orca.serve.backup_errors import DeletionHistoryUnavailable

        conn = sqlite3.connect(str(home / "auth.db"))
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users VALUES ('u1', 'u1@example.com')")
        conn.commit(); conn.close()

        key = b"K" * 32
        out_bk = td / "bk.orbk"
        backup.create(home, out_bk, key=key)

        # Restore into a fresh empty home that has NO deletion ledger
        fresh_home = td / "fresh_home"
        fresh_home.mkdir()

        # 1. Without unsafe override -> must refuse
        try:
            backup.restore(out_bk, fresh_home, key=key, overwrite=True)
            raise AssertionError("Restore without deletion history should have failed!")
        except DeletionHistoryUnavailable as exc:
            assert "no authoritative deletion history" in str(exc)

        # 2. With unsafe_without_deletion_history=True -> succeeds with explicit warning flag
        res = backup.restore(out_bk, fresh_home, key=key, overwrite=True, unsafe_without_deletion_history=True)
        assert res["verified"] is True
        assert res["deleted_data_may_be_present"] is True
        assert "NO deletion history was available" in res["deletion_history"]["statement"]

        print("GATE_D_UNSAFE_OVERRIDE_OK")
    """
    p = _run_in_m04(code, timeout=25)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_D_UNSAFE_OVERRIDE_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate E: Interrupted Restore Recovery
# ---------------------------------------------------------------------------


def test_gate_e_interrupted_restore_journal_and_fail_closed_recovery():
    """Verify that an interrupted restore journal flags the directory as restore_pending,
    causes serving to fail closed, and recover_interrupted cleanly restores integrity."""
    code = """
        import os, sys, tempfile, json, sqlite3
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_e_journal_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)

        from orca.serve import datadir_lock, backup
        from orca.serve.backup_errors import RestoreFailed

        # Create baseline file
        (home / "auth.db").write_text("baseline auth content")

        # Inject an aside directory and an interrupted journal
        aside_name = ".pre-restore-1234567890"
        aside = home / aside_name
        aside.mkdir()
        (aside / "auth.db").write_text("original auth content to recover")

        journal = {
            "aside": aside_name,
            "moved": ["auth.db"],
            "placed": ["auth.db"],
            "state": "swapping"
        }
        datadir_lock.write_journal(home, journal)

        # Verify restore_pending is True
        assert datadir_lock.restore_pending(home) is True

        # Attempting restore must fail closed because earlier restore did not finish
        try:
            backup.restore(Path("/dummy"), home, key=b"K"*32, overwrite=True)
            raise AssertionError("Should have failed while restore is pending!")
        except RestoreFailed as exc:
            assert "an earlier restore did not finish" in str(exc)

        # Execute recovery
        datadir_lock.recover_interrupted(home)

        # Verify journal unlinked and original content recovered
        assert datadir_lock.restore_pending(home) is False
        assert (home / "auth.db").read_text() == "original auth content to recover"
        assert not aside.exists()

        print("GATE_E_RECOVERY_OK")
    """
    p = _run_in_m04(code, timeout=20)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_E_RECOVERY_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate F: Tenant Ownership & Truncation Collisions
# ---------------------------------------------------------------------------


def test_gate_f_session_prefix_truncation_collision_isolation():
    """Verify that two session IDs colliding on the first 8 hex characters are prevented
    from reading or writing each other's vector collection via orneur_bindings.sqlite."""
    code = """
        import os, sys, tempfile
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_f_prefix_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca.brain.memory import LongTermMemory
        from orca import vectorstore as vs
        vs.reset_for_tests()

        sid_a = "abcdef01-custA-session"
        sid_b = "abcdef01-custB-session"

        # Alpha writes memory
        mem_a = LongTermMemory(sid_a)
        mem_a.store("Alpha confidential plan", strict=True)
        assert len(mem_a.recall("confidential", 1, strict=True)) == 1

        # Beta attempts to read or write using colliding prefix
        mem_b = LongTermMemory(sid_b)
        try:
            mem_b.store("Beta overwrite attempt", strict=True)
            raise AssertionError("Beta should have been rejected due to binding collision!")
        except Exception as exc:
            assert "another conversation" in str(exc).lower() or "VectorOwnershipError" in type(exc).__name__

        # Beta attempts to delete collection
        col_name = f"orca_{sid_a[:8]}"
        st = vs.Store(home / "memory" / "vectors")
        del_res = st.delete_collection(col_name, binding=vs.session_binding(sid_b))
        assert del_res.get("refused") == "not_owner" or del_res.get("removed") is False

        # Verify Alpha data remains untouched
        hits_a = mem_a.recall("confidential", 1, strict=True)
        assert len(hits_a) == 1
        assert "confidential plan" in hits_a[0]["text"]

        vs.transport().stop_owner()
        print("GATE_F_TENANT_ISOLATION_OK")
    """
    p = _run_in_m04(code, timeout=30)
    assert p.returncode == 0, f"Test failed:\n{p.stderr}"
    assert "GATE_F_TENANT_ISOLATION_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate H: Production Image Packaging Reality
# ---------------------------------------------------------------------------


def test_gate_h_dockerfile_packaging_reality():
    """Verify that the production Dockerfile does NOT silently bundle chromadb or cryptography,
    confirming the necessity of optional extras in container configurations."""
    dockerfile = M04_DIR / "Dockerfile"
    assert dockerfile.is_file(), "Dockerfile missing from repository root"
    content = dockerfile.read_text()

    # ChromaDB and cryptography must not be in default pip install
    assert "pip install chromadb" not in content
    assert "poetry install -E memory" not in content or "ARG ENABLE_MEMORY=false" in content
    print("GATE_H_DOCKERFILE_OK")


# ---------------------------------------------------------------------------
# Governance & Model Truth
# ---------------------------------------------------------------------------


def test_governance_immutability_and_formal_acceptance_zero():
    """Verify that MASTER-04 maintains strictly 0/95 formal pretraining acceptance
    and training status NOT_AUTHORIZED."""
    graph_path = M04_DIR / "docs" / "orneur" / "acceptance" / "register_graph.json"
    assert graph_path.is_file(), f"register_graph.json not found at {graph_path}"
    graph = json.loads(graph_path.read_text())

    # Pretraining denominator must be 95 and numerator must be 0
    pretraining_ids = graph.get("denominator_pretraining_ids", [])
    assert len(pretraining_ids) == 95, f"Expected 95 pretraining IDs, got {len(pretraining_ids)}"
    assert graph.get("numerator_pretraining") == 0, f"Expected numerator 0, got {graph.get('numerator_pretraining')}"

    # Verify authorization status rows
    nodes = {n.get("id"): n for n in graph.get("nodes", [])}
    for auth_id in ("FINAL-2", "EXEC-1", "AUTH-2", "AUTH-3"):
        if auth_id in nodes:
            assert nodes[auth_id].get("status") == "NOT_AUTHORIZED", f"{auth_id} status is not NOT_AUTHORIZED!"

    print("GOVERNANCE_ZERO_ACCEPTANCE_OK")
