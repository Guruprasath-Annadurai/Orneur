from __future__ import annotations

import pytest

from orca.serve.model_identity import model_identity
from orca.serve.uploads import UploadError, delete, read, store
from orca.serve.usage import UsageError, record_usage, reset_for_tests, snapshot


def test_uploads_are_tenant_separated(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    stored = store("user-a", "note.txt", b"hello")
    assert stored["nbytes"] == 5
    assert read("user-a", "note.txt") == b"hello"
    with pytest.raises(UploadError) as exc:
        read("user-b", "note.txt")
    assert exc.value.code == "not_found"
    with pytest.raises(UploadError):
        store("user-a", "../escape.txt", b"nope")
    with pytest.raises(UploadError):
        store("user-a", "big.bin", b"x" * (1_048_576 + 1))
    delete("user-a", "note.txt")
    with pytest.raises(UploadError):
        read("user-a", "note.txt")


def test_usage_refuses_paid_and_native_mislabel():
    reset_for_tests()
    row = record_usage(user_id="user-a", model="local-test", backend="local", tokens_in=3, tokens_out=5)
    assert row["tokens_in"] == 3
    body = snapshot("user-a")
    assert body["tokens_out"] == 5
    assert body["paid_calls"] == 0
    assert snapshot("user-b")["calls"] == 0
    with pytest.raises(UsageError) as exc:
        record_usage(user_id="user-a", model="gpt-4", backend="openai", tokens_in=1, tokens_out=1)
    assert exc.value.code == "paid_backend_refused"
    with pytest.raises(UsageError) as exc:
        record_usage(
            user_id="user-a",
            model="someone-else",
            backend="ollama",
            tokens_in=1,
            tokens_out=1,
            native_family="genesis",
        )
    assert exc.value.code == "native_identity_refused"


def test_model_identity_keeps_external_name():
    body = model_identity(
        requested_variant="genesis",
        served_tier=None,
        served_model="gpt-test",
        backend="openai",
        reason="cost_routing_escalation",
        data_left_infrastructure=True,
    )
    assert body["served_model"] == "gpt-test"
    assert body["backend"] == "openai"
    assert body["substituted"] is True
    assert body["data_left_infrastructure"] is True
    assert "genesis" not in (body["served_model"] or "")
    missing = model_identity(requested_variant="novus", served_tier=None, served_model=None, backend="none")
    assert missing["served_model"] is None
    assert missing["served_tier"] is None
