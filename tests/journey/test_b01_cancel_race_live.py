"""B-01 final integration -- Stop racing the commit (evidence class: LIVE_API + FIXTURE provider).

The user presses Stop at the worst moment: after the last token, while the server is committing the turn. Whatever the interleaving, the outcome must be ONE of
two coherent states, and what happened must be reported rather than assumed:

  (a) the commit won  -> the transcript holds the user message and the COMPLETE redacted answer, once;
  (b) the cancel won  -> the transcript holds nothing for that turn.

Never a partial answer, never a half turn, never a duplicate; the conversation is never left busy; the unit of quota is spent exactly once (output had arrived).
The test runs the race many times with different delays and records how often each outcome occurred.
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from pathlib import Path

import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, LiveServer, User

EVIDENCE = Path(os.environ.get("ORNEUR_B01_EVIDENCE_DIR", "/tmp/orneur-b01-evidence"))
PIECES = ["alpha ", "beta ", "gamma ", "delta"]
FULL = "".join(PIECES)
ROUNDS = 36


ASYNCIO_HYGIENE = ("Task exception was never retrieved", "Task was destroyed but it is pending", "was never awaited", "async generator ignored GeneratorExit",
                   "Exception ignored in", "coroutine ignored GeneratorExit")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    fake = FakeOllama(models=(JOURNEY_MODEL,), chunks=PIECES, chunk_delay=0.02)
    fake.__enter__()
    home = tmp_path_factory.mktemp("b01-race-home")
    srv = LiveServer(home, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        yield {"srv": srv, "fake": fake, "user": User(srv.base, "b01race")}
    finally:
        srv.stop()
        fake.__exit__(None, None, None)
        # The server's own log must carry no asyncio hygiene warning from the abandoned/cancelled streams this module created.
        log = srv.log_path.read_text(errors="replace")
        bad = [m for m in ASYNCIO_HYGIENE if m in log]
        assert not bad, f"server log contains asyncio hygiene warnings: {bad}"


def _usage(user):
    return user.get("/api/usage").json()["today"]["messages"]


def _hang_up_after_last_chunk(user, sid, message, delay_s):
    headers = {"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}
    n = 0
    with user.http.stream("POST", "/api/stream", json={"message": message, "session_id": sid, "model_variant": "core"}, headers=headers) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if ev["type"] == "done":
                return "done"
            if ev["type"] == "chunk":
                n += len(ev["text"])
                if n >= len(FULL):
                    time.sleep(delay_s)
                    return "hung_up"
    return "eof"


def test_stop_racing_the_commit_leaves_only_coherent_states(stack):
    user = stack["user"]
    rnd = random.Random(20261029)
    committed, cancelled, completed_before_hangup = 0, 0, 0
    for i in range(ROUNDS):
        sid, msg = str(uuid.uuid4()), f"race question {i}"
        used = _usage(user)
        outcome = _hang_up_after_last_chunk(user, sid, msg, rnd.choice([0.0, 0.0, 0.002, 0.005, 0.01, 0.02, 0.05]))
        time.sleep(0.4)                                            # let the server finish whatever it was doing
        rows = [(m["role"], m["content"]) for m in user.get(f"/api/session/{sid}/messages").json()["messages"]]
        if outcome == "done":
            completed_before_hangup += 1
            assert rows == [("user", msg), ("assistant", FULL)]
        elif rows == []:
            cancelled += 1
        else:
            assert rows == [("user", msg), ("assistant", FULL)], f"round {i}: a partial or malformed turn was committed: {rows}"
            committed += 1
        assert _usage(user) - used == 1, f"round {i}: quota must be spent exactly once (output had arrived), delta={_usage(user) - used}"
        if i % 9 == 0:                                             # and the conversation is never left busy by the race
            headers = {"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}
            with user.http.stream("POST", "/api/stream", json={"message": "still usable?", "session_id": sid, "model_variant": "core"}, headers=headers) as r:
                evs = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
            assert evs[-1]["type"] == "done" and evs[-1]["persisted"] == "saved", f"round {i}: the conversation was left busy: {evs[-2:]}"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "cancel_race.json").write_text(json.dumps({
        "rounds": ROUNDS, "commit_won": committed, "cancel_won": cancelled, "done_delivered_before_hangup": completed_before_hangup,
        "invariants": ["transcript is [] or exactly user+complete answer", "quota delta == 1 per round", "conversation never left busy"],
    }, indent=2))
    assert committed + cancelled + completed_before_hangup == ROUNDS
