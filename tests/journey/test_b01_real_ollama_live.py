"""B-01 final integration -- REAL Ollama streaming and Stop (evidence class: LIVE_API, real model behind a recording pass-through tap).

No fixture provider here: the model is whatever ``ORNEUR_JOURNEY_MODEL`` names in the workstation's Ollama (``llama3.2:1b`` when run with that literal tag; the
default ``orneur-journey`` is a local alias of the same weights). The tap forwards every byte unchanged and records what ORNEUR sent and when ORNEUR hung up,
so cancellation is MEASURED at the provider boundary rather than inferred. Nothing asserted depends on what the model says, only on timing, counts and stores.

Every test writes its measurements to ``$ORNEUR_B01_EVIDENCE_DIR`` (default /tmp/orneur-b01-evidence) for the evidence manifest.

Run:  pytest tests/journey/test_b01_real_ollama_live.py -p no:cacheprovider -v
      ORNEUR_JOURNEY_MODEL=llama3.2:1b pytest tests/journey/test_b01_real_ollama_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

from tests.journey.harness import JOURNEY_MODEL, OLLAMA_HOST, User

EVIDENCE = Path(os.environ.get("ORNEUR_B01_EVIDENCE_DIR", "/tmp/orneur-b01-evidence"))
LONG_PROMPT = "Write a long, detailed essay of at least 400 words about the history of the lighthouse. Use several paragraphs."


def record(name: str, data: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    data = {"model_tag": JOURNEY_MODEL, "ollama_host": OLLAMA_HOST, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **data}
    (EVIDENCE / f"real_ollama_{JOURNEY_MODEL.replace(':', '_')}_{name}.json").write_text(json.dumps(data, indent=2))


@pytest.fixture(scope="module")
def alice(server):
    return User(server.base, "b01real")


def _stream(user: User, message: str, session_id: str | None, *, stop_after_chunks: int | None = None):
    headers = {"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}
    events, t0, n = [], time.monotonic(), 0
    with user.http.stream("POST", "/api/stream", json={"message": message, "session_id": session_id, "model_variant": "core"}, headers=headers) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                ev["_t"] = round(time.monotonic() - t0, 3)
                events.append(ev)
                n += ev["type"] == "chunk"
                if stop_after_chunks and n >= stop_after_chunks:
                    break
    return events


def _transcript(user: User, sid: str):
    r = user.get(f"/api/session/{sid}/messages")
    assert r.status_code == 200, r.text
    return [(m["role"], m["content"]) for m in r.json()["messages"]]


def test_S10_real_model_tokens_reach_the_client_progressively(server, alice, tap):
    n0 = len(tap.requests)
    sid = str(uuid.uuid4())
    events = _stream(alice, LONG_PROMPT, sid)
    chunks = [e for e in events if e["type"] == "chunk"]
    stream_ev = next(e for e in events if e["type"] == "stream")
    done = events[-1]
    assert stream_ev == {"type": "stream", "delivery": "upstream", "cancellable": True, "_t": stream_ev["_t"]}
    assert done["type"] == "done" and done["delivery"] == "upstream" and done["persisted"] == "saved"
    assert not any(e.get("replayed") for e in events)
    assert len(chunks) >= 20, f"a 400-word essay from a real model must arrive in many pieces, got {len(chunks)}"
    first, last = chunks[0]["_t"], chunks[-1]["_t"]
    assert last - first >= 1.0, "all tokens arrived together: this was buffered, not streamed"
    assert first < done["_t"] - 1.0, "the first token only arrived with the end of generation"
    # Time-separated: at least 10 distinct arrival instants (1 ms resolution) over the generation.
    assert len({c["_t"] for c in chunks}) >= 10
    text = "".join(c["text"] for c in chunks)
    assert _transcript(alice, sid)[-1] == ("assistant", text), "what was streamed is exactly what was saved"
    ident = next(e for e in events if e["type"] == "model")["identity"]
    assert ident == done["model_identity"] and ident["backend"] == "ollama" and ident["data_left_infrastructure"] is False
    answering = [r for r in tap.requests[n0:] if (r["body"].get("messages") or [{}])[-1].get("content") == LONG_PROMPT]
    assert len(answering) == 1 and answering[0]["body"].get("stream") is True, "one answering dispatch, made with stream=true"
    record("progressive_streaming", {
        "prompt": LONG_PROMPT, "chunk_events": len(chunks), "first_chunk_s": first, "last_chunk_s": last, "done_s": done["_t"],
        "distinct_arrival_instants": len({c["_t"] for c in chunks}), "answer_chars": len(text), "model_identity": ident,
        "arrival_offsets_s_first_30": [c["_t"] for c in chunks[:30]], "answering_dispatches": len(answering),
    })


def test_S4_S5_S6_real_stop_hangs_up_on_the_model_and_leaves_no_phantom_turn(server, alice, tap):
    sid = str(uuid.uuid4())
    aborts0, lines0 = tap.client_aborts, tap.relayed_lines
    events = _stream(alice, LONG_PROMPT, sid, stop_after_chunks=6)
    stopped_at = time.monotonic()
    assert sum(e["type"] == "chunk" for e in events) == 6 and not any(e["type"] == "done" for e in events)
    # ORNEUR hung up on the (real) provider connection promptly...
    end = time.monotonic() + 8
    while time.monotonic() < end and tap.client_aborts == aborts0:
        time.sleep(0.05)
    assert tap.client_aborts == aborts0 + 1, "ORNEUR never closed its connection to the model: Stop did not stop the generation"
    abort_delay = time.monotonic() - stopped_at
    # ...and nothing more is relayed afterwards.
    time.sleep(0.4)
    relayed_at_abort = tap.relayed_lines
    time.sleep(2.0)
    assert tap.relayed_lines == relayed_at_abort, "pieces kept flowing from the model after Stop"
    assert tap.open_streams == 0
    # No phantom turn; the conversation is immediately usable; the next prompt carries no trace of the abandoned reply.
    assert _transcript(alice, sid) == []
    n0 = len(tap.requests)
    events2 = _stream(alice, "Reply with the single word: ready.", sid)
    assert events2[-1]["type"] == "done" and events2[-1]["persisted"] == "saved"
    rows = _transcript(alice, sid)
    assert [r[0] for r in rows] == ["user", "assistant"] and rows[0][1] == "Reply with the single word: ready."
    ctx = json.dumps([r["body"].get("messages") for r in tap.requests[n0:] if (r["body"].get("messages") or [{}])[-1].get("content") == "Reply with the single word: ready."])
    assert "lighthouse" not in ctx.lower(), "the abandoned prompt/partial reply leaked into later model context"
    record("stop_cancellation", {
        "chunks_seen_before_stop": 6, "provider_connection_closed_after_s": round(abort_delay, 3), "lines_relayed_at_abort": relayed_at_abort,
        "lines_relayed_2s_later": tap.relayed_lines, "committed_messages_after_stop": 0, "next_turn_persisted": True,
        "abort_log": tap.abort_log[-1:],
    })
