"""Worker termination is not the same thing as an authenticated cancellation."""
from __future__ import annotations

import os
import time
from pathlib import Path

from orca.docs.orphan_reconcile import reconcile_orphan_uploads
from orca.serve import generations


def _begin(home: Path):
    import orca.brain.memory as mem

    mem.MEMORY_DIR = home
    (home / "generations").mkdir(parents=True, exist_ok=True)
    return generations.begin(
        session_id="sess-a",
        user_id="user-a",
        delivery="upstream",
        cancellable=True,
    )


def test_disconnect_without_a_stop_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    ended = generations.end_worker(record["generation_id"], upstream="stopped")
    assert ended["state"] == "interrupted_unknown"
    assert ended["state"] != "cancelled"
    assert ended["cancel_requested"] is False


def test_unconfirmed_stop_stays_unknown_after_the_post(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    generations.end_worker(record["generation_id"], upstream="unconfirmed")
    view = generations.request_cancel(record["generation_id"])
    assert view["cancel_accepted"] is False
    assert view["code"] == "upstream_unconfirmed"
    stored = generations.read(record["generation_id"])
    assert stored["state"] == "interrupted_unknown"
    assert stored["cancel_requested"] is True
    again = generations.request_cancel(record["generation_id"])
    assert again["state"] == "interrupted_unknown"


def test_proven_stop_can_be_confirmed_by_a_later_post(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    generations.end_worker(record["generation_id"], upstream="stopped")
    view = generations.request_cancel(record["generation_id"])
    assert view["state"] == "cancelled"
    assert view["code"] == "cancel_confirmed"
    late = generations.finish(record["generation_id"], "completed")
    assert late["state"] == "cancelled"


def test_dead_lease_is_reconciled_as_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    live = tmp_path / "generations" / f"{record['generation_id']}.live"
    live.write_text("stale")
    reconciled = generations.reconcile_owner(record["generation_id"])
    assert reconciled["state"] == "interrupted_unknown"
    assert reconciled["reason"] == "worker_lost"
    assert reconciled["state"] != "cancelled"


def test_failed_temporary_closure_retries_only_for_the_recorded_owner(tmp_path, monkeypatch):
    import orca.brain.memory as mem
    from orca.serve import temporary_chat

    mem.MEMORY_DIR = tmp_path
    session_id = "temp-session-1"
    path = tmp_path / "temporary_chats" / f"{session_id}.json"
    path.parent.mkdir()
    path.write_text(
        '{"user_id":"owner-a","state":"failed","intended_state":"closed","transitions":[]}\n'
    )
    monkeypatch.setattr(temporary_chat, "_delete_contents", lambda *_args: None)
    monkeypatch.setattr(temporary_chat, "_transcript_gone", lambda *_args: True)
    recovered = temporary_chat.retry_failed_closure(session_id, "owner-a")
    assert recovered["state"] == "closed"
    assert recovered["deleted"] is True
    again = temporary_chat.retry_failed_closure(session_id, "owner-a")
    assert again["retried"] is False
    assert again["state"] == "closed"


def test_orphan_reconcile_deletes_only_an_old_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.docs.store.DOCS_DIR", tmp_path)
    monkeypatch.setattr("orca.docs.orphan_reconcile.DOCS_DIR", tmp_path)
    registry = tmp_path / "registry.json"
    registry.write_text("{}\n")
    fresh = tmp_path / "kw_abcd1234.jsonl.1.tmp"
    fresh.write_text("new")
    old = tmp_path / "kw_abcd1234.jsonl.2.tmp"
    old.write_text("old")
    os.utime(old, (time.time() - 120, time.time() - 120))
    report = reconcile_orphan_uploads(now=time.time(), apply=True)
    assert registry.exists()
    assert fresh.exists()
    assert not old.exists()
    assert str(old) in report["removed"]
    assert report["atomic"] is False
