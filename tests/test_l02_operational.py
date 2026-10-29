"""L02-06 -- readiness, drain, storage headroom, deadlines and backup/restore (real app / real databases, fixture provider)."""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from collections import namedtuple

import pytest
from fastapi.testclient import TestClient

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_product_flows_fake_ollama import _events, fake  # noqa: F401

_Usage = namedtuple("usage", "total used free")


@pytest.fixture(autouse=True)
def _ops_reset():
    from orca.serve import ops

    ops.reset_for_tests()
    yield
    ops.reset_for_tests()


@pytest.fixture
def ready_app(client, monkeypatch):
    import orca.serve.api as api

    monkeypatch.setattr(api, "resolve_tier_model", lambda *a, **k: "stub-model")        # the model runtime itself is covered by the live tests
    return client


def _ready(client):
    r = client.get("/readyz")
    return r.status_code, r.json()


# ── readiness ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_readyz_reports_each_dependency_separately_and_is_ready_when_healthy(ready_app):
    code, body = _ready(ready_app)
    deps = body["dependencies"]
    assert code == 200 and body["status"] == "ready"
    assert deps["transcript_store"]["status"] == "ok" and deps["disk"]["state"] in ("ok", "low")
    assert set(deps["maintenance_backlog"]) == {"conversation_deletions_incomplete", "document_deletions_pending", "reconciler_blocked"}
    assert deps["streams"]["capacity"] >= 1 and deps["redis"]["status"] in ("ok", "not_configured", "unavailable")
    assert "password" not in json.dumps(body).lower() and "secret" not in json.dumps(body).lower()


def test_an_unreadable_transcript_store_makes_the_server_not_ready(ready_app, monkeypatch):
    from orca.serve import ops

    monkeypatch.setattr(ops, "transcript_store_report", lambda: {"status": "unavailable", "reason": "OperationalError"})
    code, body = _ready(ready_app)
    assert code == 503 and body["status"] == "not_ready" and body["dependencies"]["transcript_store"]["status"] == "unavailable"


def test_critical_disk_makes_the_server_not_ready_and_low_disk_only_warns(ready_app, monkeypatch):
    for free_mb, expect_ready, state in ((50, False, "critical"), (500, True, "low"), (5000, True, "ok")):
        monkeypatch.setattr(shutil, "disk_usage", lambda p, f=free_mb: _Usage(100 * 1024**3, 100 * 1024**3 - f * 1024**2, f * 1024**2))
        from orca.serve import ops

        ops.reset_for_tests()
        code, body = _ready(ready_app)
        assert (code == 200) is expect_ready and body["dependencies"]["disk"]["state"] == state, (free_mb, body["dependencies"]["disk"])


def test_redis_down_is_reported_but_does_not_make_the_server_not_ready(ready_app, monkeypatch):
    from orca.serve import ops

    monkeypatch.setattr(ops, "redis_report", lambda: {"status": "unavailable", "role": "advisory"})
    code, body = _ready(ready_app)
    assert code == 200 and body["dependencies"]["redis"] == {"status": "unavailable", "role": "advisory"}


# ── storage exhaustion: refuse BEFORE spending anything ───────────────────────────────────────────────────────────────────────

def test_a_full_disk_refuses_new_turns_before_any_model_call_or_charge_and_recovers(client, fake, monkeypatch):
    from orca.auth.store import get_usage_today
    from orca.serve import ops

    t, uid = _signup(client)
    h = _hdr(t)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: _Usage(100 * 1024**3, 100 * 1024**3 - 10 * 1024**2, 10 * 1024**2))      # 10 MB free: critical
    ops.reset_for_tests()
    n0 = len(fake.requests)
    evs = _events(client, h, {"message": "will not be started"})
    assert evs[-1]["type"] == "error" and evs[-1]["code"] == "history_unavailable"
    r = client.post("/api/chat", json={"message": "nor this"}, headers=h)
    assert r.status_code == 503 and r.json()["code"] == "history_unavailable"
    assert len(fake.requests) == n0 and get_usage_today(uid)["messages"] == 0
    monkeypatch.setattr(shutil, "disk_usage", lambda p: _Usage(100 * 1024**3, 0, 50 * 1024**3))
    ops.reset_for_tests()
    ok = _events(client, h, {"message": "now it can"})
    assert ok[-1]["type"] == "done" and ok[-1]["persisted"] == "saved"


# ── graceful drain ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_draining_refuses_new_work_with_a_retryable_503_and_keeps_health_endpoints_answering(ready_app, fake):
    from orca.serve import ops

    t, uid = _signup(ready_app)
    h = _hdr(t)
    ops.begin_drain()
    n0 = len(fake.requests)
    for path, body in (("/api/stream", {"message": "x"}), ("/api/chat", {"message": "x"})):
        r = ready_app.post(path, json=body, headers=h)
        assert r.status_code == 503 and r.json()["code"] == "server_draining" and r.headers.get("retry-after")
    assert len(fake.requests) == n0
    assert ready_app.get("/livez").status_code == 200
    code, body = _ready(ready_app)
    assert code == 503 and body["dependencies"]["lifecycle"]["status"] == "draining"
    assert ready_app.get("/api/auth/me", headers=h).status_code == 200, "reads and in-flight sessions are not broken by a drain"


# ── total request deadline ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_stream_that_exceeds_the_total_deadline_is_stopped_told_and_not_committed(client, monkeypatch):
    import orca.serve.api as api

    monkeypatch.setattr(api, "_STREAM_MAX_S", 0.6)
    with FakeOllama(chunks=tuple(f"w{i} " for i in range(60)), chunk_delay=0.1) as f:
        point_orneur_at(f, monkeypatch)
        t, uid = _signup(client)
        h = {**_hdr(t), "Idempotency-Key": "k-" + uuid.uuid4().hex}
        sid = str(uuid.uuid4())
        t0 = time.monotonic()
        with client.stream("POST", "/api/stream", json={"message": "a very long answer", "session_id": sid, "model_variant": "core"}, headers=h) as s:
            text = "".join(s.iter_text())
        took = time.monotonic() - t0
        evs = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
        assert evs[-1]["type"] == "error" and evs[-1]["code"] == "request_timeout" and took < 5
        assert f.stream_aborted.wait(3), "the provider was not hung up on at the deadline"
        from orca.serve import conversations

        assert conversations.turns_for_session(sid) == []
        st = client.get(f"/api/turns/{h['Idempotency-Key']}", headers=_hdr(t)).json()
        assert st["state"] == "not_committed" and st["reason"] == "request_timeout"


# ── backup and restore ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _assemble_home(tmp_path):
    """A data directory laid out exactly like a deployment's ORNEUR_HOME, populated from the live test databases (the test suite splits these across temp roots)."""
    from orca.auth import db as authdb
    from orca.docs import store as docs_store
    from orca.serve import conversations

    home = tmp_path / "home"
    (home / "memory" / "conversations").mkdir(parents=True)
    (home / "docs").mkdir()
    for src, rel in ((conversations._turns_db(), "memory/conversations/turns.db"), (authdb.AUTH_DB, "auth.db")):
        s_, d_ = sqlite3.connect(str(src)), sqlite3.connect(str(home / rel))
        s_.backup(d_)
        s_.close()
        d_.close()
    if docs_store._REGISTRY_FILE.exists():
        shutil.copy2(docs_store._REGISTRY_FILE, home / "docs" / "registry.json")
    (home / "docs" / "kw_abc.jsonl").write_text(json.dumps({"doc_id": "d", "text": "keyword text"}) + "\n")
    return home


def test_backup_is_consistent_verifiable_and_restores_into_a_fresh_directory(client, fake, tmp_path):
    from orca.serve import backup

    t, uid = _signup(client)
    h = _hdr(t)
    sid = _events(client, h, {"message": "remember this exact sentence"})[0]["session_id"]
    client.post("/api/docs/upload", files={"file": ("n.txt", b"the stored document text", "text/plain")}, headers=h, params={"session_id": sid})
    home = _assemble_home(tmp_path)
    dest = tmp_path / "bk"
    made = backup.create(home, dest)
    assert made["files"] >= 4 and backup.verify(dest)["ok"] is True
    fresh = tmp_path / "restored-home"
    r = backup.restore(dest, fresh)
    assert r["verified"] and r["restored_files"] == made["files"]
    conn = sqlite3.connect(str(fresh / "memory/conversations/turns.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", (sid,)).fetchone()[0] == 1
        assert "remember this exact sentence" in conn.execute("SELECT user_content FROM conversation_turns WHERE session_id=?", (sid,)).fetchone()[0]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert (fresh / "docs" / "kw_abc.jsonl").read_text().strip().endswith('"keyword text"}')
    with pytest.raises(FileExistsError):
        backup.restore(dest, fresh)                                 # never overwrites a populated directory by accident
    with pytest.raises(FileExistsError):
        backup.create(home, dest)                                   # nor an existing backup


def test_backup_taken_while_the_database_is_being_written_is_still_consistent(client, fake, tmp_path):
    """The online-backup API gives a transactionally consistent snapshot even with a writer active."""
    from orca.serve import backup, conversations

    t, uid = _signup(client)
    h = _hdr(t)
    _events(client, h, {"message": "seed"})
    home = _assemble_home(tmp_path)
    stop = threading.Event()
    def writer():
        while not stop.is_set():
            conn = sqlite3.connect(str(home / "memory/conversations/turns.db"), timeout=10)
            try:
                with conn:
                    conn.execute("INSERT INTO session_export_state (session_id, updated_at) VALUES (?, ?) ON CONFLICT DO NOTHING", (uuid.uuid4().hex, time.time()))
            finally:
                conn.close()
    th = threading.Thread(target=writer)
    th.start()
    try:
        dest = tmp_path / "bk"
        backup.create(home, dest)
    finally:
        stop.set()
        th.join()
    assert backup.verify(dest)["ok"] is True


def test_a_corrupted_backup_is_detected_and_nothing_is_restored(client, fake, tmp_path):
    from orca.serve import backup

    t, uid = _signup(client)
    _events(client, _hdr(t), {"message": "x"})
    home = _assemble_home(tmp_path)
    dest = tmp_path / "bk"
    backup.create(home, dest)
    victim = next(dest.rglob("turns.db"))
    with open(victim, "r+b") as f:
        f.seek(100)
        f.write(b"\x00corrupted\x00")
    v = backup.verify(dest)
    assert v["ok"] is False and any("turns.db" in p for p in v["problems"])
    target = tmp_path / "never-written"
    with pytest.raises(ValueError):
        backup.restore(dest, target)
    assert not target.exists() or not any(target.iterdir())


# ── truthful capacity errors ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_model_gateway_capacity_refusals_are_reported_as_server_busy_not_as_a_model_failure():
    """Found by the live 24-stream test: the gateway's queue-full refusal (4 running + 16 queued per deployment) reached users as 'The model backend could not complete this
    request' (backend_error). It is a capacity condition and must say so."""
    from orca.cognitive.errors import CognitiveExecutionFailedError
    from orca.gateway.errors import CircuitOpenError, GenerationTimeoutError, QueueFullError, QueueTimeoutError
    from orca.serve.errors import public_error

    for exc, code in ((QueueFullError("d"), "server_busy"), (QueueTimeoutError("d"), "server_busy"), (CircuitOpenError("d"), "model_unavailable"),
                      (GenerationTimeoutError("d"), "upstream_timeout")):
        try:
            try:
                raise exc
            except Exception as inner:
                raise CognitiveExecutionFailedError(internal_detail=str(inner)) from inner     # exactly how the Kernel wraps a gateway failure
        except Exception as wrapped:
            pe = public_error(wrapped, route="/api/stream")
            assert pe.code == code and pe.status in (503, 504), (type(exc).__name__, pe.code)
            assert "d" not in pe.message.split() and "traceback" not in pe.message.lower()


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_turn_outcomes_cancellations_deletions_and_refusals_are_counted_with_bounded_labels(client, fake):
    import uuid

    from orca.serve import metrics, ops

    metrics.reset()
    t, uid = _signup(client)
    h = _hdr(t)
    k1, k2 = "k-" + uuid.uuid4().hex, "k-" + uuid.uuid4().hex
    with client.stream("POST", "/api/stream", json={"message": "metrics one", "model_variant": "core"}, headers={**h, "Idempotency-Key": k1}) as s:
        "".join(s.iter_text())
    client.post(f"/api/turns/{k2}/cancel", headers=h)
    chat = client.post("/api/chat", json={"message": "hello there friend"}, headers=h)
    assert chat.status_code == 200, chat.text
    sid = chat.json()["session_id"]
    client.delete(f"/api/session/{sid}", headers=h)
    ops.begin_drain()
    client.post("/api/stream", json={"message": "x"}, headers=h)
    text = client.get("/metrics").text
    for needle in ('event="turn_outcome",label="committed:none"', 'event="turn_outcome",label="cancelled:cancelled_before_admission"', 'event="turn_cancel_requested"',
                   'event="deletion",label="complete"', 'event="refusal",label="server_draining"'):
        assert needle in text, needle
    assert k1 not in text and uid not in text and sid not in text, "no identifier may appear in a metric"
    for i in range(300):
        metrics.record_event("refusal", f"label-{i}")
    assert text.count("orca_events_total{") < 200 and len([l for l in client.get("/metrics").text.splitlines() if l.startswith("orca_events_total{")]) <= 201
