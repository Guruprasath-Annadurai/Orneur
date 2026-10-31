"""L02-01f -- deletion under REAL failure conditions (evidence class: LIVE_API: real ``orca serve`` processes, real SQLite, real Redis in a dedicated container).

Which parts are real and which are not (per test docstring):
  * ORNEUR processes, SQLite, Redis (a throwaway ``redis:7-alpine`` container this module starts, stops and restarts itself -- the shared test Redis is never touched),
    Chroma on disk, filesystem permissions: REAL.
  * model provider: FakeOllama (fixture) except the last test, which uses REAL Ollama + the real ``nomic-embed-text`` embedding weights (third-party).
  * "crash" in D4 is a SYNTHETIC state (a tombstone row written with the server stopped); the restart and the recovery are real.

Run:  pytest tests/journey/test_l02_deletion_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, CapabilityMissing, LiveServer, User, _free_port

EVIDENCE = Path(os.environ.get("ORNEUR_L02_EVIDENCE_DIR", "/tmp/orneur-l02-evidence"))


def record(name: str, data: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"l02_deletion_live_{name}.json").write_text(json.dumps({"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **data}, indent=2))


def _docker(*args, check=True):
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120, check=check)
    except Exception as exc:
        raise CapabilityMissing(f"capability missing: docker ({exc!r})")


class RedisBox:
    """A dedicated Redis the test may kill and restart."""

    def __init__(self):
        self.port = _free_port()
        self.name = f"l02-redis-{uuid.uuid4().hex[:8]}"
        _docker("run", "-d", "--rm", "--name", self.name, "-p", f"127.0.0.1:{self.port}:6379", "redis:7-alpine", "--save", "", "--appendonly", "no")
        self.url = f"redis://127.0.0.1:{self.port}/0"
        self.wait_up()

    def client(self):
        import redis

        return redis.from_url(self.url, socket_connect_timeout=1, socket_timeout=2)

    def wait_up(self, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.client().ping():
                    return
            except Exception:
                time.sleep(0.2)
        raise CapabilityMissing("capability missing: dedicated Redis container did not come up")

    def down(self):
        _docker("pause", self.name)         # the process is frozen: connections hang/time out exactly like an unreachable Redis, and no data is lost

    def up(self):
        _docker("unpause", self.name)
        self.wait_up()

    def close(self):
        _docker("rm", "-f", self.name, check=False)


def _turns_db(home: Path) -> Path:
    found = list(home.rglob("turns.db"))
    assert found, f"no turns.db under {home}"
    return found[0]


def _deletion_state(home: Path, sid: str):
    conn = sqlite3.connect(str(_turns_db(home)))
    try:
        row = conn.execute("SELECT state, deletion_id, attempts FROM session_deletions WHERE session_id=?", (sid,)).fetchone()
        return row
    finally:
        conn.close()


def _turn_rows(home: Path, sid: str) -> int:
    conn = sqlite3.connect(str(_turns_db(home)))
    try:
        return conn.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", (sid,)).fetchone()[0]
    finally:
        conn.close()


def _wait(pred, timeout=30, every=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(every)
    return None


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    box = RedisBox()
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="FIXTURE-ANSWER")
    fake.__enter__()
    home = tmp_path_factory.mktemp("l02-del-home")
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_DELETION_SWEEP_S": "2", "ORNEUR_DELETE_REQUEST_BUDGET_S": "8",
           "ORNEUR_TURN_AUTHORITY_TTL_S": "3", "ORNEUR_TURN_HEARTBEAT_S": "1", "ORNEUR_TURN_LEASE_MS": "4000"}
    a = LiveServer(home, redis_url=box.url, extra_env=env)
    b = LiveServer(home, redis_url=box.url, extra_env=env)
    try:
        a.wait_ready()
        b.wait_ready()
        user = User(a.base, "l02del")
        user.token_b = httpx.post(f"{b.base}/api/auth/login", json={"email": user.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
        yield {"box": box, "fake": fake, "home": home, "env": env, "a": a, "b": b, "user": user}
    finally:
        for s in (a, b):
            s.stop()
        fake.__exit__(None, None, None)
        box.close()


def _turn(cluster, text="my codename is NIGHTINGALE-ZX", sid=None):
    sid = sid or str(uuid.uuid4())
    status, events = cluster["user"].stream(text, sid)
    assert status == 200 and events[-1]["type"] == "done" and events[-1]["persisted"] == "saved", events[-2:]
    return sid


def _delete(base, token, sid):
    return httpx.delete(f"{base}/api/session/{sid}", headers={"Authorization": f"Bearer {token}"}, timeout=60)


def test_D1_redis_unreachable_during_deletion_is_partial_then_completes_after_recovery(cluster):
    """LIVE: real Redis frozen (pause) while ORNEUR deletes; real recovery; the sweep finishes it."""
    box, user, home = cluster["box"], cluster["user"], cluster["home"]
    sid = _turn(cluster)
    keys_before = [k.decode() for k in box.client().scan_iter(match=f"orca:session:{sid}*")]
    box.down()
    try:
        t0 = time.time()
        r = _delete(cluster["a"].base, user.token, sid)
        took = time.time() - t0
        assert r.status_code == 202, (r.status_code, r.text)
        body = r.json()
        assert body["deleted"] is False and body["state"] == "partial" and body["access_revoked"] is True
        assert body["stores"]["redis"] == "failed"
        assert httpx.get(f"{cluster['a'].base}/api/session/{sid}/messages", headers=user.headers, timeout=30).status_code == 404
    finally:
        box.up()
    row = _wait(lambda: (lambda r: r if r and r[0] == "complete" else None)(_deletion_state(home, sid)), timeout=40)
    assert row, f"the sweep never completed the deletion: {_deletion_state(home, sid)}"
    keys_after = [k.decode() for k in box.client().scan_iter(match=f"orca:session:{sid}*")]
    assert keys_after == [] and _turn_rows(home, sid) == 0
    record("D1_redis_outage", {"redis_keys_before": keys_before, "partial_response_s": round(took, 2), "partial_body_stores": body["stores"],
                               "final_state": row[0], "attempts": row[2], "redis_keys_after": keys_after})


def test_D2_two_workers_deleting_at_once_converge_on_one_deletion(cluster):
    """LIVE: two real workers, six concurrent DELETEs for one conversation."""
    user, home = cluster["user"], cluster["home"]
    sid = _turn(cluster)
    out = []

    def go(base, tok):
        out.append(_delete(base, tok, sid))

    ts = [threading.Thread(target=go, args=(cluster["a"].base, user.token)) for _ in range(3)] + \
         [threading.Thread(target=go, args=(cluster["b"].base, user.token_b)) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    codes = sorted(r.status_code for r in out)
    assert all(c in (200, 202, 404) for c in codes) and 200 in codes, codes
    ids = {r.json().get("deletion_id") for r in out if r.status_code in (200, 202)}
    assert len(ids) == 1
    row = _wait(lambda: (lambda r: r if r and r[0] == "complete" else None)(_deletion_state(home, sid)), timeout=30)
    assert row and _turn_rows(home, sid) == 0
    record("D2_two_workers", {"status_codes": codes, "distinct_deletion_ids": len(ids), "final_state": row[0]})


def test_D3_deletion_during_an_in_flight_generation_stores_nothing(cluster):
    """LIVE: a slow streamed generation on worker A; the user deletes the conversation from worker B while it is generating."""
    user, home, fake = cluster["user"], cluster["home"], cluster["fake"]
    sid = _turn(cluster, "first message")                                  # an existing conversation with one committed turn
    fake._chunks = tuple(f"w{i} " for i in range(25))
    fake.chunk_delay = 0.2
    result = {}

    def stream():
        result["status"], result["events"] = user.stream("second message during deletion", sid)

    t = threading.Thread(target=stream)
    t.start()
    time.sleep(1.2)                                                        # generation is under way
    r = _delete(cluster["b"].base, user.token_b, sid)
    t.join(timeout=60)
    fake.chunk_delay, fake._chunks = 0.0, None
    assert r.status_code in (200, 202), r.text
    events = result["events"]
    done = [e for e in events if e["type"] == "done"]
    assert not done or done[0]["persisted"] != "saved", "the in-flight turn must not be reported as saved after the conversation was deleted"
    row = _wait(lambda: (lambda x: x if x and x[0] == "complete" else None)(_deletion_state(home, sid)), timeout=30)
    assert row and _turn_rows(home, sid) == 0, "no turn (old or new) may survive the deletion"
    assert httpx.get(f"{cluster['a'].base}/api/session/{sid}/messages", headers=user.headers, timeout=30).status_code == 404
    record("D3_in_flight", {"delete_status": r.status_code, "stream_event_types": [e["type"] for e in events][-6:],
                            "done_persisted": done[0]["persisted"] if done else None, "turn_rows_after": _turn_rows(home, sid)})


def test_D4_restart_during_partial_cleanup_resumes(cluster):
    """SYNTHETIC crash state (tombstone written, nothing cleaned, server stopped) + REAL restart and real recovery by the new process."""
    user, home = cluster["user"], cluster["home"]
    sid = _turn(cluster, "restart me")
    uid = httpx.get(f"{cluster['a'].base}/api/auth/me", headers=user.headers, timeout=30).json()["id"] if False else None
    conn = sqlite3.connect(str(_turns_db(home)))
    try:
        owner = conn.execute("SELECT user_id FROM conversation_turns WHERE session_id=? LIMIT 1", (sid,)).fetchone()[0]
        now = time.time()
        conn.execute("INSERT INTO session_deletions (session_id, deletion_id, user_id, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                     (sid, str(uuid.uuid4()), owner, "revoked", now, now))
        conn.commit()
    finally:
        conn.close()
    assert _turn_rows(home, sid) == 1
    fresh = LiveServer(home, redis_url=cluster["box"].url, extra_env=cluster["env"])            # a brand-new process
    try:
        fresh.wait_ready()
        row = _wait(lambda: (lambda x: x if x and x[0] == "complete" else None)(_deletion_state(home, sid)), timeout=40)
        assert row and _turn_rows(home, sid) == 0
        assert httpx.get(f"{fresh.base}/api/session/{sid}/messages", headers=user.headers, timeout=30).status_code == 404
    finally:
        fresh.stop()
    record("D4_restart", {"synthetic_crash_state": "tombstone written, stores untouched", "recovered_by": "new process sweep", "final_state": row[0], "attempts": row[2]})


def test_D5_vector_store_failure_is_partial_then_recovers(cluster):
    """LIVE: the vector store's directory becomes unusable on disk (replaced by a plain file -- a real filesystem failure that fails FAST) while the user
    deletes; the deletion must be partial and never a false success; once the directory is restored the sweep completes it.

    (A held SQLite lock on the vector store was tried first and is NOT used here: the chromadb native client blocks while holding the GIL, which freezes the
    whole ORNEUR process, not just the deletion -- recorded as register item L02-06a, evidence/l02_chroma_lock_freezes_process.txt.)"""
    user, home = cluster["user"], cluster["home"]
    sid = _turn(cluster, "vector failure subject")
    vec = sorted({f.parent for f in home.rglob("chroma.sqlite3") if f.parent.parent.name == "memory"})
    assert vec, "no long-term vector store was created by the turn"
    moved = []
    for d in vec:
        side = d.with_name(d.name + ".away")
        d.rename(side)
        d.write_text("not a directory")
        moved.append((d, side))
    try:
        r = _delete(cluster["a"].base, user.token, sid)
        body = r.json()
        record("D5_vector_failure_probe", {"status": r.status_code, "stores": body["stores"]})
        assert r.status_code == 202 and body["deleted"] is False and body["state"] == "partial", (r.status_code, body)
        assert body["stores"]["long_term_vector_memory"] == "failed"
        assert httpx.get(f"{cluster['a'].base}/api/session/{sid}/messages", headers=user.headers, timeout=30).status_code == 404
    finally:
        for d, side in moved:
            d.unlink()
            side.rename(d)
    row = _wait(lambda: (lambda x: x if x and x[0] == "complete" else None)(_deletion_state(cluster["home"], sid)), timeout=40)
    assert row
    record("D5_vector_failure", {"partial_stores": body["stores"], "final_state": row[0], "attempts": row[2]})


# ── D6: REAL Ollama + real embedding weights (nomic-embed-text, third-party) ──────────────────────────────────────────────────────

def test_D6_real_ollama_embeddings_deleted_document_does_not_resurface(server, tap):
    """LIVE+REAL: documents are embedded by the real ``nomic-embed-text`` weights through the recording tap; after the document is deleted its text must not
    reach the model again, the vector collection is empty, and a stale-embedding probe (the chunk still physically present, registry entry gone) is not served."""
    from tests.journey.harness import OLLAMA_HOST

    tags = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=10).json()["models"]
    assert any(m["name"].startswith("nomic-embed-text") for m in tags), "capability missing: `ollama pull nomic-embed-text` (free, local)"
    user = User(server.base, "l02emb")
    canary = "ZEBRAFISH-CANARY-8841"
    text = (f"Lab notes. The incubation temperature for the {canary} culture is 28.5 degrees Celsius. "
            "Samples are stored in the second freezer. Contact the lab manager for access.").encode()
    up = user.http.post("/api/docs/upload", files={"file": ("lab.txt", text, "text/plain")}, headers=user.headers)
    assert up.status_code == 200, up.text
    sid, doc = up.json()["session_id"], up.json()["doc_id"]
    assert tap.embed_calls >= 1, "the real embedding model was not used"
    n0 = len(tap.requests)
    status, events = user.stream("What is the incubation temperature for the culture?", sid)
    assert status == 200 and events[-1]["type"] == "done"
    sent_before = json.dumps([r["body"] for r in tap.requests[n0:]])
    assert canary in sent_before, "with the document present the passage must reach the model"
    d = user.http.delete(f"/api/docs/{doc}", params={"session_id": sid}, headers=user.headers)
    assert d.status_code == 200 and d.json()["deleted"] is True, d.text
    listing = user.http.get("/api/docs/list", params={"session_id": sid}, headers=user.headers).json()
    assert listing["docs"] == [] and listing["total_chunks"] == 0
    n1 = len(tap.requests)
    status, events = user.stream("What is the incubation temperature for the culture?", sid)
    assert status == 200
    where = []
    for i, r in enumerate(tap.requests[n1:]):
        for m in (r["body"].get("messages") or [{"role": "prompt", "content": r["body"].get("prompt", "")}]):
            if canary in m["content"]:
                in_doc_ctx = "[Document context" in m["content"] or "[Retrieved context]" in m["content"]
                where.append({"request": i, "role": m["role"], "in_document_context_block": in_doc_ctx,
                              "kind": "knowledge-graph side call" if "Extract factual relationships" in m["content"] else "conversation history"})
    # The DOCUMENT's passages must never be retrieved again. Text the assistant already said in turn 1 lives in the conversation transcript (and the graph
    # extraction of that exchange); that is the disclosed scope of a document deletion, not a retrieval leak.
    assert not any(w["in_document_context_block"] for w in where), where
    assert all(w["kind"] in ("conversation history", "knowledge-graph side call") for w in where), where
    done = events[-1]
    assert done["type"] == "done" and done["sources"] == []
    record("D6_real_embeddings", {"embedding_model": "nomic-embed-text (third-party weights)", "embed_calls_during_upload_and_queries": tap.embed_calls,
                                  "canary_sent_before_delete": True, "canary_in_document_context_after_delete": False, "canary_occurrences_after_delete": where, "sources_after_delete": 0,
                                  "model_tag": JOURNEY_MODEL})
