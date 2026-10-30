"""LANDMARK-01 Wave 5: temporary chats stay temporary across real OS processes, crashes and racing commits.

Every actor is a separate Python process sharing one ORNEUR_HOME on disk (the same shape as two uvicorn workers). The assertions look at the
bytes on disk -- the SQLite authority tables, the JSONL export, the message-version files and the tombstone -- not at an API's opinion of them.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "tests" / "_temp_chat_worker.py"


def _env(home: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO), "ORNEUR_AUTH_SECRET": "x" * 40, **extra})
    return env


def _run(home: Path, mode: str, sid: str, uid: str = "temp-owner", *, wait: bool = True, **extra):
    proc = subprocess.Popen([sys.executable, str(WORKER), mode, sid, uid], cwd=REPO, env=_env(home, **extra),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if not wait:
        return proc
    out, err = proc.communicate(timeout=120)
    return proc.returncode, [json.loads(l) for l in out.splitlines() if l.startswith("{")], err


def _db_rows(home: Path, sid: str) -> dict:
    out = {}
    for db in home.rglob("*.db"):
        try:
            conn = sqlite3.connect(db)
            for table in ("conversation_turns", "session_authority", "session_export_state"):
                try:
                    out[table] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?", (sid,)).fetchone()[0]
                except sqlite3.Error:
                    pass
            conn.close()
        except sqlite3.Error:
            pass
    return out


def _files_mentioning(home: Path, sid: str) -> list[str]:
    hits = []
    for p in home.rglob("*"):
        if p.is_file() and not p.name.endswith((".db", ".db-wal", ".db-shm", ".sqlite3")) and (sid in p.name):
            hits.append(str(p.relative_to(home)))
    return hits


def _leaks(home: Path, needle: bytes) -> list[str]:
    found = []
    for p in home.rglob("*"):
        if p.is_file():
            try:
                if needle in p.read_bytes():
                    found.append(str(p.relative_to(home)))
            except OSError:
                pass
    return found


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "orneur-home"
    h.mkdir()
    return h


def test_crash_mid_closure_is_resumed_by_another_process_and_leaves_nothing(home):
    sid = "tmpmp001-" + uuid.uuid4().hex[:8]
    rc, out, err = _run(home, "open", sid)
    assert rc == 0 and out[0]["opened"] == "active" and out[1]["commit"] == "committed", (out, err[-400:])
    assert _db_rows(home, sid)["conversation_turns"] == 1

    rc, _, _ = _run(home, "crash_in_close", sid)
    assert rc == 9, "the injected crash did not happen inside the closure"
    tomb = json.loads(next((home).rglob(f"{sid}.json")).read_text())
    assert tomb["state"] == "closing", "a crash mid-closure must leave an explicit, resumable 'closing' marker, not a still-usable 'active' chat"

    # A DIFFERENT process meets the half-closed chat: it must finish the deletion and refuse to serve a turn.
    rc, out, err = _run(home, "enforce", sid)
    assert rc == 0, err[-400:]
    refusal = out[0]["enforce"]
    assert refusal and refusal["code"] == "temporary_closed", refusal
    tomb = json.loads(next((home).rglob(f"{sid}.json")).read_text())
    assert tomb["state"] == "closed"
    assert "secret question" not in json.dumps(tomb) and "secret answer" not in json.dumps(tomb)

    assert _db_rows(home, sid) == {"conversation_turns": 0, "session_authority": 0, "session_export_state": 0}
    assert _leaks(home, b"secret question") == [] and _leaks(home, b"secret answer") == []
    leftovers = [f for f in _files_mentioning(home, sid) if not f.endswith(f"{sid}.json")]
    assert leftovers == [], leftovers


def test_a_commit_racing_the_closure_never_survives_it(home):
    sid = "tmpmp002-" + uuid.uuid4().hex[:8]
    rc, out, err = _run(home, "open", sid)
    assert rc == 0 and out[1]["commit"] == "committed", (out, err[-400:])
    committer = _run(home, "committer", sid, wait=False)
    closer = _run(home, "close", sid, wait=False, CLOSE_DELAY="0.3")
    c_out, c_err = committer.communicate(timeout=120)
    k_out, k_err = closer.communicate(timeout=120)
    steps = [json.loads(l) for l in c_out.splitlines() if l.startswith("{")]
    assert steps, c_err[-400:]
    assert steps[-1]["outcome"] in ("refused", "no-authority") or steps[-1]["outcome"].startswith("commit-"), steps[-3:]
    closed = [json.loads(l) for l in k_out.splitlines() if l.startswith("{")][0]["closed"]
    assert closed["state"] == "closed" and closed["deleted"] is True
    # Whatever the interleaving, NOTHING of the conversation is left once the closure returned.
    assert _db_rows(home, sid) == {"conversation_turns": 0, "session_authority": 0, "session_export_state": 0}
    assert _leaks(home, b"secret question") == [] and _leaks(home, b"secret answer") == []


def test_two_processes_closing_the_same_chat_both_finish_cleanly(home):
    sid = "tmpmp003-" + uuid.uuid4().hex[:8]
    rc, out, err = _run(home, "open", sid)
    assert rc == 0 and out[1]["commit"] == "committed", (out, err[-400:])
    procs = [_run(home, "close", sid, wait=False) for _ in range(4)]
    results = []
    for p in procs:
        o, e = p.communicate(timeout=120)
        assert p.returncode == 0, e[-400:]
        results.append([json.loads(l) for l in o.splitlines() if l.startswith("{")][0]["closed"])
    assert all(r["state"] == "closed" for r in results), results
    assert _db_rows(home, sid) == {"conversation_turns": 0, "session_authority": 0, "session_export_state": 0}
    assert _leaks(home, b"secret question") == []


def test_a_closed_chat_cannot_be_reopened_or_adopted(home):
    sid = "tmpmp004-" + uuid.uuid4().hex[:8]
    _run(home, "open", sid)
    _run(home, "close", sid)
    rc, out, err = _run(home, "open", sid)           # activate() must refuse to bring a finished chat back
    assert rc != 0 and "temporary_finished" in err or "already finished" in err, (rc, out, err[-300:])
    assert _db_rows(home, sid) == {"conversation_turns": 0, "session_authority": 0, "session_export_state": 0}


def test_a_worker_that_arrives_after_the_closure_is_refused_and_leaves_no_rows_behind(home):
    """CI found the interleaving where the racing committer ACQUIRES authority just after the closure finished: the refusal must not leave the
    content-free authority / export rows it just re-created (deterministic version: close first, then commit)."""
    sid = "tmpmp005-" + uuid.uuid4().hex[:8]
    rc, out, err = _run(home, "open", sid)
    assert rc == 0 and out[1]["commit"] == "committed", (out, err[-300:])
    rc, out, _ = _run(home, "close", sid)
    assert rc == 0 and out[0]["closed"]["state"] == "closed"
    rc, steps, err = _run(home, "committer", sid)
    assert rc == 0 and steps[0]["outcome"] == "refused", (steps, err[-300:])
    assert _db_rows(home, sid) == {"conversation_turns": 0, "session_authority": 0, "session_export_state": 0}
    assert _leaks(home, b"secret question") == []
