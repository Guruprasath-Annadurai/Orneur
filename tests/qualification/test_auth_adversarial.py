"""Independent Authentication & Access Control Red Team Suite.

Evaluates adversarial authentication behavior across ORNEUR serving endpoints:
- Missing vs Garbage vs Expired vs Revoked tokens
- Logout and Logout-All revocation enforcement
- Cross-user session access
- Rejection of non-session token types (reset, verify)
- Proof of zero model dispatches on rejected probes
"""
from __future__ import annotations

import json
import pytest
from starlette.testclient import TestClient

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


# Target routes accepting optional or required credentials that access model/session data
GUARDED_OPTIONAL = [
    ("POST", "/api/chat", {"message": "hello", "session_id": "probe-sess-001"}),
    ("POST", "/api/stream", {"message": "hello", "session_id": "probe-sess-002"}),
    ("GET", "/api/sessions", None),
    ("GET", "/api/session/probe-sess-003/messages", None),
]

GUARDED_STRICT = [
    ("GET", "/api/auth/me", None),
    ("POST", "/api/auth/logout", None),
]


@pytest.fixture
def fake(client, monkeypatch):  # noqa: F811
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    f = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra", "llama3.2:1b"))
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    yield f
    f.__exit__(None, None, None)


def _execute(client: TestClient, method: str, path: str, body: dict | None, headers: dict):
    if method == "GET":
        return client.get(path, headers=headers)
    elif method == "POST":
        if "stream" in path:
            with client.stream("POST", path, json=body, headers=headers) as r:
                r.read()
                return r
        return client.post(path, json=body, headers=headers)
    raise ValueError(f"Unknown method {method}")


class TestAuthenticationRedTeam:
    def test_anonymous_request_without_header_permitted_on_optional_routes(self, client: TestClient, fake: FakeOllama):
        """No Authorization header sent where anonymous access is permitted."""
        resp = client.get("/api/sessions")
        # Should succeed (200) or return anonymous list, never 401
        assert resp.status_code != 401, f"Expected non-401 for anonymous access, got {resp.status_code}"

    def test_garbage_bearer_token_refused_with_401_and_zero_dispatches(self, client: TestClient, fake: FakeOllama):
        """Presented-but-invalid credentials must return 401, never anonymous fallback."""
        headers = {"Authorization": "Bearer not-a-valid-token-at-all"}
        initial_dispatches = len(fake.requests)

        for method, path, body in GUARDED_OPTIONAL:
            resp = _execute(client, method, path, body, headers)
            assert resp.status_code == 401, (
                f"Fail-open defect! {method} {path} returned {resp.status_code} instead of 401"
            )

        assert len(fake.requests) == initial_dispatches, (
            f"Model dispatch leakage: {len(fake.requests) - initial_dispatches} requests reached Ollama"
        )

    def test_expired_bearer_token_refused_with_401(self, client: TestClient, fake: FakeOllama):
        """An expired JWT must return 401, never anonymous fallback."""
        from orca.auth.crypto import create_token

        _, uid = _signup(client)
        expired_token = create_token({"sub": uid, "type": "session", "jti": "exp-01"}, expires_in=-120)
        headers = _hdr(expired_token)
        initial_dispatches = len(fake.requests)

        for method, path, body in GUARDED_OPTIONAL:
            resp = _execute(client, method, path, body, headers)
            assert resp.status_code == 401, (
                f"Expired token treated as anonymous! {method} {path} gave {resp.status_code}"
            )

        assert len(fake.requests) == initial_dispatches

    def test_revoked_token_after_logout_refused_with_401(self, client: TestClient, fake: FakeOllama):
        """After /api/auth/logout, the revoked token must return 401 across all endpoints."""
        token, _ = _signup(client)
        headers = _hdr(token)

        me_resp = client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 200

        logout_resp = client.post("/api/auth/logout", headers=headers)
        assert logout_resp.status_code == 200

        # Now verify probe against guarded endpoints
        initial_dispatches = len(fake.requests)
        for method, path, body in GUARDED_OPTIONAL:
            resp = _execute(client, method, path, body, headers)
            assert resp.status_code == 401, (
                f"Revoked token after logout accepted! {method} {path} returned {resp.status_code}"
            )

        assert len(fake.requests) == initial_dispatches

    def test_logout_all_invalidates_all_device_tokens(self, client: TestClient, fake: FakeOllama):
        """Logout-all must revoke all active session tokens issued to that user."""
        from orca.auth.routes import _make_response
        from orca.auth.store import create_user

        user = create_user("logout-all-test@example.com", "Secure-Password-123!", "Test User")
        device_1_token = _make_response(user)["token"]
        device_2_token = _make_response(user)["token"]

        assert client.get("/api/auth/me", headers=_hdr(device_2_token)).status_code == 200

        logout_all_resp = client.post("/api/auth/logout-all", headers=_hdr(device_1_token))
        assert logout_all_resp.status_code == 200

        for tok, label in [(device_1_token, "device-1"), (device_2_token, "device-2")]:
            for method, path, body in GUARDED_OPTIONAL:
                resp = _execute(client, method, path, body, _hdr(tok))
                assert resp.status_code == 401, (
                    f"Token {label} still active after logout-all on {method} {path} ({resp.status_code})"
                )

    @pytest.mark.parametrize("kind", ["reset", "email_verification", "2fa_pending"])
    def test_non_session_token_types_rejected(self, client: TestClient, fake: FakeOllama, kind: str):
        """Tokens with non-session types must not be admitted to session routes."""
        from orca.auth.crypto import create_token

        _, uid = _signup(client)
        bad_token = create_token({"sub": uid, "type": kind, "jti": f"{kind}-jti"}, expires_in=3600)
        headers = _hdr(bad_token)

        for method, path, body in GUARDED_OPTIONAL:
            resp = _execute(client, method, path, body, headers)
            assert resp.status_code == 401

    def test_cross_user_session_access_denied(self, client: TestClient, fake: FakeOllama):
        """User A must receive 403 or 404 when querying User B's session."""
        tok_a, _ = _signup(client)
        tok_b, _ = _signup(client)

        create_resp = client.post(
            "/api/sessions",
            headers=_hdr(tok_a),
            json={"title": "User A Private Session"},
        )
        assert create_resp.status_code in (200, 201)
        session_id = create_resp.json().get("id") or create_resp.json().get("session_id")
        assert session_id

        # User B attempts to access User A's session
        access_resp = client.get(f"/api/session/{session_id}/messages", headers=_hdr(tok_b))
        assert access_resp.status_code in (403, 404), (
            f"Cross-user session breach! Status: {access_resp.status_code}"
        )
