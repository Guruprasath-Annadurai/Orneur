from __future__ import annotations

from types import SimpleNamespace

from orca.serve.availability import NOT_AVAILABLE, discover, native_status, resolve_honest


def test_native_families_are_not_available():
    assert native_status("GENESIS") == NOT_AVAILABLE
    assert native_status("novus") == NOT_AVAILABLE
    assert native_status("aeternum") == NOT_AVAILABLE
    body = discover(installed=[])
    assert body["genesis"] == NOT_AVAILABLE
    assert body["ollama_status"] == NOT_AVAILABLE
    assert body["paid_fallback"] == "refused"
    assert body["spending_authorized"] is False


def test_empty_provider_is_unavailable_not_native():
    missing = resolve_honest("core", resolver=lambda tier: (_ for _ in ()).throw(RuntimeError("none")))
    assert missing["status"] == NOT_AVAILABLE
    assert missing["served_model"] is None
    assert missing["native_family"] is None


def test_paid_backend_stays_unavailable_while_spending_is_denied():
    paid = SimpleNamespace(backend="openai", model="gpt-test", data_left_infrastructure=True)
    body = resolve_honest("ultra", resolver=lambda tier: paid)
    assert body["status"] == NOT_AVAILABLE
    assert body["reason"] == "paid_backend_refused"
    assert body["served_model"] is None


def test_local_backend_keeps_its_own_name():
    local = SimpleNamespace(backend="ollama", model="orca-nano", data_left_infrastructure=False)
    body = resolve_honest("nano", resolver=lambda tier: local)
    assert body["status"] == "available"
    assert body["served_model"] == "orca-nano"
    assert body["native_family"] is None
    assert "genesis" not in body["served_model"]
