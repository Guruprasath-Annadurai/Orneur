"""
Tests for orca/serve/ratelimit.py.

Real gap this locks in: /api/chat and /api/stream used to only check
quota `if user:` — anonymous requests had zero rate limit, and
/api/code/run (spawns a real subprocess per request) had no limit at all.
These tests exercise the in-process fallback path (no Redis in test env),
which is also what most real Orca deployments actually run on.
"""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from orca.serve import ratelimit


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Minimal stand-in for fastapi.Request — only the attributes ratelimit.py touches."""
    def __init__(self, host="1.2.3.4", xff=None):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = _FakeClient(host)


@pytest.fixture(autouse=True)
def _reset_local_counters():
    """Each test gets a clean in-process counter dict — state otherwise leaks between tests."""
    ratelimit._local_counters.clear()
    yield
    ratelimit._local_counters.clear()


def test_get_client_ip_uses_direct_peer_when_no_xff():
    req = _FakeRequest(host="10.0.0.5")
    assert ratelimit.get_client_ip(req) == "10.0.0.5"


def test_get_client_ip_prefers_x_forwarded_for():
    """Behind a reverse proxy (Fly.io, nginx), request.client.host is the proxy's IP, not the real client's."""
    req = _FakeRequest(host="127.0.0.1", xff="203.0.113.9, 10.0.0.1")
    assert ratelimit.get_client_ip(req) == "203.0.113.9"


def test_get_client_ip_handles_missing_client():
    req = _FakeRequest()
    req.client = None
    assert ratelimit.get_client_ip(req) == "unknown"


def test_check_rate_limit_allows_within_limit():
    for i in range(5):
        allowed, count, _ = ratelimit.check_rate_limit("test-key-1", limit=5, window_seconds=60)
        assert allowed is True
        assert count == i + 1


def test_check_rate_limit_blocks_over_limit():
    for _ in range(5):
        ratelimit.check_rate_limit("test-key-2", limit=5, window_seconds=60)
    allowed, count, retry_after = ratelimit.check_rate_limit("test-key-2", limit=5, window_seconds=60)
    assert allowed is False
    assert count == 6
    assert retry_after > 0


def test_check_rate_limit_independent_keys_dont_interfere():
    """Different keys (different IPs, or different endpoints for the same IP) must not share a counter."""
    for _ in range(5):
        ratelimit.check_rate_limit("key-a", limit=5, window_seconds=60)
    allowed, count, _ = ratelimit.check_rate_limit("key-b", limit=5, window_seconds=60)
    assert allowed is True
    assert count == 1


def test_check_rate_limit_never_raises_on_bad_input():
    """A rate limiter that crashes the request it's protecting defeats its own purpose."""
    allowed, count, retry_after = ratelimit.check_rate_limit("edge-case", limit=0, window_seconds=1)
    assert isinstance(allowed, bool)


def test_local_counters_cleared_when_growing_unbounded(monkeypatch):
    """Guards against unbounded memory growth across many distinct IPs — real risk at 10K+ user scale."""
    ratelimit._local_counters.clear()
    for i in range(50_001):
        ratelimit._local_counters[f"synthetic-key-{i}"] = (0, 1)
    # Next real call should detect the size and clear before adding its own entry
    ratelimit.check_rate_limit("trigger-clear", limit=100, window_seconds=60)
    assert len(ratelimit._local_counters) <= 50_001  # cleared, then this call's own entry added back


def test_enforce_allows_under_limit():
    req = _FakeRequest(host="9.9.9.9")
    rule = ratelimit.RateLimitRule(limit=5, window_seconds=60, label="test_enforce_ok")
    for _ in range(4):
        ratelimit.enforce(req, rule)  # must not raise


def test_enforce_raises_429_over_limit():
    req = _FakeRequest(host="9.9.9.8")
    rule = ratelimit.RateLimitRule(limit=2, window_seconds=60, label="test_enforce_block")
    ratelimit.enforce(req, rule)
    ratelimit.enforce(req, rule)
    with pytest.raises(HTTPException) as exc_info:
        ratelimit.enforce(req, rule)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_enforce_extra_key_gives_independent_buckets_per_endpoint():
    """Same IP, different endpoints (login vs signup) must not share a rate limit bucket."""
    req = _FakeRequest(host="9.9.9.7")
    rule = ratelimit.RateLimitRule(limit=1, window_seconds=60, label="test_enforce_extra")
    ratelimit.enforce(req, rule, extra_key="login")
    ratelimit.enforce(req, rule, extra_key="signup")  # different extra_key — must not raise
    with pytest.raises(HTTPException):
        ratelimit.enforce(req, rule, extra_key="login")  # second hit on the SAME extra_key must raise
