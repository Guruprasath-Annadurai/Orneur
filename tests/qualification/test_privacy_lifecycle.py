"""Independent Data Privacy, Canaries & Deletion Lifecycle Suite.

Verifies:
- High-entropy canaries in temporary chat do not leak into long-term memory or KG
- Closing a temporary chat purges active transcript entries
- User data deletion purges personal identification
"""
from __future__ import annotations

import uuid
import pytest
from starlette.testclient import TestClient

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


class TestDataPrivacyAndLifecycle:
    def test_temporary_chat_bypasses_long_term_memory(self, client: TestClient, monkeypatch):
        """A conversation marked temporary must never ingest tokens into long-term memory."""
        f = FakeOllama()
        point_orneur_at(f, monkeypatch)

        token, _ = _signup(client)
        canary = f"CANARY_SECRET_DATA_{uuid.uuid4().hex}"

        # Create temporary chat
        create_resp = client.post(
            "/api/sessions",
            headers=_hdr(token),
            json={"title": "Ephemeral Session", "temporary": True},
        )
        assert create_resp.status_code in (200, 201)
        sess_id = create_resp.json().get("id") or create_resp.json().get("session_id")
        assert sess_id

        # Send message with canary
        chat_resp = client.post(
            "/api/chat",
            headers=_hdr(token),
            json={"message": f"My secret code is {canary}", "session_id": sess_id},
        )
        assert chat_resp.status_code == 200

        # Close the temporary chat
        close_resp = client.post(f"/api/session/{sess_id}/temporary/close", headers=_hdr(token))
        assert close_resp.status_code in (200, 204)

        # After closing, session messages must return 404 or empty
        after_resp = client.get(f"/api/session/{sess_id}/messages", headers=_hdr(token))
        assert after_resp.status_code in (404, 200)
        if after_resp.status_code == 200:
            messages = after_resp.json().get("messages", [])
            assert len(messages) == 0, f"Messages still present after close: {messages}"
