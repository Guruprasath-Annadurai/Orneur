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
    assert report["exactly_once"] is False
    replay = reconcile_orphan_uploads(now=time.time(), apply=True)
    assert replay["removed"] == []
    assert not old.exists()


def test_worker_failure_is_not_rewritten_as_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    failed = generations.finish(record["generation_id"], "failed", reason="inference_error")
    view = generations.request_cancel(record["generation_id"])
    assert failed["state"] == "failed"
    assert view["state"] == "failed"
    assert view["code"] == "generation_already_terminal"
    assert view["cancel_requested"] is True


def test_duplicate_cancel_leaves_a_confirmed_stop_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    generations.end_worker(record["generation_id"], upstream="stopped")
    first = generations.request_cancel(record["generation_id"])
    second = generations.request_cancel(record["generation_id"])
    assert first["state"] == "cancelled"
    assert second["state"] == "cancelled"
    assert second["code"] == "generation_already_terminal"
    assert second["reason"] == "cancel_requested"


def test_a_dropped_cancel_post_leaves_the_run_running(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    stored = generations.read(record["generation_id"])
    assert stored["state"] == "running"
    assert stored["cancel_requested"] is False
    assert stored["state"] != "cancelled"


def test_unknown_termination_survives_a_reread(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    generations.end_worker(record["generation_id"], upstream="unconfirmed")
    stored = generations.read(record["generation_id"])
    assert stored["state"] == "interrupted_unknown"
    again = generations.reconcile_owner(record["generation_id"])
    assert again["state"] == "interrupted_unknown"
    assert again["reason"] == "upstream_unconfirmed"


def test_stale_heartbeat_without_a_live_lock_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    path = tmp_path / "generations" / f"{record['generation_id']}.json"
    payload = generations.read(record["generation_id"])
    payload["updated_at"] = time.time() - 90
    path.write_text(__import__("json").dumps(payload))
    reconciled = generations.reconcile_owner(record["generation_id"])
    assert reconciled["state"] == "interrupted_unknown"
    assert reconciled["reason"] == "stale_lease"
    assert reconciled["state"] != "cancelled"


def test_a_lock_held_by_another_process_is_not_cancelled(tmp_path, monkeypatch):
    import subprocess
    import sys

    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    record, _created = _begin(tmp_path)
    live = tmp_path / "generations" / f"{record['generation_id']}.live"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl,os,sys,time; fd=os.open(sys.argv[1], os.O_RDWR|os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)",
            str(live),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        kept = generations.reconcile_owner(record["generation_id"])
        assert kept["state"] == "running"
        assert kept["cancel_requested"] is False
    finally:
        holder.terminate()
        holder.wait(timeout=5)
    released = generations.reconcile_owner(record["generation_id"])
    assert released["state"] == "interrupted_unknown"
    assert released["reason"] == "worker_lost"
    assert released["state"] != "cancelled"


def test_orphan_scan_reports_uncertain_stores_and_keeps_them(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("orca.docs.store.DOCS_DIR", docs)
    registry = docs / "registry.json"
    registry.write_text('{"sess-doc":[{"doc_id":"doc-1","filename":"a.txt"}]}\n')
    fallback = docs / "kw_sessdoc1.jsonl"
    fallback.write_text('{"doc_id":"doc-1","text":"kept"}\n{"doc_id":"doc-missing","text":"extra"}\n')
    vector = docs / "vectors" / "chroma.sqlite3"
    vector.parent.mkdir()
    vector.write_text("vector")
    link = docs / "linked.jsonl"
    link.symlink_to(fallback)
    index = tmp_path / "authorized_index" / "owner-a" / "bindings"
    index.mkdir(parents=True)
    binding = index / "session-1.json"
    binding.write_text('{"user_id":"owner-b","product_session_id":"session-1"}\n')
    pending = index.parent / "g1.chunks.jsonl.tmp"
    pending.write_text("partial")
    chats = tmp_path / "temporary_chats"
    chats.mkdir()
    failed = chats / "temp-1.json"
    failed.write_text('{"user_id":"owner-a","state":"failed","intended_state":"closed"}\n')
    dry = reconcile_orphan_uploads(
        now=time.time(),
        apply=False,
        docs_dir=docs,
        index_dir=tmp_path / "authorized_index",
        temporary_dir=chats,
    )
    assert dry["dry_run"] is True
    assert dry["removed"] == []
    classes = {row["class"] for row in dry["discrepancies"]}
    assert "document_only" in classes
    assert "storage_disagreement" in classes
    assert "vector_collection" in classes
    assert "owner_uncertain" in classes
    assert "incomplete_transaction" in classes
    assert "incomplete_deletion" in classes
    assert "uncertain_link" in classes
    assert "sess-doc" in dry["document_only_preserved"]
    assert all(row["remediation"] != "eligible" or row["class"] == "abandoned_temp" for row in dry["discrepancies"])
    applied = reconcile_orphan_uploads(
        now=time.time(),
        apply=True,
        docs_dir=docs,
        index_dir=tmp_path / "authorized_index",
        temporary_dir=chats,
    )
    assert applied["removed"] == []
    assert registry.exists() and fallback.exists() and vector.exists() and binding.exists() and pending.exists() and failed.exists()


def test_user_message_id_is_returned_only_after_the_transcript_confirms_it(tmp_path, monkeypatch):
    import orca.brain.memory as mem
    from orca.serve.api import _persist_turn
    from orca.serve import conversations

    mem.MEMORY_DIR = tmp_path

    class _User:
        id = "user-a"

    saved = _persist_turn(_User(), "sess-persist-1", "hello there", "reply")
    assert saved["user_message_id"]
    found = conversations.find_message("sess-persist-1", saved["user_message_id"])
    assert found["content"] == "hello there"
    monkeypatch.setattr(conversations, "find_message", lambda *_args, **_kwargs: None)
    assert _persist_turn(_User(), "sess-persist-2", "second", "reply") is None


def test_edit_replay_is_reconciled_for_the_same_idempotency_key(tmp_path, monkeypatch):
    import orca.brain.memory as mem
    from orca.serve import message_versions

    mem.MEMORY_DIR = tmp_path
    monkeypatch.setattr("orca.brain.memory.MEMORY_DIR", tmp_path)
    message_versions.seed("sess-edit-1", "user-a", "msg-11111111", "user", "hello")
    first = message_versions.edit("sess-edit-1", "user-a", "msg-11111111", "hello there", idempotency_key="idem-key-edit-1111")
    second = message_versions.edit("sess-edit-1", "user-a", "msg-11111111", "hello there", idempotency_key="idem-key-edit-1111")
    assert first["created"] is True
    assert second["created"] is False
    assert second["reconciled"] is True
    assert second["version_id"] == first["version_id"]
    assert second["version_count"] == first["version_count"]


def test_failed_closure_without_an_intended_state_is_not_reopened(tmp_path, monkeypatch):
    import orca.brain.memory as mem
    from orca.serve import temporary_chat

    mem.MEMORY_DIR = tmp_path
    session_id = "temp-unknown-1"
    path = tmp_path / "temporary_chats" / f"{session_id}.json"
    path.parent.mkdir()
    path.write_text('{"user_id":"owner-a","state":"failed","transitions":[]}\n')
    recovered = temporary_chat.retry_failed_closure(session_id, "owner-a")
    assert recovered["retried"] is False
    assert recovered["state"] == "failed"
    assert recovered["deleted"] is False
    try:
        temporary_chat.retry_failed_closure(session_id, "other-user")
    except temporary_chat.TemporaryChatDenied as exc:
        assert exc.code == "temporary_not_found"
    else:
        raise AssertionError("a different owner was able to retry the closure")
