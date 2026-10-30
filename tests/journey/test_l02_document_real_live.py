"""L02-02 -- document conversation against a REAL local model behind the recording tap (evidence class: LIVE_API + real Ollama).

The weights are third-party (whatever ``ORNEUR_JOURNEY_MODEL`` names; ``llama3.2:1b`` when run with that literal tag). Nothing asserted depends on what the model
says: only on what ORNEUR sent to it, when, how many times, and what ORNEUR stored/charged. Measurements go to ``$ORNEUR_L02_EVIDENCE_DIR``.

Run:  ORNEUR_JOURNEY_MODEL=llama3.2:1b pytest tests/journey/test_l02_document_real_live.py -p no:cacheprovider -v
Set ``L02_BASELINE_MEASURE=1`` to record without asserting the discarded-dispatch count (used to measure the unfixed baseline).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

from tests.journey.harness import JOURNEY_MODEL, OLLAMA_HOST, User

EVIDENCE = Path(os.environ.get("ORNEUR_L02_EVIDENCE_DIR", "/tmp/orneur-l02-evidence"))
BASELINE = os.environ.get("L02_BASELINE_MEASURE") == "1"
DOC = (b"Study notes: photosynthesis.\nPhotosynthesis converts light energy into chemical energy stored as glucose. "
       b"It happens in the chloroplasts. The light-dependent reactions occur in the thylakoid membranes and produce ATP and NADPH. "
       b"The Calvin cycle occurs in the stroma and uses ATP and NADPH to fix carbon dioxide into glucose.\n")
Q = os.environ.get("L02_Q", "Where in the cell does the Calvin cycle occur, according to my notes?")


def record(name: str, data: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    data = {"model_tag": JOURNEY_MODEL, "ollama_host": OLLAMA_HOST, "weights": "third-party (not an ORNEUR-native model)",
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "baseline_measure": BASELINE, **data}
    (EVIDENCE / f"l02_real_{name}.json").write_text(json.dumps(data, indent=2))


@pytest.fixture(scope="module")
def student(server):
    return User(server.base, "l02doc")


def _upload(user: User, text: bytes = DOC, name: str = "notes.txt", sid: str | None = None) -> dict:
    r = user.http.post("/api/docs/upload", files={"file": (name, text, "text/plain")}, params={"session_id": sid} if sid else {},
                       headers={"Authorization": f"Bearer {user.token}"})
    assert r.status_code == 200, r.text
    return r.json()


def _stream(user: User, message: str, sid: str, stop_after: int | None = None):
    events, t0, n = [], time.monotonic(), 0
    with user.http.stream("POST", "/api/stream", json={"message": message, "session_id": sid, "model_variant": "core"},
                          headers={"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                ev["_t"] = round(time.monotonic() - t0, 3)
                events.append(ev)
                n += ev["type"] == "chunk"
                if stop_after and n >= stop_after:
                    break
    return events


def _classify(requests):
    """Provider requests for one turn, by role. With a real model the Kernel's plan decides the route: a document question is usually evidence-routed
    (Truth Fabric: one non-streamed answer carrying ``[Retrieved context]`` plus claim-verification calls) and otherwise goes through the document
    pipeline (deep-RAG stages plus ONE streamed answer carrying ``[Document context``)."""
    out = {"truth_fabric_answer": 0, "truth_fabric_verification": 0, "streamed_answer": 0, "kernel_discarded_answer": 0, "rag_stage": 0, "side_call": 0}
    for r in requests:
        b = r["body"]
        last = (b.get("messages") or [{}])[-1].get("content", "") if b.get("messages") else b.get("prompt", "")
        if "Extract factual relationships" in last:
            out["side_call"] += 1
        elif "[Retrieved context]" in last:
            out["truth_fabric_answer"] += 1
        elif last.lstrip().startswith(("CLAIM", "CLAIM A")) or "EVIDENCE:" in last[:400]:
            out["truth_fabric_verification"] += 1
        elif b.get("stream") and "[Document context" in last:
            out["streamed_answer"] += 1
        elif not b.get("stream") and last.strip() == Q:
            out["kernel_discarded_answer"] += 1
        else:
            out["rag_stage"] += 1
    return out


def test_L02_02_real_model_document_turn_dispatches_and_timing(server, student, tap):
    sid = _upload(student)["session_id"]
    n0 = len(tap.requests)
    t0 = time.monotonic()
    events = _stream(student, Q, sid)
    wall = round(time.monotonic() - t0, 3)
    done = events[-1]
    chunks = [e for e in events if e["type"] == "chunk"]
    assert done["type"] == "done" and done["persisted"] == "saved" and chunks
    counts = _classify(tap.requests[n0:])
    assert counts["truth_fabric_answer"] + counts["streamed_answer"] == 1, f"exactly one answering dispatch expected: {counts}"
    if not BASELINE:
        assert counts["kernel_discarded_answer"] == 0, f"a discarded Kernel answer was generated: {counts}"
    assert done["source_summary"]["grounding"] in ("cited", "retrieved_not_cited", "evidence_state_only")
    record("document_turn_dispatches", {
        "question": Q, "dispatch_counts": counts, "total_provider_requests": len(tap.requests) - n0,
        "first_chunk_s": chunks[0]["_t"], "done_s": done["_t"], "wall_s": wall, "chunk_events": len(chunks),
        "grounding": done["source_summary"]["grounding"], "sources": len(done["sources"]),
        "delivery": done.get("delivery"), "route": "truth_fabric" if counts["truth_fabric_answer"] else "document_pipeline",
    })


def test_L02_02_real_model_unrelated_question_abstention_notice_reaches_the_model(server, student, tap):
    sid = _upload(student)["session_id"]
    n0 = len(tap.requests)
    events = _stream(student, "What is the capital of Australia?", sid)
    done = events[-1]
    sent = json.dumps([r["body"] for r in tap.requests[n0:]])
    assert done["type"] == "done"
    assert "NO passage in the uploaded documents matched" in sent, "an unrelated question must tell the model the documents do not contain the answer"
    assert done["source_summary"]["grounding"] == "none" and done["sources"] == []
    record("unrelated_question", {"grounding": done["source_summary"]["grounding"], "answer_chars": len("".join(e["text"] for e in events if e["type"] == "chunk")),
                                  "note": "what the model then says is not asserted; only that it was told, and that no source card was invented"})


def test_L02_02_real_model_stop_in_a_document_turn_hangs_up_and_stores_nothing(server, student, tap):
    sid = _upload(student)["session_id"]
    prompt = "Using my notes, write a long, detailed essay of at least 400 words about photosynthesis. Use several paragraphs."
    a0 = tap.client_aborts if hasattr(tap, "client_aborts") else None
    n0 = len(tap.requests)
    events = _stream(student, prompt, sid, stop_after=5)
    assert sum(e["type"] == "chunk" for e in events) >= 5
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and tap.open_streams:
        time.sleep(0.05)
    assert tap.open_streams == 0, "the provider connection is still open after Stop"
    r = student.get(f"/api/session/{sid}/messages")
    assert r.status_code == 200 and r.json()["messages"] == [], "no phantom turn after Stop"
    record("document_stop", {"chunks_before_stop": 5, "provider_streams_open_after": tap.open_streams, "messages_stored": 0,
                             "requests": len(tap.requests) - n0})
