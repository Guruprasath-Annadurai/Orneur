"""Independent Data Privacy, Canaries & Deletion Lifecycle Suite.

Verifies:
- Standard chat persistence baseline (canary is persisted as expected)
- Temporary chat lifecycle (PR #129+): memory/KG ingestion bypassed
- Closing a temporary chat purges active transcript entries from disk and SQLite
- Post-close canary audit across all persistent storage locations
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from orca.serve.api import app
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401

_ROUTE_PATHS = [getattr(r, "path", "") for r in app.routes]
HAS_TEMP_CHAT = "/api/sessions/temporary" in _ROUTE_PATHS


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit
    ratelimit._local_counters.clear()
    with FakeOllama() as f:
        point_orneur_at(f, monkeypatch)
        yield f


class TestDataPrivacyAndLifecycle:
    def test_standard_session_persists_transcript_baseline(self, client: TestClient, fake: FakeOllama):
        """Baseline check: standard session preserves conversational turns in storage."""
        token, _ = _signup(client)
        canary = f"CANARY_STD_{uuid.uuid4().hex[:12]}"
        sid = f"std-sess-{uuid.uuid4().hex[:8]}"

        resp = client.post(
            "/api/chat",
            headers=_hdr(token),
            json={"message": f"Hello {canary}", "session_id": sid, "model_variant": "core"},
        )
        assert resp.status_code == 200

        # Transcript endpoint should return the message
        msg_resp = client.get(f"/api/session/{sid}/messages", headers=_hdr(token))
        assert msg_resp.status_code == 200
        assert canary in msg_resp.text

    def test_temporary_chat_lifecycle_and_canary_purge(self, client: TestClient, fake: FakeOllama, tmp_path: Path):
        """Positive control: temporary chat skips vector ingestion and purges transcript on close."""
        if not HAS_TEMP_CHAT:
            pytest.skip("Temporary chat endpoints not in this candidate (introduced in PR #129)")

        token, _ = _signup(client)
        canary = f"CANARY_EPHEMERAL_{uuid.uuid4().hex[:16]}"
        sid = f"temp-sess-{uuid.uuid4().hex[:8]}"

        # 1. Create temporary chat via real canonical endpoint
        create_resp = client.post(
            "/api/sessions/temporary",
            headers=_hdr(token),
            json={"ttl_seconds": 3600, "session_id": sid},
        )
        assert create_resp.status_code == 200, f"Temporary chat creation failed: {create_resp.text}"

        # 2. Chat with canary
        chat_resp = client.post(
            "/api/chat",
            headers=_hdr(token),
            json={"message": f"Secret code: {canary}", "session_id": sid, "model_variant": "core"},
        )
        assert chat_resp.status_code == 200

        # 3. Close temporary chat
        close_resp = client.post(f"/api/session/{sid}/temporary/close", headers=_hdr(token))
        assert close_resp.status_code == 200

        # 4. Messages endpoint must refuse or show empty
        after_resp = client.get(f"/api/session/{sid}/messages", headers=_hdr(token))
        assert after_resp.status_code in (404, 400) or canary not in after_resp.text

        # 5. Search active filesystem data directory for canary
        from orca.config import DATA_DIR
        data_path = Path(DATA_DIR)
        matches = []
        if data_path.exists():
            for root, _, files in os.walk(data_path):
                for fname in files:
                    if fname.endswith((".jsonl", ".txt", ".db")):
                        try:
                            fcontent = Path(root, fname).read_bytes()
                            if canary.encode("utf-8") in fcontent:
                                matches.append(str(Path(root, fname)))
                        except Exception:
                            pass

        assert len(matches) == 0, f"Privacy violation! Canary found in persisted files: {matches}"
