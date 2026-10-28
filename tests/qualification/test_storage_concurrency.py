"""Independent Concurrency, Persistence & Storage Fault Laboratory.

Audits:
- Negative control: demonstrates uncommitted / non-transactional JSONL append vulnerabilities
- Positive control: verifies SQLite `conversation_turns` table schema and atomic commit_turn protocol (PR #131+)
- Fencing authority: verifies that a stale worker with failed authority_check is rejected
- Transaction rollback: verifies uncommitted turn rows roll back cleanly on crash
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
import pytest

from orca.serve import conversations

HAS_SQLITE_TURNS = hasattr(conversations, "commit_turn")


class TestStorageConcurrencyAndRecovery:
    def test_negative_control_legacy_jsonl_append_lacks_transactional_rollback(self, tmp_path: Path, monkeypatch):
        """Negative control: demonstrates that direct filesystem JSONL appending lacks WAL transaction rollback."""
        monkeypatch.setattr(conversations, "_dir", lambda: tmp_path)
        session_id = "sess-legacy-fault-001"

        # Append one turn
        conversations.append(session_id, "user", "Hello legacy")
        p = conversations._path(session_id)
        assert p.exists()

        # Simulate partial/corrupt write that would occur during mid-write SIGKILL
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"role": "assistant", "content": "Partial unfin')

        # Reading lines fails or sees incomplete JSON
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        with pytest.raises(json.JSONDecodeError):
            json.loads(lines[1])

    def test_positive_control_sqlite_conversation_turns_schema(self, tmp_path: Path, monkeypatch):
        """Positive control: verifies that PR #131+ initializes the conversation_turns table."""
        if not HAS_SQLITE_TURNS:
            pytest.skip("SQLite authoritative commit_turn not in this candidate (introduced in PR #131)")

        monkeypatch.setattr(conversations, "_dir", lambda: tmp_path)
        conn = conversations._turns_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_turns';")
        row = cursor.fetchone()
        assert row is not None, "Canonical table conversation_turns must exist in SQLite database"

    def test_stale_worker_rejected_by_authority_check(self, tmp_path: Path, monkeypatch):
        """Positive control: verify commit_turn rejects stale worker when authority_check fails."""
        if not HAS_SQLITE_TURNS:
            pytest.skip("SQLite authoritative commit_turn not in this candidate")

        monkeypatch.setattr(conversations, "_dir", lambda: tmp_path)
        res = conversations.commit_turn(
            session_id="sess-fence-001",
            user_content="prompt text",
            assistant_content="response text",
            user_id="user-1",
            turn_id="turn-stale-001",
            authority_check=lambda: False,
        )
        assert res.ok is False
        assert res.reason == "stale_worker", f"Expected stale_worker rejection, got {res.reason}"

    def test_valid_worker_commits_turn_monotonically(self, tmp_path: Path, monkeypatch):
        """Positive control: valid worker commits turn and auto-increments revision."""
        if not HAS_SQLITE_TURNS:
            pytest.skip("SQLite authoritative commit_turn not in this candidate")

        monkeypatch.setattr(conversations, "_dir", lambda: tmp_path)
        res1 = conversations.commit_turn(
            session_id="sess-mono-001",
            user_content="turn 1 prompt",
            assistant_content="turn 1 answer",
            user_id="user-1",
            turn_id="turn-mono-001",
            authority_check=lambda: True,
        )
        assert res1.ok is True
        assert res1.revision == 1

        # Second turn
        res2 = conversations.commit_turn(
            session_id="sess-mono-001",
            user_content="turn 2 prompt",
            assistant_content="turn 2 answer",
            user_id="user-1",
            turn_id="turn-mono-002",
            authority_check=lambda: True,
        )
        assert res2.ok is True
        assert res2.revision == 2

    def test_sqlite_crash_mid_transaction_rollback_durability(self, tmp_path: Path):
        """Durable isolation: verifies that SQLite BEGIN IMMEDIATE rolls back uncommitted rows on crash."""
        db_path = tmp_path / "test_wal_crash.db"
        conn1 = sqlite3.connect(str(db_path))
        conn1.execute("PRAGMA journal_mode=WAL;")
        conn1.execute("CREATE TABLE conversation_turns (session_id TEXT, revision INT, user_content TEXT);")
        conn1.execute("INSERT INTO conversation_turns VALUES ('s1', 1, 'committed');")
        conn1.commit()
        conn1.close()

        # Simulate uncommitted transaction from a process that crashes
        crash_conn = sqlite3.connect(str(db_path))
        crash_conn.execute("BEGIN IMMEDIATE;")
        crash_conn.execute("INSERT INTO conversation_turns VALUES ('s1', 2, 'uncommitted_partial');")
        crash_conn.close()  # Connection dropped without commit -> rolled back by WAL

        verify_conn = sqlite3.connect(str(db_path))
        rows = verify_conn.execute("SELECT revision, user_content FROM conversation_turns WHERE session_id='s1';").fetchall()
        verify_conn.close()

        assert len(rows) == 1
        assert rows[0][0] == 1
        assert rows[0][1] == "committed"
