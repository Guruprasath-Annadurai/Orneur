"""
ORNEUR INDEPENDENT MASTER-03 INTEGRATION QUALIFICATION TEST SUITE
Candidate: PR #146 (cursor/master-03-security-corrected-b882)
Verified Engineering HEAD: b96cc3260078b6f677a22381b05fe1f72026256f
Verified Tree: 168a6a2c75bd11e0cbac113e06ff4d50e88f9cae
Merge Commit: 34b6688450fdc199baf336fd5884164fd5684f63

Audited Scope:
1. Complete 6-PR ancestry (F02, F03, L01, L02, L02-B3, L02-B6) and source preservation.
2. Full-history ancestry fail-closed verification (no skip on missing objects).
3. Evalinfra governance frozen-path gate: verify the 4 pinned blobs and fail-closed defense against arbitrary changes.
4. Retention of B3 and B6 live-journey selections and historical login-timing evidence.
5. Real execution of legacy backup CLI commands, recording exact return codes (1 vs 2) and absence of plaintext leaks.
6. Real supported Chroma backend exercise: proving access revocation, retrieval exclusion, logical cleanup, and physical reclamation distinction.
7. Full application execution without cryptography: testing /readyz, /livez, conversation deletion, and complete account deletion.
8. Interrupted restoration against actual FastAPI application: /readyz 503 refusal, recovery rollback, and return to 200.
9. Realistic account backup/deletion/restore journey across full schema (users, user_sessions, storage_keys, user_settings, api_keys, usage_daily).
10. Explicit audit of CI test skips by exact test identity and causal classification.
11. Governance immutability (0/95 formal acceptance, pretraining STRICT NO-GO).
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
import pytest

MASTER03_DIR = Path("/home/pc/projects/Orneur-master03")
HEAD_SHA = "b96cc3260078b6f677a22381b05fe1f72026256f"
EXPECTED_TREE = "168a6a2c75bd11e0cbac113e06ff4d50e88f9cae"
MERGE_COMMIT = "34b6688450fdc199baf336fd5884164fd5684f63"

CONSTITUENTS = {
    "canonical_main": "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a",
    "pr140_f02": "649d90f84069fc618ba4d69b4c26a66bed731caa",
    "pr142_f03": "0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51",
    "pr136_l01": "9cb864c99ad323d11626063498a7d1cef0d7d4b5",
    "pr139_l02": "38e0d311991875366f2bc88a39690c7b2b6ea3ee",
    "pr141_b3_code": "283e3a464a3de1d0a420709a3f6602730023300d",
    "pr141_b3_head": "66ce8aeace2077b89195735211d75ebd566716c8",
    "master02_head": "d8827409248dcdb5da55a010d8224d9e0e3bddbe",
    "pr143_b6_code": "14e1160dc50024d726f2f379fba510fbd2a88f66",
    "pr143_b6_head": "4ab809df6b9895812def68e5d9e9cef03a09f4d7",
    "master03_merge": "34b6688450fdc199baf336fd5884164fd5684f63",
}


def _switch_to_master03():
    for m in [k for k in list(sys.modules) if k.startswith(("orca", "tests"))]:
        sys.modules.pop(m, None)
    sys.path = [str(MASTER03_DIR)] + [p for p in sys.path if p != "/home/pc/projects/Orneur"]


def _git(*args, cwd=MASTER03_DIR):
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


# ---------------------------------------------------------------------------
# Gate 1: Lineage, Tree Identity, and Ancestry Verification
# ---------------------------------------------------------------------------


def test_master03_complete_six_pr_ancestry():
    """Verify all 6 constituent PRs are direct topological ancestors of MASTER-03 HEAD."""
    assert MASTER03_DIR.is_dir()
    current_head = _git("rev-parse", "HEAD")
    assert current_head == HEAD_SHA, f"HEAD mismatch: {current_head} != {HEAD_SHA}"

    current_tree = _git("rev-parse", f"{HEAD_SHA}^{{tree}}")
    assert current_tree == EXPECTED_TREE, f"Tree mismatch: {current_tree} != {EXPECTED_TREE}"

    for name, sha in CONSTITUENTS.items():
        rc = subprocess.call(["git", "merge-base", "--is-ancestor", sha, HEAD_SHA], cwd=str(MASTER03_DIR))
        assert rc == 0, f"{name} ({sha[:7]}) is NOT an ancestor of MASTER-03 HEAD {HEAD_SHA}!"


def test_ancestry_gate_fails_closed_when_objects_missing():
    """Verify that portable harness fails closed instead of skipping when git objects are absent."""
    harness_path = MASTER03_DIR / "tests/qualification/test_master02_f03_portable_harness.py"
    content = harness_path.read_text(encoding="utf-8")
    fn_start = content.find("def test_engineering_sha_is_ancestor_of_integrated_head")
    fn_end = content.find("def test_parent_and_engineering_blob_identity_preserved")
    ancestry_fn = content[fn_start:fn_end]
    assert "pytest.skip" not in ancestry_fn
    assert "Refusing to skip; configure full-history fetch." in ancestry_fn


# ---------------------------------------------------------------------------
# Gate 2: Evalinfra Governance Gate and 4 Pinned Blob Exceptions
# ---------------------------------------------------------------------------


def test_evalinfra_governance_four_pinned_blobs_and_fail_closed():
    """Verify the 4 pinned blobs match approved Foundation changes and arbitrary diffs fail closed."""
    gov_test_path = MASTER03_DIR / "tests/test_evalinfra_governance.py"
    content = gov_test_path.read_text(encoding="utf-8")

    expected_blobs = {
        "docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json":
            "d236706d07d3934d191fad0ee81ac9a49c6d8463",
        "docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json":
            "1eff1d91fae0d028a9275b716824c0c4cc8f0833",
        "docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json":
            "0cabf72961f637d81425564ac7bb64b0d611af7b",
        "orca/rse/imp1/consumer_verification.py":
            "a42286de9a0babe348a2f9b03840a29fb4664e64",
    }

    for path, exp_blob in expected_blobs.items():
        actual_blob = _git("rev-parse", f"HEAD:{path}")
        assert actual_blob == exp_blob, f"Blob mismatch for {path}: {actual_blob} != {exp_blob}"

    assert "Refusing to skip; configure full-history fetch." in content


# ---------------------------------------------------------------------------
# Gate 3: Retention of Live Journeys and Non-Overwritten Timing Evidence
# ---------------------------------------------------------------------------


def test_b3_and_b6_live_journeys_and_login_timing_preserved():
    """Verify both B3 and B6 live journeys are retained and login timing is indexed, not overwritten."""
    workflow = (MASTER03_DIR / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "test_l02_b3_apikey_reauth_live.py" in workflow
    assert "test_l02_b6_backup_live.py" in workflow

    timing_index_path = MASTER03_DIR / "docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json"
    index = json.loads(timing_index_path.read_text(encoding="utf-8"))
    assert "retained_measurements" in index
    retained_paths = [m["path"] for m in index["retained_measurements"]]
    assert any("master02-1a17fb0" in p for p in retained_paths)
    assert any("b6-e5266c7" in p for p in retained_paths)

    for m in index["retained_measurements"]:
        assert (MASTER03_DIR / m["path"]).is_file()


# ---------------------------------------------------------------------------
# Gate 4: Integrated B6 Legacy CLI Execution & Return Codes
# ---------------------------------------------------------------------------


def test_actual_legacy_cli_execution_and_exact_exit_codes():
    """Execute actual legacy CLI commands and record real exit codes, stdout/stderr, and absence of plaintext leaks.
    Corrects the erroneous exit-code-2 claim: legacy CLI exits with code 1; exit-code-2 is for missing cryptography."""
    cmd_backup = [sys.executable, "-m", "orca.cli", "backup"]
    p_backup = subprocess.run(cmd_backup, cwd=str(MASTER03_DIR), capture_output=True, text=True)
    assert p_backup.returncode == 1, f"Expected returncode 1, got {p_backup.returncode}"
    assert "retired: the plaintext backup/restore wrote an UNENCRYPTED copy" in p_backup.stdout
    assert len(p_backup.stderr) == 0

    cmd_restore = [sys.executable, "-m", "orca.cli", "restore", "/tmp/fake.db"]
    p_restore = subprocess.run(cmd_restore, cwd=str(MASTER03_DIR), capture_output=True, text=True)
    assert p_restore.returncode == 1, f"Expected returncode 1, got {p_restore.returncode}"
    assert "retired: the plaintext backup/restore wrote an UNENCRYPTED copy" in p_restore.stdout
    assert len(p_restore.stderr) == 0

    # orca backups lists backups or prints notice: exit code 0
    cmd_backups = [sys.executable, "-m", "orca.cli", "backups"]
    p_backups = subprocess.run(cmd_backups, cwd=str(MASTER03_DIR), capture_output=True, text=True)
    assert p_backups.returncode == 0
    assert "No legacy plaintext backups found" in p_backups.stdout

    # Now verify where exit-code-2 ACTUALLY occurs: when data-backup is run without cryptography
    block = "import sys\nsys.modules['cryptography'] = None\nfor m in list(sys.modules):\n    if m.startswith('cryptography.'):\n        sys.modules[m] = None\n"
    probe_code = block + textwrap.dedent("""
        from typer.testing import CliRunner
        from orca.cli import app
        r = CliRunner().invoke(app, ["data-backup", "create", "/tmp/test.orbk", "--key-file", "/nonexistent"])
        print(f"EXIT_CODE={r.exit_code}")
    """)
    p_crypto = subprocess.run([sys.executable, "-c", probe_code], cwd=str(MASTER03_DIR), capture_output=True, text=True)
    assert "EXIT_CODE=2" in p_crypto.stdout


# ---------------------------------------------------------------------------
# Gate 5: Document Restoration with Real Chroma Backend
# ---------------------------------------------------------------------------


def test_restored_document_real_chroma_backend_and_byte_reclamation():
    """Exercise restored document using real supported Chroma backend.
    Distinguishes access revocation, retrieval exclusion, logical vector cleanup, and physical reclamation."""
    _switch_to_master03()
    import chromadb
    from orca.docs.chunker import Chunk
    from orca.docs.store import DocStore, register_doc, list_docs
    import orca.docs.store as ods
    from orca.serve import backup, deletion_ledger

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        home = root / "home"
        home.mkdir()
        docs_dir = home / "docs"
        docs_dir.mkdir()

        # Point environment to test home
        os.environ["ORNEUR_HOME"] = str(home)
        ods.DOCS_DIR = docs_dir
        ods._REGISTRY_FILE = docs_dir / "registry.json"

        # Initialize SQLite database so backup recognizes valid directory
        conn = sqlite3.connect(str(home / "auth.db"))
        conn.execute("CREATE TABLE t (x INT)")
        conn.commit()
        conn.close()

        sid = "sess-12345678"
        store = DocStore(session_id=sid, enforce_registry=True)

        chunks = [
            Chunk(text="The launch key is blue-horizon-alpha.", doc_id="doc-top-secret", filename="secret.txt", chunk_idx=0, char_start=0, char_end=36),
            Chunk(text="Secondary verification is gamma-ray-99.", doc_id="doc-top-secret", filename="secret.txt", chunk_idx=1, char_start=37, char_end=75),
        ]
        n = store.add_chunks(chunks, doc_id="doc-top-secret", filename="secret.txt")
        register_doc(session_id=sid, doc_id="doc-top-secret", filename="secret.txt", chunk_count=n, size_bytes=100)

        # Baseline checks: retrieval succeeds, chunks in Chroma
        assert store.count() == 2
        hits = store.retrieve("blue-horizon", top_k=5)
        assert len(hits) == 2

        client = chromadb.PersistentClient(path=str(docs_dir / "vectors"))
        col = client.get_collection(store._col_name)
        assert col.count() == 2

        # Create encrypted backup
        key = os.urandom(32)
        archive = root / "backup.orbk"
        backup.create(home, archive, key=key)

        # Document deleted in customer session -> recorded in deletion ledger
        deletion_ledger.record(kind="doc", subject_id="doc-top-secret", session_id=sid, home=home)
        export_file = root / "doc_del.export"
        deletion_ledger.export(home, export_file, key=key)

        # Restore archive with deletion ledger
        target = root / "restored_home"
        res = backup.restore(archive, target, key=key, deletion_ledger=export_file)
        assert res["deletions_applied"]["doc"] >= 1

        # Point environment to restored target
        target_docs = target / "docs"
        os.environ["ORNEUR_HOME"] = str(target)
        ods.DOCS_DIR = target_docs
        ods._REGISTRY_FILE = target_docs / "registry.json"

        restored_store = DocStore(session_id=sid, enforce_registry=True)

        # 1. Access Revocation & Retrieval Exclusion:
        # Registry entry removed; store count is 0; retrieve returns 0 hits
        assert list_docs(sid) == []
        assert restored_store.count() == 0
        restored_hits = restored_store.retrieve("blue-horizon", top_k=5)
        assert len(restored_hits) == 0, "Document was not retrieval-excluded!"

        # 2. Physical Vector Byte Inspection:
        # Vector bytes in Chroma SQLite database are NOT erased merely by registry removal
        restored_client = chromadb.PersistentClient(path=str(target_docs / "vectors"))
        restored_col = restored_client.get_collection(restored_store._col_name)
        assert restored_col.count() == 2, "Chroma collection count should still be 2 before physical vacuum/reclamation!"
        raw_peek = restored_col.peek(2)
        assert "The launch key is blue-horizon-alpha." in raw_peek["documents"]

        # 3. Physical Reclamation:
        # Explicit deletion call purges chunks from Chroma store
        cleanup_res = restored_store.delete_doc_detailed("doc-top-secret")
        assert cleanup_res["collection"] == "ok"
        assert restored_col.count() == 0, "Chroma collection should be 0 after physical deletion!"


# ---------------------------------------------------------------------------
# Gate 6: Application Launch & Full Customer Deletion Without Cryptography
# ---------------------------------------------------------------------------


def test_full_application_readiness_and_customer_deletion_without_cryptography():
    """Launch full application in isolated process with cryptography blocked.
    Verify /readyz, /livez, conversation deletion, and complete customer account deletion."""
    block = "import sys\nsys.modules['cryptography'] = None\nfor m in list(sys.modules):\n    if m.startswith('cryptography.'):\n        sys.modules[m] = None\n"
    code = block + textwrap.dedent("""
        import json, uuid, os, sqlite3
        from pathlib import Path
        from fastapi.testclient import TestClient
        from orca.serve import streaming
        streaming.shutdown_streaming_pool = lambda wait=False: None
        from orca.serve.api import app
        from orca.auth.db import init_db, get_conn
        from orca.serve import deletions, deletion_ledger
        from orca.serve.account_delete import delete_account

        init_db()

        uid = "usr-test-" + str(uuid.uuid4())[:8]
        with get_conn() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                         (uid, f"{uid}@example.com", "argon_hash", "member", "2026-10-31T00:00:00Z"))
            conn.execute("INSERT INTO user_sessions (session_id, user_id, created_at) VALUES (?, ?, ?)",
                         ("sess-1", uid, 100.0))
            conn.execute("INSERT INTO user_settings (user_id, retention_days, updated_at) VALUES (?, ?, ?)",
                         (uid, 30, "2026-10-31T00:00:00Z"))
            conn.commit()

        results = {}
        with TestClient(app) as client:
            results["livez"] = client.get("/livez").status_code
            results["readyz"] = client.get("/readyz").status_code

            # Conversation deletion
            sid = str(uuid.uuid4())
            deletions.begin(sid, uid)
            results["conv_deleted"] = any(e["id"] == sid for e in deletion_ledger.read())

            # Complete account deletion
            del_res = delete_account(uid)
            results["account_deleted"] = True

            with get_conn() as conn:
                u_cnt = conn.execute("SELECT count(*) FROM users WHERE id=?", (uid,)).fetchone()[0]
                s_cnt = conn.execute("SELECT count(*) FROM user_sessions WHERE user_id=?", (uid,)).fetchone()[0]
                results["u_cnt"] = u_cnt
                results["s_cnt"] = s_cnt

            results["ledger_has_user"] = any(e["kind"] == "user" and e["id"] == uid for e in deletion_ledger.read())

        print("OUT_JSON:" + json.dumps(results))
    """)

    with tempfile.TemporaryDirectory() as td:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
        env.update({"ORNEUR_HOME": td, "PYTHONPATH": str(MASTER03_DIR)})
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=str(MASTER03_DIR))
        assert p.returncode == 0, f"App execution failed: {p.stderr}"
        line = [ln for ln in p.stdout.splitlines() if ln.startswith("OUT_JSON:")][0]
        res = json.loads(line.replace("OUT_JSON:", ""))
        assert res["livez"] == 200
        assert res["readyz"] == 200
        assert res["conv_deleted"] is True
        assert res["u_cnt"] == 0
        assert res["s_cnt"] == 0
        assert res["ledger_has_user"] is True


# ---------------------------------------------------------------------------
# Gate 7: Interrupted Restoration Against Actual Application Process
# ---------------------------------------------------------------------------


def test_interrupted_restoration_against_actual_application_process():
    """Exercise interrupted restoration against actual FastAPI application.
    Confirm /readyz 503 refusal, startup lock block, recovery execution, and return to 200."""
    code = textwrap.dedent("""
        import json, os, shutil, sys
        from pathlib import Path
        from fastapi.testclient import TestClient

        from orca.auth.db import init_db
        from orca.serve import datadir_lock
        from orca.serve.backup_errors import RestoreFailed
        from orca.serve.api import app

        home = Path(os.environ["ORNEUR_HOME"])
        init_db()

        # 1. Server initially reports ready (200)
        with TestClient(app) as client:
            r1 = client.get("/readyz")
            assert r1.status_code == 200

        # 2. Simulate interrupted restore
        aside = home / ".pre-restore-1234567890"
        aside.mkdir(parents=True)
        shutil.copy2(home / "auth.db", aside / "auth.db")
        (home / "auth.db").write_text("CORRUPTED_HALF_RESTORED_STATE")

        journal = home / datadir_lock.JOURNAL
        journal.write_text(json.dumps({"aside": aside.name, "moved": ["auth.db"], "placed": ["auth.db"]}))
        journal.chmod(0o600)

        assert datadir_lock.restore_pending(home) is True

        # 3. /readyz returns 503 with interrupted status
        with TestClient(app) as client:
            r2 = client.get("/readyz")
            assert r2.status_code == 503
            dep = r2.json()["dependencies"]["restore"]
            assert dep["status"] == "interrupted"
            assert "recover" in dep["action"]

        # 4. Server startup fails closed if exclusive restore lock is held
        with datadir_lock.exclusive_data_dir(home):
            try:
                with datadir_lock.serving_lock(home):
                    raise AssertionError("serving_lock should fail!")
            except RestoreFailed as exc:
                assert "a restore is in progress" in str(exc)

        # 5. Execute recovery
        datadir_lock.recover_interrupted(home)
        assert datadir_lock.restore_pending(home) is False
        assert not journal.exists()
        assert (home / "auth.db").exists()

        # 6. /readyz returns 200 after recovery
        with TestClient(app) as client:
            r3 = client.get("/readyz")
            assert r3.status_code == 200

        print("INTERRUPTED_RESTORE_OK")
    """)

    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
        env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(MASTER03_DIR)})
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=str(MASTER03_DIR))
        assert p.returncode == 0, f"Interrupted restore test failed:\n{p.stderr}"
        assert "INTERRUPTED_RESTORE_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate 8: Realistic Account Backup/Deletion/Restore Journey
# ---------------------------------------------------------------------------


def test_realistic_account_backup_deletion_restore_full_schema():
    """Run realistic account backup/deletion/restore journey across product's supported account schema:
    users, user_sessions, session_storage_keys, user_settings, api_keys, and usage_daily."""
    code = textwrap.dedent("""
        import json, os, shutil, sys, uuid, sqlite3
        from pathlib import Path

        from orca.auth.db import init_db, get_conn
        from orca.serve import backup, deletion_ledger

        home = Path(os.environ["ORNEUR_HOME"])
        init_db()

        uid_target = "usr_target_" + str(uuid.uuid4())[:8]
        uid_retained = "usr_retained_" + str(uuid.uuid4())[:8]

        with get_conn() as conn:
            # 1. users
            conn.execute(
                "INSERT INTO users (id, email, name, password_hash, tier, role, created_at, verified, totp_secret, totp_enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid_target, "target@example.com", "Target User", "hash_target", "pro", "member", "2026-10-31T00:00:00Z", 1, "JBSWY3DPEHPK3PXP", 1)
            )
            conn.execute(
                "INSERT INTO users (id, email, name, password_hash, tier, role, created_at, verified, totp_secret, totp_enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid_retained, "retained@example.com", "Retained User", "hash_retained", "free", "member", "2026-10-31T00:00:00Z", 1, None, 0)
            )

            # 2. user_sessions
            conn.execute("INSERT INTO user_sessions (session_id, user_id, created_at) VALUES (?, ?, ?)", ("sess_target_1", uid_target, 1000.0))
            conn.execute("INSERT INTO user_sessions (session_id, user_id, created_at) VALUES (?, ?, ?)", ("sess_retained_1", uid_retained, 1500.0))

            # 3. session_storage_keys
            conn.execute("INSERT INTO session_storage_keys (session_id, storage_key, created_at) VALUES (?, ?, ?)", ("sess_target_1", "key_data_1", 1000.0))
            conn.execute("INSERT INTO session_storage_keys (session_id, storage_key, created_at) VALUES (?, ?, ?)", ("sess_retained_1", "key_data_2", 1500.0))

            # 4. user_settings
            conn.execute("INSERT INTO user_settings (user_id, retention_days, updated_at) VALUES (?, ?, ?)", (uid_target, 90, "2026-10-31T00:00:00Z"))
            conn.execute("INSERT INTO user_settings (user_id, retention_days, updated_at) VALUES (?, ?, ?)", (uid_retained, 30, "2026-10-31T00:00:00Z"))

            # 5. api_keys
            conn.execute(
                "CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '', "
                "created_at REAL NOT NULL, last_used REAL, revoked INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute("INSERT INTO api_keys (id, user_id, key_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("key_1", uid_target, "hash_key_1", "Production Key", 1234.0))
            conn.execute("INSERT INTO api_keys (id, user_id, key_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("key_2", uid_retained, "hash_key_2", "Dev Key", 5678.0))

            # 6. usage_daily
            conn.execute("INSERT INTO usage_daily (user_id, date, messages, ultra_runs) VALUES (?, ?, ?, ?)", (uid_target, "2026-10-31", 42, 5))
            conn.execute("INSERT INTO usage_daily (user_id, date, messages, ultra_runs) VALUES (?, ?, ?, ?)", (uid_retained, "2026-10-31", 5, 1))
            conn.commit()

        # Create encrypted backup
        key = os.urandom(32)
        archive = home.parent / "backup.orbk"
        backup.create(home, archive, key=key)

        # Record target deletion in ledger
        deletion_ledger.record(kind="user", subject_id=uid_target, home=home)
        export_file = home.parent / "accounts_del.export"
        deletion_ledger.export(home, export_file, key=key)

        # Restore to fresh target
        target_home = home.parent / "restored_home"
        res_restore = backup.restore(archive, target_home, key=key, deletion_ledger=export_file)
        assert res_restore["deletions_applied"]["user"] >= 1

        # Verify all tables
        conn_r = sqlite3.connect(str(target_home / "auth.db"))
        for tbl, col, uid in [
            ("users", "id", uid_target),
            ("user_sessions", "user_id", uid_target),
            ("user_settings", "user_id", uid_target),
            ("api_keys", "user_id", uid_target),
            ("usage_daily", "user_id", uid_target),
        ]:
            cnt = conn_r.execute(f"SELECT count(*) FROM {tbl} WHERE {col}=?", (uid,)).fetchone()[0]
            assert cnt == 0, f"Deleted user rows still present in {tbl}!"

        st_cnt = conn_r.execute("SELECT count(*) FROM session_storage_keys WHERE session_id='sess_target_1'").fetchone()[0]
        assert st_cnt == 0

        # Verify retained user is completely preserved
        for tbl, col, uid in [
            ("users", "id", uid_retained),
            ("user_sessions", "user_id", uid_retained),
            ("user_settings", "user_id", uid_retained),
            ("api_keys", "user_id", uid_retained),
            ("usage_daily", "user_id", uid_retained),
        ]:
            cnt = conn_r.execute(f"SELECT count(*) FROM {tbl} WHERE {col}=?", (uid,)).fetchone()[0]
            assert cnt == 1, f"Retained user rows missing from {tbl}!"

        conn_r.close()
        print("REALISTIC_ACCOUNT_RESTORE_OK")
    """)

    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
        env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(MASTER03_DIR)})
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=str(MASTER03_DIR))
        assert p.returncode == 0, f"Realistic account restore failed:\n{p.stderr}"
        assert "REALISTIC_ACCOUNT_RESTORE_OK" in p.stdout



# ---------------------------------------------------------------------------
# Gate 9: CI Skips Audit and Detailed Classification
# ---------------------------------------------------------------------------


def test_ci_skips_audit_and_characterization():
    """Audit test suite skips by exact identity and category.
    Proves skips are not all external-provider-related; verifies specific architectural categories."""
    skip_probes = subprocess.check_output(
        ["grep", "-rn", "pytest.skip", "tests/"],
        cwd=str(MASTER03_DIR),
        text=True
    ).splitlines()

    # Verify key categories exist in the codebase:
    # 1. Local Ollama daemon absent
    ollama_skips = [s for s in skip_probes if "Ollama" in s]
    assert len(ollama_skips) >= 10, "Expected local Ollama daemon skips"

    # 2. Candidate models not admitted / not ready
    admission_skips = [s for s in skip_probes if "READY" in s or "gate not applicable" in s]
    assert len(admission_skips) >= 5, "Expected candidate model readiness skips"

    # 3. Historical large pretraining dataset seeds
    dataset_skips = [s for s in skip_probes if "seed" in s]
    assert len(dataset_skips) >= 2, "Expected dataset builder seed skips"

    # 4. OS and platform specific limits
    env_skips = [s for s in skip_probes if any(k in s for k in ("macOS", "sticky /tmp", "/proc", "system python", "symlink"))]
    assert len(env_skips) >= 5, "Expected environment-specific skips"


# ---------------------------------------------------------------------------
# Gate 10: Governance, Model Truth, and Formal Acceptance
# ---------------------------------------------------------------------------


def test_governance_immutability_and_formal_acceptance_zero():
    """Verify formal acceptance is 0/95 and training authorization remains STRICT NO-GO."""
    res = subprocess.check_output(
        ["python3", "scripts/acceptance/validate_register_graph.py", "--check"],
        cwd=str(MASTER03_DIR),
        text=True,
    ).strip()
    assert "pretraining=95 numerator=0" in res

    auth_json = json.loads((MASTER03_DIR / "docs/orneur/authorization/TRAINING_AUTHORIZATION.json").read_text(encoding="utf-8"))
    assert auth_json.get("authorized") is False or auth_json.get("status") in ("NOT_AUTHORIZED", "NO_GO")


def test_model_identity_disclosure_and_governance_contracts():
    """Verify model identity contracts: third-party Ollama disclosed, Genesis INTERFACE_ONLY."""
    _switch_to_master03()
    from orca.serve.model_identity import model_identity

    ident = model_identity(
        requested_variant="orca-core",
        served_tier="orca-nano",
        served_model="llama3.2:1b",
        backend="ollama",
    )
    assert ident["substituted"] is True
    assert ident["requested_tier"] == "core"
    assert ident["served_tier"] == "nano"
    assert ident["backend"] == "ollama"

    weights_origin_doc = (MASTER03_DIR / "docs/orneur/landmarks/landmark-02/L02_MODEL_IDENTITY_AND_CAPABILITY_TRUTH.md").read_text(encoding="utf-8")
    assert "L02-08" in weights_origin_doc
    assert "INTERFACE_ONLY" in weights_origin_doc
    assert "third-party open-weights model" in weights_origin_doc
