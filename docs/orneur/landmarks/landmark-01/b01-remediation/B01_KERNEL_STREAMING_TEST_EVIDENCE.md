# B-01 — Kernel Streaming Test Evidence

**SHA under test (at evidence write):** see branch tip / `B01_EXACT_HEAD_CI_REPORT.md` after push.  
**Base:** `8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`

## Primary suite

```bash
.venv/bin/pytest -q tests/test_kernel_streaming.py --tb=short
```

| Result | Count | Notes |
|---|---|---|
| passed | 8 | Delayed fake runtime — proves real time-separated deltas |
| skipped | 1 | `test_live_ollama_streaming_when_available` — no Ollama on this agent VM |

### What the delayed-provider tests prove

1. Non-streaming path still calls `generate()` once (no stream).
2. Streaming path calls `stream()` once, never `generate()`.
3. Multiple deltas arrive **before** `execute()` completes (no pre-generation).
4. Measurable inter-delta wall time with `delay_s=0.04`.
5. Accumulated output equals `"".join(provider_chunks)`.
6. Resolved model identity retains `fixture-llama3.2:1b` (colon tag preserved).
7. Cancelled consumer → `CancelledError`, `_active_streams == 0`, stream aclose observed.
8. Mid-stream provider failure → `CognitiveExecutionFailedError` (not false COMPLETED).
9. Bounded `RawDeltaChannel(maxsize=1)` delivers all deltas (no silent discard).
10. Conversation context messages identical for generate vs stream.

### Live Ollama

**Unverified in this environment** (no daemon on `:11434`). Command for Antigravity / workstation:

```bash
ollama pull llama3.2:1b
.venv/bin/pytest -q tests/test_kernel_streaming.py::test_live_ollama_streaming_when_available -rs
```

Do not treat the delayed fixture as a live-model benchmark.

## Supporting regressions (same workspace tip)

```bash
.venv/bin/pytest -q \
  tests/test_kernel_streaming.py \
  tests/test_cognitive_kernel.py \
  tests/test_conversation_context.py \
  tests/test_gateway_model_gateway.py \
  tests/test_gateway_stream_contract.py \
  tests/test_canonical_route_dlp.py \
  tests/test_kernel_working_memory.py \
  tests/test_kernel_memory_recall_integration.py \
  tests/test_kernel_replanning.py \
  tests/test_fast_path_no_society_overhead.py
# → 71 passed, 9 skipped
```

```bash
.venv/bin/pytest -q \
  tests/test_a_serving_authorization.py \
  tests/test_b_logout_revocation.py \
  tests/test_session_ownership_isolation.py \
  tests/test_p0_reservation_ownership.py \
  tests/test_p0_stream_dlp_closure.py \
  tests/test_p0_transcript_integrity.py
# → 47 passed, 2 skipped (skips = needs real Redis)
```

Mandatory full deterministic suite + exact-head CI: recorded in `B01_EXACT_HEAD_CI_REPORT.md` after push.
