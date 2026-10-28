from __future__ import annotations

from types import SimpleNamespace

from orca.serve.availability import NOT_AVAILABLE, discover, native_status, probe_ollama, resolve_honest


def test_native_families_are_not_available():
    assert native_status("GENESIS") == NOT_AVAILABLE
    assert native_status("novus") == NOT_AVAILABLE
    assert native_status("aeternum") == NOT_AVAILABLE
    body = discover(installed=["llama"])
    assert body["genesis"] == NOT_AVAILABLE
    assert body["ollama_status"] == NOT_AVAILABLE
    assert body["live_probe"] == "not_probed"
    assert body["inference"] is False
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
    assert body["status"] == "resolved_not_inferred"
    assert body["inference"] is False
    assert body["served_model"] == "orca-nano"
    assert body["native_family"] is None
    assert "genesis" not in body["served_model"]


def test_probe_timeout_and_unreachable_are_not_inference():
    def timeout(url, timeout_s):
        raise TimeoutError("slow")

    timed = probe_ollama(host="http://127.0.0.1:9", transport=timeout)
    assert timed["status"] == NOT_AVAILABLE
    assert timed["reason"] == "provider_timeout"
    assert timed["inference"] is False

    def boom(url, timeout_s):
        raise ConnectionError("down")

    down = probe_ollama(host="http://127.0.0.1:9", transport=boom)
    assert down["status"] == NOT_AVAILABLE
    assert down["reason"] == "unreachable"
    assert down["inference"] is False

    live = probe_ollama(host="http://example.invalid", transport=lambda url, t: {"models": [{"name": "llama3"}]})
    assert live["status"] == "reachable"
    assert live["installed"] == ["llama3"]
    assert live["inference"] is False
    assert live["streaming_probed"] is False
    discovered = discover(probe=True, host="http://example.invalid", transport=lambda url, t: {"models": [{"name": "llama3"}]})
    assert discovered["ollama_status"] == "reachable_not_inferred"
    assert discovered["inference"] is False
    assert discovered["genesis"] == NOT_AVAILABLE
