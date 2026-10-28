"""Antigravity SSE DLP split-secret reproducer — failing-before on per-chunk scan."""

from __future__ import annotations

import uuid
from threading import Event

from orca.serve.dlp import scan_output
from orca.serve.stream_dlp import StreamRedactor, redact_structure

SECRET = "sk-abcdefghijklmnopqrstuvwxyz1234567890"


def test_per_chunk_scan_was_the_leak_reproducer():
    first, second = SECRET[:12], SECRET[12:]
    leaked = scan_output(first)["safe_text"] + scan_output(second)["safe_text"]
    assert SECRET in leaked


def test_stateful_redactor_withholds_split_secret():
    redactor = StreamRedactor()
    a = redactor.push(SECRET[:12])
    assert "sk-" not in a
    b = redactor.push(SECRET[12:])
    text = a + b + redactor.finish()
    assert SECRET not in text
    assert "REDACTED" in text


def test_per_character_and_two_chunk_and_single_chunk():
    redactor = StreamRedactor()
    emitted = "".join(redactor.push(ch) for ch in SECRET) + redactor.finish()
    assert SECRET not in emitted
    one = StreamRedactor()
    assert SECRET not in (one.push(SECRET) + one.finish())
    two = StreamRedactor()
    body = two.push("hello ") + two.push(SECRET[:8]) + two.push(SECRET[8:] + "!") + two.finish()
    assert SECRET not in body
    assert "hello" in body


def test_long_token_fail_closed_and_malformed_emits():
    redactor = StreamRedactor()
    huge = "sk-" + ("a" * 400)
    out = redactor.push(huge) + redactor.finish()
    assert "sk-" + ("a" * 20) not in out
    ok = StreamRedactor()
    text = ok.push("sk-short!") + ok.finish()
    assert "sk-short!" in text


def test_cancel_does_not_flush_hold():
    redactor = StreamRedactor()
    redactor.push(SECRET[:10])
    redactor.cancel()
    assert redactor.finish() == ""
    assert SECRET not in redactor.safe_text()


def test_sse_metadata_is_redacted():
    payload = {"type": "error", "error": f"upstream {SECRET}", "detail": {"raw": SECRET}}
    safe = redact_structure(payload)
    assert SECRET not in str(safe)


def test_stream_complete_split_secret(isolated_home, ollama_fixture):
    from orca.auth.store import User
    from orca.serve.inference import stream_complete

    user = User(id="u1", email="u1@example.com", name="u", tier="free", verified=True)
    body = stream_complete(
        user=user,
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=uuid.uuid4().hex,
        transport_stream=lambda host, model, msg: iter([SECRET[:11], SECRET[11:]]),
        synthetic_provider=True,
    )
    assert SECRET not in "".join(body["chunks"])
    assert SECRET not in body["text"]
    cancel = Event()
    cancel.set()
    stopped = stream_complete(
        user=user,
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=uuid.uuid4().hex,
        transport_stream=lambda host, model, msg: iter([SECRET[:11], SECRET[11:]]),
        cancel=cancel,
        synthetic_provider=True,
    )
    assert stopped["cancelled"] is True
    assert SECRET not in stopped["text"]
