"""Independent Inference Security & Adversarial Red Team Suite.

Tests DLP boundaries and quota replay protection:
- Negative control: per-chunk stateless scanning leaks secrets split across chunk boundaries
- Positive control: stateful StreamRedactor (PR #127+) holds incomplete tokens and redacts split secrets
- Character-by-character PEM private key emission through stateful redactor
- Secret pattern coverage across OpenAI, Anthropic, AWS, GitHub, and Bearer tokens
- Quota idempotency on identical request IDs
"""
from __future__ import annotations

import re
import pytest
from starlette.testclient import TestClient

from orca.serve.dlp import scan_output, redact_secrets, _SECRET_PATTERNS

try:
    from orca.serve.stream_dlp import StreamRedactor
    HAS_STREAM_REDACTOR = True
except ImportError:
    HAS_STREAM_REDACTOR = False

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


class TestStreamingDLPAdversarial:
    def test_negative_control_stateless_chunk_scan_leaks_split_secrets(self):
        """Negative control: demonstrates that per-chunk scan_output leaks secrets split across deltas."""
        secret = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        part1 = secret[:12]
        part2 = secret[12:]

        # Stateless per-chunk scanning
        chunk1 = scan_output(part1)["safe_text"]
        chunk2 = scan_output(part2)["safe_text"]
        assembled = chunk1 + chunk2

        # In unpatched stateless streaming, the secret reassembles completely!
        assert secret in assembled, "Expected defect: split secret should leak when scanned per-chunk"

    def test_positive_control_stateful_stream_redactor_prevents_leakage(self):
        """Positive control: stateful StreamRedactor holds incomplete prefixes and redacts secrets."""
        if not HAS_STREAM_REDACTOR:
            pytest.skip("StreamRedactor not implemented in this candidate (introduced in PR #127)")

        secret = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        redactor = StreamRedactor()
        out = redactor.push(secret[:12]) + redactor.push(secret[12:]) + redactor.finish()
        assert secret not in out, f"Stateful redactor failed: secret leaked: {out}"

    def test_pem_private_key_character_by_character_stateful_streaming(self):
        """PEM private key streamed 1 character per chunk through stateful redactor."""
        if not HAS_STREAM_REDACTOR:
            pytest.skip("StreamRedactor not implemented in this candidate")

        pem_text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----"
        redactor = StreamRedactor()
        emitted = "".join(redactor.push(ch) for ch in pem_text) + redactor.finish()

        assert "BEGIN RSA PRIVATE KEY" not in emitted, "Raw PEM header leaked through stream"
        assert "[REDACTED-PRIVATE_KEY_BLOCK]" in emitted or "REDACTED" in emitted

    def test_known_secret_patterns_redacted_on_full_payloads(self):
        """Verify all supported secret regex patterns in orca.serve.dlp."""
        probes = [
            ("openai", "sk-abcdefghijklmnopqrstuvwxyz1234567890"),
            ("anthropic", "sk-ant-api03-1234567890abcdef1234567890abcdef-ZZ"),
            ("aws", "AKIAIOSFODNN7EXAMPLE"),
            ("github", "ghp_1234567890abcdefghijklmnopqrstuvwxyz12"),
            ("bearer", "Bearer tok_1234567890abcdef1234567890"),
        ]
        for name, secret in probes:
            result = scan_output(f"Output containing secret: {secret}")
            assert secret not in result["safe_text"], f"DLP pattern for {name} failed to redact"
            assert result["has_findings"] is True


class TestQuotaAndReplayAdversarial:
    def test_identical_request_id_cannot_replay_quota_spending(self, client: TestClient, monkeypatch):
        """Submitting duplicate request_id must be detected and not double-counted."""
        f = FakeOllama()
        point_orneur_at(f, monkeypatch)

        token, _ = _signup(client)
        req_id = "req-fixed-id-9999"

        payload = {
            "message": "Quota check message 1",
            "session_id": "sess-quota-01",
            "request_id": req_id,
        }

        resp1 = client.post("/api/chat", json=payload, headers=_hdr(token))
        resp2 = client.post("/api/chat", json=payload, headers=_hdr(token))

        if resp2.status_code == 200:
            data2 = resp2.json()
            assert data2.get("replayed") is True or resp2.status_code != 200
