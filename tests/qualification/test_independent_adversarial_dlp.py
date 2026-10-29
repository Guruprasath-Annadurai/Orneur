from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest


def _resolve_candidate_dir() -> Path:
    """Resolve candidate worktree path portably without hardcoded workstation paths."""
    # 1. Explicit environment variable set by qualification runner or CI
    env_path = os.environ.get("ORNEUR_CANDIDATE_PATH")
    if env_path:
        cand = Path(env_path).resolve()
        if cand.exists() and (cand / "orca").exists():
            return cand

    # 2. Sibling directory discovery relative to harness repository
    here = Path(__file__).resolve()
    repo_root = here.parents[2]  # Orneur root
    for candidate_name in ["Orneur-b01", "candidate", "Orneur-candidate"]:
        cand = repo_root.parent / candidate_name
        if cand.exists() and (cand / "orca" / "serve" / "stream_dlp.py").exists():
            return cand
        cand_sub = repo_root / candidate_name
        if cand_sub.exists() and (cand_sub / "orca" / "serve" / "stream_dlp.py").exists():
            return cand_sub

    # 3. Current repository if candidate features are present
    if (repo_root / "orca" / "serve" / "stream_dlp.py").exists():
        return repo_root

    raise RuntimeError(
        "Candidate worktree with orca.serve.stream_dlp not found. "
        "Set ORNEUR_CANDIDATE_PATH or execute via scripts/qualification/run_b01_qualification.py"
    )


_candidate_dir = _resolve_candidate_dir()
if str(_candidate_dir) not in sys.path:
    sys.path.insert(0, str(_candidate_dir))

# Explicit module loading to eliminate sys.modules namespace collisions between candidate and harness
_stream_dlp_path = _candidate_dir / 'orca' / 'serve' / 'stream_dlp.py'
_dlp_path = _candidate_dir / 'orca' / 'serve' / 'dlp.py'

_spec_dlp = importlib.util.spec_from_file_location('orca.serve.dlp', str(_dlp_path))
_mod_dlp = importlib.util.module_from_spec(_spec_dlp)
sys.modules['orca.serve.dlp'] = _mod_dlp
_spec_dlp.loader.exec_module(_mod_dlp)

_spec_sdlp = importlib.util.spec_from_file_location('orca.serve.stream_dlp', str(_stream_dlp_path))
_mod_sdlp = importlib.util.module_from_spec(_spec_sdlp)
sys.modules['orca.serve.stream_dlp'] = _mod_sdlp
_spec_sdlp.loader.exec_module(_mod_sdlp)

MAX_DELTA_CHARS = _mod_sdlp.MAX_DELTA_CHARS
MAX_HOLD_CHARS = _mod_sdlp.MAX_HOLD_CHARS
MAX_PEM_CHARS = _mod_sdlp.MAX_PEM_CHARS
StreamRedactor = _mod_sdlp.StreamRedactor
scan_output = _mod_dlp.scan_output
redact_secrets = _mod_dlp.redact_secrets
from tests.fake_ollama import FakeOllama

# Direct file import to prevent sys.modules['tests'] namespace collision between harness and candidate
_harness_file = _candidate_dir / "tests" / "journey" / "harness.py"
if not _harness_file.exists():
    raise RuntimeError(f"Candidate harness not found at {_harness_file}")

_spec = importlib.util.spec_from_file_location("b01_harness", str(_harness_file))
_harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)
JOURNEY_MODEL = _harness.JOURNEY_MODEL
LiveServer = _harness.LiveServer
User = _harness.User


# Fresh adversarial canaries strictly satisfying detection regex specifications
CANARIES = {
    "openai": "sk-AntigravityCanaryToken9876543210abcdefXYZ",
    "github": "ghp_AntigravityPatCanary9876543210ZYXWV",
    "aws": "AKIA1234567890ABCDEF",
    "bearer_jwt": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.antigravity_canary_payload.sig12345",
    "ec_pem": "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIANTIGRAVITYCANARYKEYDATA1234567890abcdef\n-----END EC PRIVATE KEY-----",
    "openssh_pem": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB\n-----END OPENSSH PRIVATE KEY-----",
    "rsa_pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAantigravitycanaryrsa9876543210\n-----END RSA PRIVATE KEY-----",
}


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


class TestIndependentAdversarialDLP:
    """Rigorous differential and adversarial boundary tests on StreamRedactor."""

    @pytest.mark.parametrize("canary_name", list(CANARIES.keys()))
    @pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 7, 11, 16, 23])
    def test_adversarial_chunk_splits_equal_one_shot(self, canary_name: str, chunk_size: int):
        """Every chunk split size from 1 to 23 chars must produce zero leakage and match one-shot redaction."""
        secret = CANARIES[canary_name]
        surrounding_text = f"Here is the credential for testing: {secret}. Please keep it safe!"
        one_shot_expected = scan_output(surrounding_text)["safe_text"]

        assert secret not in one_shot_expected, f"Canary {canary_name} not detected by base scan_output"

        redactor = StreamRedactor()
        chunks = _split_into_chunks(surrounding_text, chunk_size)
        streamed_pieces = []
        for ch in chunks:
            emitted = redactor.push(ch)
            if emitted:
                assert secret not in emitted
                streamed_pieces.append(emitted)

        tail = redactor.finish()
        if tail:
            assert secret not in tail
            streamed_pieces.append(tail)

        reassembled = "".join(streamed_pieces)
        assert secret not in reassembled, f"Canary {canary_name} leaked in reassembled stream with chunk size {chunk_size}!"
        assert redactor.safe_text() == reassembled
        assert reassembled == one_shot_expected, f"Reassembled stream does not equal one-shot scan for {canary_name} at size {chunk_size}"

    @pytest.mark.parametrize("wrapper", [
        ('{"token": "', '"}'),
        ("`", "`"),
        ("```\n", "\n```"),
        ("prefix: ", " suffix"),
        ("Key = ", "\n"),
        ("[SECRET](", ")"),
        ("<span>", "</span>"),
    ])
    def test_glued_punctuation_and_wrappers_never_leak(self, wrapper: tuple[str, str]):
        """Glued delimiters and syntax markers must not inhibit prefix detection."""
        prefix, suffix = wrapper
        for name, secret in CANARIES.items():
            full = f"{prefix}{secret}{suffix}"
            for chunk_size in [1, 2, 4, 9]:
                redactor = StreamRedactor()
                chunks = _split_into_chunks(full, chunk_size)
                streamed = "".join([redactor.push(c) for c in chunks] + [redactor.finish()])
                assert secret not in streamed, f"Secret {name} leaked when enclosed in {wrapper} at chunk size {chunk_size}"

    def test_single_delta_overflow_fails_closed(self):
        """Single delta exceeding MAX_DELTA_CHARS fails closed immediately."""
        redactor = StreamRedactor()
        huge_delta = "X" * (MAX_DELTA_CHARS + 1)
        emitted = redactor.push(huge_delta)
        assert emitted == "[REDACTED-OVERFLOW]"
        assert redactor.safe_text() == "[REDACTED-OVERFLOW]"

    def test_pem_body_overflow_fails_closed(self):
        """Unterminated PEM body exceeding MAX_PEM_CHARS fails closed."""
        redactor = StreamRedactor()
        header = "-----BEGIN RSA PRIVATE KEY-----\n"
        huge_body = "A" * (MAX_PEM_CHARS + 10)
        emitted1 = redactor.push(header)
        assert emitted1 == ""  # Held in pem_body phase
        emitted2 = redactor.push(huge_body)
        assert "[REDACTED-OVERFLOW]" in emitted2 or redactor.safe_text() == "[REDACTED-OVERFLOW]"

    def test_cancel_discards_held_prefix_safely(self):
        """Cancelling a stream in mid-flight drops any held prefix without flushing."""
        secret = CANARIES["openai"]
        part1 = secret[:10]  # "sk-Antigra"
        redactor = StreamRedactor()
        emitted = redactor.push(part1)
        assert emitted == ""  # Held
        redactor.cancel()
        assert redactor.finish() == ""
        assert secret not in redactor.safe_text()


class TestEndToEndSSEAndMemoryContamination:
    """Verifies that wire SSE, SQLite DB, and memory ingestion are all cleanly redacted using live server."""

    def test_live_server_sse_and_db_and_next_turn_context(self, tmp_path):
        """Send freshly minted canaries through live orca serve; verify wire SSE, SQLite, and subsequent prompt."""
        secret = CANARIES["openai"]
        full_reply = f"System access granted with key {secret} for deployment."
        # Split into 3-char chunks
        chunks = _split_into_chunks(full_reply, 3)

        fake = FakeOllama(models=(JOURNEY_MODEL,), chunks=chunks, reply=full_reply)
        fake.__enter__()
        home = tmp_path / "adversarial-home"
        home.mkdir(parents=True, exist_ok=True)
        srv = LiveServer(home, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
        try:
            srv.wait_ready()
            user = User(srv.base, "adversarial_dlp")

            # 1. First turn: send stream request
            sid = str(uuid.uuid4())
            events = []
            headers = {"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}
            body = {"message": "Please show me the key", "session_id": sid, "model_variant": "core"}
            with user.http.stream("POST", "/api/stream", json=body, headers=headers) as resp:
                assert resp.status_code == 200
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        events.append(data)

            # Check wire chunks
            chunk_texts = [e["text"] for e in events if e.get("type") == "chunk"]
            wire_text = "".join(chunk_texts)
            for ch in chunk_texts:
                assert secret not in ch, "Raw secret leaked in wire SSE chunk!"
            assert secret not in wire_text, "Raw secret reassembled from wire chunks!"
            assert "[REDACTED" in wire_text

            # 2. Check all files on disk under home (SQLite DB, logs, JSONL)
            for path in home.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    assert secret.encode() not in data, f"Raw secret persisted in file {path.name}!"

            # 3. Second turn: prompt referring to prior turn
            fake.chunks = ["Acknowledged."]
            fake.reply = "Acknowledged."
            n_before = len(fake.requests)
            headers2 = {"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}
            body2 = {"message": "What key was shown?", "session_id": sid, "model_variant": "core"}
            with user.http.stream("POST", "/api/stream", json=body2, headers=headers2) as resp:
                assert resp.status_code == 200
                list(resp.iter_lines())

            time.sleep(0.5)
            # Inspect every outbound request sent to fake model after second turn
            for req in fake.requests[n_before:]:
                req_dump = json.dumps(req)
                assert secret not in req_dump, "Raw secret leaked back into model prompt context!"

        finally:
            srv.stop()
            fake.__exit__(None, None, None)
