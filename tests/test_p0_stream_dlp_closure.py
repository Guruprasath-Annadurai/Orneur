"""P0-1: streaming DLP must hold secrets across every split, including PEM."""

from __future__ import annotations

import uuid
from threading import Event

from orca.serve.dlp import scan_output
from orca.serve.stream_dlp import StreamRedactor

SECRET = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
AWS = "AKIAIOSFODNN7EXAMPLE"
GH = "ghp_0123456789012345678901234567890123"
BEARER = "Bearer " + ("tok_" + "x" * 24)
PEM_HEADER = "-----BEGIN RSA PRIVATE KEY-----"
PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7"
PEM_FOOTER = "-----END RSA PRIVATE KEY-----"
PEM = f"{PEM_HEADER}\n{PEM_BODY}\n{PEM_FOOTER}"


def _all_splits(secret: str) -> None:
    for i in range(len(secret) + 1):
        redactor = StreamRedactor()
        out = redactor.push(secret[:i]) + redactor.push(secret[i:]) + redactor.finish()
        assert secret not in out, (i, out)
        assert "BEGIN" not in out or "REDACTED" in out


def test_failing_before_per_chunk_scan_leaks_split_secret():
    first, second = SECRET[:12], SECRET[12:]
    leaked = scan_output(first)["safe_text"] + scan_output(second)["safe_text"]
    assert SECRET in leaked


def test_every_split_position_for_supported_secrets():
    for label, secret in (("openai", SECRET), ("aws", AWS), ("github", GH), ("bearer", BEARER), ("pem", PEM)):
        _all_splits(secret)


def test_character_by_character_pem_header_and_full_block():
    redactor = StreamRedactor()
    emitted = "".join(redactor.push(ch) for ch in PEM) + redactor.finish()
    assert PEM_BODY not in emitted
    assert "BEGIN RSA PRIVATE KEY" not in emitted
    assert "REDACTED" in emitted

    almost = StreamRedactor()
    parts = [almost.push(ch) for ch in PEM_HEADER[:-1]]
    assert PEM_HEADER[:-1] not in "".join(parts)
    parts.append(almost.push(PEM_HEADER[-1]))
    parts.append(almost.push("\n" + PEM_BODY + "\n"))
    assert PEM_BODY not in "".join(parts)
    parts.append(almost.push(PEM_FOOTER))
    parts.append(almost.finish())
    assert PEM_BODY not in "".join(parts)


def test_finish_and_cancel_never_flush_incomplete_pem_or_prefix():
    held = StreamRedactor()
    held.push(PEM_HEADER + "\n" + PEM_BODY)
    finished = held.finish()
    assert PEM_BODY not in finished
    assert "BEGIN" not in finished

    cancelled = StreamRedactor()
    cancelled.push(SECRET[:10])
    cancelled.cancel()
    assert cancelled.finish() == ""
    assert SECRET not in cancelled.safe_text()


def test_sse_bytes_from_stream_complete_match_persisted(isolated_home, ollama_fixture):
    from orca.auth.store import User
    from orca.serve import conversations
    from orca.serve.inference import stream_complete

    user = User(id="dlp-u", email="dlp@example.com", name="d", tier="free", verified=True)
    sid = uuid.uuid4().hex[:16]
    body = stream_complete(
        user=user,
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=sid,
        transport_stream=lambda host, model, msg: iter([PEM_HEADER[:10], PEM_HEADER[10:] + "\n", PEM_BODY + "\n", PEM_FOOTER]),
        synthetic_provider=True,
    )
    client_bytes = "".join(body["chunks"])
    assert PEM_BODY not in client_bytes
    assert PEM_BODY not in body["text"]
    assert client_bytes == body["text"] or body["text"] in client_bytes or "REDACTED" in body["text"]
    transcript = conversations.transcript(sid)
    stored = "".join(m["content"] for m in transcript["messages"] if m["role"] == "assistant")
    assert PEM_BODY not in stored
    assert "REDACTED" in stored

    cancel = Event()
    cancel.set()
    stopped = stream_complete(
        user=user,
        message="hello2",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=uuid.uuid4().hex[:16],
        transport_stream=lambda host, model, msg: iter([SECRET[:8], SECRET[8:]]),
        cancel=cancel,
        synthetic_provider=True,
    )
    assert stopped["cancelled"] is True
    assert SECRET not in stopped["text"]
    assert SECRET not in "".join(stopped["chunks"])
