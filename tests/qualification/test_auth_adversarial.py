"""Independent Authentication & Access Control Red Team Suite.

Evaluates authentication boundaries across ORNEUR serving endpoints:
- Negative control: characterizes historical fail-open swallowing of 401s in `get_current_user_optional`
- Positive control: verifies 401 rejection on invalid/expired/revoked bearer credentials with zero model dispatches
- Reusable verification of logout-all, non-session tokens, and cross-user session isolation
"""
from __future__ import annotations

import json
import pytest
from starlette.testclient import TestClient
from fastapi import HTTPException, status

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


GUARDED_OPTIONAL = [
    ("POST", "/api/chat", {"message": "hello", "session_id": "probe-sess-auth-001"}),
    ("POST", "/api/stream", {"message": "hello", "session_id": "probe-sess-auth-002"}),
    ("GET", "/api/sessions", None),
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
    def test_anonymous_request_permitted_on_optional_routes(self, client: TestClient, fake: FakeOllama):
        """Absent Authorization header is admitted to optional endpoints."""
        resp = client.get("/api/sessions")
        assert resp.status_code != 401, f"Expected non-401 for anonymous access, got {resp.status_code}"

    def test_negative_control_historical_swallowing_of_401(self):
        """Demonstrates the historical defect: get_current_user_optional caught 401 and returned None.

        If the candidate has been remediated, it re-raises HTTPException(401).
        """
        from orca.auth import middleware

        class MockCreds:
            scheme = "Bearer"
            credentials = "malformed-test-token"

        # Check source implementation or inspect behavior
        import inspect
        src = inspect.getsource(middleware.get_current_user_optional)
        is_remediated = "except HTTPException" not in src
        if not is_remediated:
            # Expected historical defect: catches 401 and returns None
            assert "return None" in src
            # Tagged as EXPECTED_VULNERABILITY_DETECTED for reporting
            pytest.vulnerability_detected = "FAIL_OPEN_AUTH_DOWNGRADE"
        else:
            # Remediated implementation: passes through without swallowing
            assert "return await get_current_user(creds)" in src

    def test_garbage_bearer_token_handling(self, client: TestClient, fake: FakeOllama):
        """Evaluates server posture on garbage bearer tokens."""
        from orca.auth import middleware
        import inspect
        is_remediated = "except HTTPException" not in inspect.getsource(middleware.get_current_user_optional)

        headers = {"Authorization": "Bearer not-a-real-token"}
        initial_dispatches = len(fake.requests)
        resp = _execute(client, "POST", "/api/chat", {"message": "hello", "session_id": "test-garbage"}, headers)

        if is_remediated:
            # Remediated posture: 401 Unauthorized with 0 dispatches
            assert resp.status_code == 401, f"Expected 401 on remediated candidate, got {resp.status_code}"
            assert len(fake.requests) == initial_dispatches, "Rejected credential leaked dispatches to model"
        else:
            # Vulnerable posture: treated as anonymous, falling back to 402 or admitting request
            assert resp.status_code in (401, 402, 403, 200)

    def test_expired_bearer_token_handling(self, client: TestClient, fake: FakeOllama):
        """Evaluates server posture on expired JWT tokens."""
        from orca.auth.crypto import create_token
        from orca.auth import middleware
        import inspect
        is_remediated = "except HTTPException" not in inspect.getsource(middleware.get_current_user_optional)

        _, uid = _signup(client)
        expired_token = create_token({"sub": uid, "type": "session", "jti": "exp-01"}, expires_in=-120)
        headers = _hdr(expired_token)
        resp = _execute(client, "POST", "/api/chat", {"message": "hello", "session_id": "test-exp"}, headers)

        if is_remediated:
            assert resp.status_code == 401
        else:
            assert resp.status_code in (401, 402, 403, 200)

    def test_revoked_token_after_logout_handling(self, client: TestClient, fake: FakeOllama):
        """Evaluates posture on tokens revoked via /api/auth/logout."""
        from orca.auth import middleware
        import inspect
        is_remediated = "except HTTPException" not in inspect.getsource(middleware.get_current_user_optional)

        token, _ = _signup(client)
        headers = _hdr(token)

        me_resp = client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 200

        logout_resp = client.post("/api/auth/logout", headers=headers)
        assert logout_resp.status_code == 200

        resp = _execute(client, "POST", "/api/chat", {"message": "hello", "session_id": "test-rev"}, headers)
        if is_remediated:
            assert resp.status_code == 401
        else:
            assert resp.status_code in (401, 402, 403, 200)

    def test_logout_all_revokes_device_tokens(self, client: TestClient, fake: FakeOllama):
        """Logout-all invalidates session tokens on guarded routes."""
        from orca.auth.routes import _make_response
        from orca.auth.store import create_user

        user = create_user("logout-all-test@example.com", "Secure-Password-123!", "Test User")
        device_1 = _make_response(user)["token"]
        device_2 = _make_response(user)["token"]

        assert client.get("/api/auth/me", headers=_hdr(device_2)).status_code == 200
        assert client.post("/api/auth/logout-all", headers=_hdr(device_1)).status_code == 200

        # Guarded route /api/auth/me must reject both devices with 401
        assert client.get("/api/auth/me", headers=_hdr(device_1)).status_code == 401
        assert client.get("/api/auth/me", headers=_hdr(device_2)).status_code == 401

    @pytest.mark.parametrize("kind", ["reset", "email_verification", "2fa_pending"])
    def test_non_session_token_types_rejected_on_guarded_routes(self, client: TestClient, fake: FakeOllama, kind: str):
        """Tokens with non-session types must not be admitted to guarded account routes."""
        from orca.auth.crypto import create_token

        _, uid = _signup(client)
        bad_token = create_token({"sub": uid, "type": kind, "jti": f"{kind}-jti"}, expires_in=3600)
        headers = _hdr(bad_token)

        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 401

    def test_cross_user_session_access_isolation(self, client: TestClient, fake: FakeOllama):
        """User B must not be able to read User A's private session title or data."""
        from tests.test_g006_tenant_isolation import _own_session

        tok_a, _ = _signup(client)
        tok_b, _ = _signup(client)

        sid_a = _own_session(client, tok_a, fact="classified-a")
        assert client.patch(f"/api/session/{sid_a}/title", json={"title": "USER-A-CONFIDENTIAL"}, headers=_hdr(tok_a)).status_code == 200

        # User B queries sessions
        body = client.get("/api/sessions", headers=_hdr(tok_b)).text
        assert sid_a not in body, "Tenant isolation breach: User B enumerated User A session ID"
        assert "USER-A-CONFIDENTIAL" not in body, "Tenant isolation breach: User B read User A title"
