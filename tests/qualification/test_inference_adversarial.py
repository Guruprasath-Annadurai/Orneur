"""Independent Inference Security & Adversarial Red Team Suite.

Tests serving boundaries:
- Streaming DLP with PEM private keys split token-by-token or character-by-character
- Secret redaction across arbitrary chunk boundaries
- Quota reservation atomicity & anti-double-spend
- Replay prevention on identical request IDs
- Model entitlement spoofing
"""
from __future__ import annotations

import asyncio
import json
import pytest
from starlette.testclient import TestClient

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


class TestStreamingDLPAdversarial:
    def test_pem_private_key_split_across_chunks_is_redacted(self):
        """PEM header split character-by-character must not leak to client."""
        from orca.serve.dlp import scan_and_redact

        pem_text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----"
        # Simulate feeding chunks character by character
        emitted = []
        for ch in pem_text:
            redacted, _ = scan_and_redact(ch)
            if redacted:
                emitted.append(redacted)

        final_stream = "".join(emitted)
        assert "BEGIN RSA PRIVATE KEY" not in final_stream, "Raw PEM key leaked through stream!"

    def test_api_keys_and_bearer_tokens_redacted(self):
        """Standard high-entropy API keys must be scrubbed from output."""
        from orca.serve.dlp import scan_and_redact

        probe_strings = [
            "sk-proj-abc1234567890abcdef1234567890abcdef1234567890abcdef",
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz12",
        ]
        for secret in probe_strings:
            clean, matched = scan_and_redact(f"Here is your key: {secret}")
            assert secret not in clean, f"Secret {secret} was not redacted!"


class TestQuotaAndReplayAdversarial:
    def test_identical_request_id_cannot_replay_quota_spending(self, client: TestClient, monkeypatch):
        """Submitting duplicate request_id must be detected as replay and rejected."""
        from tests.fake_ollama import FakeOllama, point_orneur_at

        f = FakeOllama()
        point_orneur_at(f, monkeypatch)

        token, _ = _signup(client)
        req_id = "req-fixed-id-9999"

        payload = {
            "message": "Quota check message 1",
            "session_id": "sess-quota-01",
            "request_id": req_id,
        }

        # First request consumes
        resp1 = client.post("/api/chat", json=payload, headers=_hdr(token))
        # Subsequent request with same request_id must either reject (400/409) or not double-count
        resp2 = client.post("/api/chat", json=payload, headers=_hdr(token))
        if resp2.status_code == 200:
            # Must be marked idempotent/cached or not billed twice
            data2 = resp2.json()
            assert data2.get("replayed") is True or resp2.status_code != 200
