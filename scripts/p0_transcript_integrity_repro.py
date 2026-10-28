#!/usr/bin/env python3
"""Reproduce Antigravity P0-3 transcript integrity failures / verify closure.

Demonstrates (against the broken #127 protocol at 2222508):
  1. Stale worker can still commit after lease takeover (revision claim vs later write).
  2. JSONL written inside an uncommitted SQLite transaction survives a crash/rollback.
  3. Uncommitted / phantom JSONL enters subsequent LLM prompt context.

Exit 0 when all three defects are observed (failing-before), exit 1 when any is fixed.
Use --expect-fixed to invert (passing-after: zero defects).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
import uuid


def _setup_home():
    tmp = tempfile.mkdtemp(prefix="p0_transcript_repro_")
    os.environ["ORCA_HOME"] = tmp
    os.environ.pop("ORCA_DATABASE_URL", None)
    os.environ.pop("ORNEUR_DATABASE_URL", None)
    return tmp


def repro_jsonl_inside_txn_phantom(tmp: str) -> dict:
    """Simulate crash after JSONL write but before SQLite COMMIT."""
    from orca.serve import conversations, inference

    sid = "phantom-" + uuid.uuid4().hex[:8]
    conn = conversations._turns_conn()
    turn_id = "t-phantom"
    revision = 1
    user_content, assistant_content = "PHANTOM_USER", "PHANTOM_ASSISTANT"
    ts = time.time()
    payload = (
        json.dumps({"role": "user", "content": user_content, "ts": ts, "meta": {"turn_id": turn_id, "revision": revision}})
        + "\n"
        + json.dumps({"role": "assistant", "content": assistant_content, "ts": ts, "meta": {"turn_id": turn_id, "revision": revision}})
        + "\n"
    ).encode()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO conversation_turns "
            "(turn_id, session_id, user_id, revision, user_content, assistant_content, meta_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (turn_id, sid, "u", revision, user_content, assistant_content, "{}", ts),
        )
        p = conversations._path(sid)
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        conn.execute("ROLLBACK")
    finally:
        conn.close()

    os.environ.pop("ORNEUR_REDIS_URL", None)
    os.environ.pop("ORCA_REDIS_URL", None)
    import orca.serve.session_store as store

    store.REDIS_URL = None
    store._redis_client = None

    body = conversations.transcript(sid, source="auto")
    committed = conversations.transcript(sid, source="committed")
    sqlite_turns = conversations.turns_for_session(sid)
    prompt_msgs = inference._session_messages(sid)
    # Defect: JSONL/prompt sees content that SQLite rolled back.
    poisoned_prompt = any(
        c in ("PHANTOM_USER", "PHANTOM_ASSISTANT") for c in [m["content"] for m in prompt_msgs]
    )
    return {
        "name": "jsonl_phantom_after_sqlite_rollback",
        "jsonl_or_auto_total": body["total"],
        "committed_total": committed["total"],
        "sqlite_turns": len(sqlite_turns),
        "prompt_contents": [m["content"] for m in prompt_msgs],
        "defect_observed": len(sqlite_turns) == 0 and poisoned_prompt,
    }


def repro_stale_worker_after_lease_takeover(tmp: str, redis_url: str) -> dict:
    """Worker A still writes after Worker B takes the lease."""
    import redis as redis_lib

    from orca.serve import conversations
    from orca.serve import session_store
    from orca.serve.inference import InferenceError, _persist

    redis_lib.from_url(redis_url).flushdb()
    os.environ["ORNEUR_REDIS_URL"] = redis_url
    session_store.REDIS_URL = redis_url
    session_store._redis_client = None

    sid = "lease-" + uuid.uuid4().hex[:8]
    assert session_store.acquire_session_lease(sid, "fence-a", ttl_ms=40)

    # Soft preflight claim (broken protocol treated this as a write ticket).
    _state, rev = session_store.load_session_state_with_revision(sid)
    claimed_a = session_store.claim_turn_commit(sid, "fence-a", rev)

    time.sleep(0.06)
    assert session_store.acquire_session_lease(sid, "fence-b", ttl_ms=5_000)
    safe_b = _persist(
        user_id="u-b",
        session_id=sid,
        message="from-B",
        text="reply-B",
        identity={"served_model": "fixture"},
        model="fixture",
        fence_token="fence-b",
    )
    assert safe_b == "reply-B"

    stale_ok = False
    stale_reason = ""
    try:
        _persist(
            user_id="u-a",
            session_id=sid,
            message="from-A-STALE",
            text="reply-A-STALE",
            identity={"served_model": "fixture"},
            model="fixture",
            fence_token="fence-a",
        )
        stale_ok = True
    except InferenceError as exc:
        stale_reason = exc.code

    # Also attempt a direct commit using the pre-claimed Redis ticket / next rev.
    late = conversations.commit_turn(
        sid,
        "from-A-DIRECT",
        "reply-A-DIRECT",
        user_id="u-a",
        turn_id="stale-" + uuid.uuid4().hex[:8],
        revision=None,
        meta={},
        authority_check=lambda: session_store.lease_held(sid, "fence-a"),
    )

    turns = conversations.turns_for_session(sid)
    users = [t["user_content"] for t in turns]
    stale_landed = any(u in ("from-A-STALE", "from-A-DIRECT") for u in users)
    return {
        "name": "stale_worker_commit_after_lease_takeover",
        "worker_a_claim": claimed_a,
        "worker_a_persist_ok": stale_ok,
        "worker_a_persist_reason": stale_reason,
        "worker_a_direct_ok": late.ok,
        "worker_a_direct_reason": late.reason,
        "sqlite_turn_users": users,
        "defect_observed": stale_ok or late.ok or stale_landed,
    }


def repro_prompt_contamination_from_untrusted_jsonl(tmp: str) -> dict:
    """Plant uncommitted JSONL; confirm whether it enters the inference prompt builder."""
    from orca.serve import conversations, inference

    sid = "contam-" + uuid.uuid4().hex[:8]
    conversations.append(sid, "user", "UNCOMMITTED_SECRET_PROMPT_POISON")
    conversations.append(sid, "assistant", "should-not-be-in-context")
    assert conversations.turns_for_session(sid) == []
    msgs = inference._session_messages(sid)
    poisoned = any(m["content"] == "UNCOMMITTED_SECRET_PROMPT_POISON" for m in msgs)
    return {
        "name": "prompt_contamination_from_jsonl",
        "sqlite_turns": 0,
        "prompt_contents": [m["content"] for m in msgs],
        "defect_observed": poisoned,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis-url", default="redis://localhost:6379/14")
    ap.add_argument("--expect-fixed", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    tmp = _setup_home()
    results = []
    try:
        results.append(repro_jsonl_inside_txn_phantom(tmp))
        results.append(repro_prompt_contamination_from_untrusted_jsonl(tmp))
        results.append(repro_stale_worker_after_lease_takeover(tmp, args.redis_url))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    observed = [r for r in results if r.get("defect_observed")]
    report = {
        "expect_fixed": args.expect_fixed,
        "defects_observed": len(observed),
        "results": results,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if args.expect_fixed:
        return 0 if len(observed) == 0 else 1
    return 0 if len(observed) == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
