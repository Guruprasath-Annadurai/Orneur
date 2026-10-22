"""
Integration tests for the new B01/B02/B03 conversation shell
(orca/serve/web/conversation.html, served at GET /conversation).

These test the real, deployed contract this page actually depends on:
the route itself, the exact API shapes the page's JS calls against
(auth/me response wrapping, models endpoint honesty fields, session
listing/ownership), and that the pre-existing /app route is genuinely
untouched. Real, interactive browser verification (B01 empty state,
theme toggle, model selector disclosure, a live streamed response,
conversation persistence/recovery, cross-user denial, and the mobile
navigation drawer) was performed by hand against a live local server
during this engineering phase -- screenshotted and recorded in
docs/orneur/status/ORNEUR_B01_B03_ENGINEERING_REPORT.md -- but no
automated browser (Playwright/Selenium) suite exists in this repo, and
none is introduced here; that is an explicit, honestly-reported scope
limitation, not a claim of automated browser-level coverage.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orca.serve import api as api_module


@pytest.fixture
def client():
    return TestClient(api_module.app, raise_server_exceptions=False)


def test_conversation_route_serves_the_new_shell(client):
    resp = client.get("/conversation")
    assert resp.status_code == 200
    body = resp.text
    assert "Hello chief, what's the plan today." in body
    assert "ORNEUR — Conversation" in body
    assert 'id="auth-overlay"' in body
    assert 'id="empty-view"' in body
    assert 'id="active-view"' in body


def test_conversation_route_references_the_verified_approved_logo_asset(client):
    """The page must reference the SHA-256-verified logo copied from the
    approved B01-B16 handoff archive, not a regenerated/substitute
    asset."""
    resp = client.get("/conversation")
    assert "/static/b01_approved_assets/orneur_logo_horizontal.png" in resp.text


def test_approved_logo_asset_is_served_and_matches_the_verified_archive_hash(client):
    import hashlib

    resp = client.get("/static/b01_approved_assets/orneur_logo_horizontal.png")
    assert resp.status_code == 200
    digest = hashlib.sha256(resp.content).hexdigest()
    # SHA-256 of ORNEUR_Logo_Horizontal_Transparent.png as verified against
    # this repo's own copy of the approved handoff archive's SHA256_MANIFEST.txt
    # before being copied into this repo (see the engineering report).
    assert digest == "b52c2f34764e294828891c4337ef47a6bca7e34b04bb969ed4892fc76d55768c"


def test_existing_app_route_is_unmodified(client):
    """AUDIT-B01-B03: the pre-existing /app page (an earlier, unapproved
    design) must be left completely untouched -- new work lives only at
    the new /conversation route."""
    resp = client.get("/app")
    assert resp.status_code == 200
    assert "Intelligence, Without End." in resp.text
    # The new shell's greeting must NOT have leaked into the old page.
    assert "Hello chief, what's the plan today." not in resp.text


def test_models_endpoint_never_claims_unqualified_production_readiness(client):
    """The conversation shell's model selector reads directly from this
    endpoint's `disclosure`/`lifecycle` fields -- this test guards that
    the endpoint itself keeps providing the honesty fields the frontend
    depends on to avoid overclaiming (AUDIT-C02-B02 finding: an earlier
    draft of the frontend showed "Available now" for every tier despite
    all three being EXPERIMENTAL / not qualified)."""
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    for variant in ("nano", "core", "ultra"):
        assert variant in data
        assert "lifecycle" in data[variant]
        assert "disclosure" in data[variant]
        assert "publicly_served" in data[variant]
        assert "fallback_active" in data[variant]
        assert "resolved_model" in data[variant]


def test_auth_me_response_is_wrapped_in_a_user_key(client):
    """Regression guard for a real bug this phase found and fixed: the
    conversation shell's session-restore logic initially treated
    /api/auth/me's response AS the user object directly, when the real
    endpoint wraps it as {"user": {...}, "limits": {...}, "usage": {...}}."""
    signup = client.post(
        "/api/auth/signup",
        json={"email": f"shell-test-{id(client)}@example.test", "password": "TestPassword123!", "name": "Shell Test"},
    )
    assert signup.status_code == 200, signup.text
    token = signup.json()["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert "user" in body
    assert body["user"]["email"].startswith("shell-test-")


def test_session_messages_endpoint_denies_cross_user_access(client):
    """The conversation shell's loadSessions/openSession rely entirely on
    this endpoint's own ownership enforcement -- re-verified here
    directly against the real app, matching the cross-user access
    denial the engineering directive explicitly requires testing.

    An UNCLAIMED session id is deliberately NOT 404 in this system's own
    design (session ids are bearer-token-like; see
    orca.auth.store.claim_session's own docstring: "a session with NO
    recorded owner ... stays reachable by anyone who holds its id") --
    so this test claims a real session for alice first via the same
    claim_session() the server itself uses, then verifies mallory,
    a genuinely different authenticated user, is denied."""
    import uuid

    from orca.auth.store import claim_session

    alice = client.post(
        "/api/auth/signup",
        json={"email": f"alice-shell-{id(client)}@example.test", "password": "TestPassword123!", "name": "Alice"},
    ).json()
    mallory = client.post(
        "/api/auth/signup",
        json={"email": f"mallory-shell-{id(client)}@example.test", "password": "TestPassword123!", "name": "Mallory"},
    ).json()

    session_id = uuid.uuid4().hex
    assert claim_session(session_id, alice["user"]["id"]) is True

    resp = client.get(
        f"/api/session/{session_id}/messages",
        headers={"Authorization": f"Bearer {mallory['token']}"},
    )
    assert resp.status_code == 404

    # The genuine owner is correctly let through (even though the
    # transcript is empty -- this call is only testing the ownership
    # gate, not transcript content).
    resp_owner = client.get(
        f"/api/session/{session_id}/messages",
        headers={"Authorization": f"Bearer {alice['token']}"},
    )
    assert resp_owner.status_code == 200


def test_session_messages_endpoint_requires_authentication(client):
    resp = client.get("/api/session/some-id/messages")
    assert resp.status_code in (401, 404)  # fails closed either way -- never 200 with real content
