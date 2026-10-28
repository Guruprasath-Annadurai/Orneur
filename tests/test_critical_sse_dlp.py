"""Antigravity SSE DLP split-secret reproducer — failing-before on per-chunk scan."""

from __future__ import annotations

import uuid
from threading import Event

from orca.serve.dlp import scan_output
from orca.serve.stream_dlp import StreamRedactor, redact_structure

SECRET = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
PEM_HEADER = "-----BEGIN RSA PRIVATE KEY-----\n"
PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\n"
PEM_FOOTER = "-----END RSA PRIVATE KEY-----"
PEM = PEM_HEADER + PEM_BODY + PEM_FOOTER


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
    assert "abcdefghijklmnopqrstuvwxyz" not in emitted
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


def test_pem_body_is_held_until_end_then_redacted():
    redactor = StreamRedactor()
    a = redactor.push(PEM_HEADER)
    b = redactor.push(PEM_BODY)
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" not in a + b
    text = a + b + redactor.push(PEM_FOOTER) + redactor.finish()
    assert "BEGIN RSA PRIVATE KEY" not in text
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" not in text
    assert "REDACTED" in text


def test_pem_character_by_character_never_leaks_body():
    """Antigravity char-by-char PEM reproducer — must not emit key material."""
    redactor = StreamRedactor()
    emitted = "".join(redactor.push(ch) for ch in PEM) + redactor.finish()
    assert "BEGIN RSA PRIVATE KEY" not in emitted
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" not in emitted
    assert "END RSA PRIVATE KEY" not in emitted
    assert "REDACTED" in emitted
    assert PEM_BODY.strip() not in redactor.safe_text()


def test_pem_all_supported_delimiters_char_by_char():
    labels = ["", "RSA ", "EC ", "DSA ", "OPENSSH ", "ENCRYPTED "]
    for label in labels:
        block = f"-----BEGIN {label}PRIVATE KEY-----\nSECRETBODY{label.strip()}\n-----END {label}PRIVATE KEY-----"
        redactor = StreamRedactor()
        out = "".join(redactor.push(ch) for ch in block) + redactor.finish()
        assert "SECRETBODY" not in out
        assert "BEGIN" not in out
        assert "REDACTED" in out


def test_pem_unclosed_fail_closed_on_finish():
    redactor = StreamRedactor()
    redactor.push(PEM_HEADER + PEM_BODY)
    assert "MIIEvQ" not in redactor.finish()
    assert "REDACTED" in redactor.safe_text()


def test_cancel_does_not_flush_hold():
    redactor = StreamRedactor()
    redactor.push(SECRET[:10])
    redactor.cancel()
    assert redactor.finish() == ""
    assert SECRET not in redactor.safe_text()
    pem = StreamRedactor()
    pem.push(PEM_HEADER + PEM_BODY)
    pem.cancel()
    assert pem.finish() == ""
    assert "MIIEvQ" not in pem.safe_text()


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


def test_stream_complete_pem_char_chunks_and_transcript(isolated_home, ollama_fixture):
    from orca.auth.store import User
    from orca.serve import conversations
    from orca.serve.inference import stream_complete

    user = User(id="u-pem", email="pem@example.com", name="u", tier="free", verified=True)
    sid = "pem" + uuid.uuid4().hex[:12]
    body = stream_complete(
        user=user,
        message="show key",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=sid,
        transport_stream=lambda host, model, msg: iter(list(PEM)),
        synthetic_provider=True,
    )
    joined = "".join(body["chunks"])
    assert "MIIEvQ" not in joined
    assert "MIIEvQ" not in body["text"]
    transcript = conversations.transcript(sid)
    for row in transcript["messages"]:
        assert "MIIEvQ" not in row["content"]
        assert "BEGIN RSA PRIVATE KEY" not in row["content"]
