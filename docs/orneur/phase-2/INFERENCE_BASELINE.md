# Inference Performance Baseline (Phase 2)

Measured through the new `OllamaRuntime` adapter itself (`scripts/measure_inference_baseline.py`) — dogfooding the Phase 2 code, not a separate ad-hoc benchmark. Raw output: `docs/orneur/phase-2/inference_baseline_raw.json`.

## Hardware (honest — this is a shared laptop, not a dedicated inference host)

| | |
|---|---|
| CPU | Apple M4 |
| Memory | 16 GB |
| Architecture | arm64 |
| OS | macOS 26.6.2 |
| Note | Other processes (this Claude Code session itself, background apps) were competing for CPU/memory during this measurement — these numbers are NOT representative of a dedicated inference server, only of this specific dev machine's current real-world capacity. |

## Model measured

`orca-nano-v7` (currently the fastest available checkpoint on this machine per this session's own prior measurements — Qwen2.5-7B-class, Q4_K_M quantization).

## Generation latency vs. output length

| max_tokens | completion_tokens | total latency | tokens/sec |
|---|---|---|---|
| 5 | 5 | 694ms | 7.2 |
| 20 | 20 | 2,706ms | 7.39 |
| 50 (capped early) | 32 | 4,023ms | 7.95 |

Consistent ~7.2–8.0 tokens/sec across all three runs — CPU-bound generation, no GPU acceleration on this machine. This matches the ~7–8.8 t/s this session already observed independently during Phase 0.5/1 evaluation work (via raw Ollama server logs), now confirmed through the new gateway code path itself.

## Time-to-first-token (streaming)

**729.6ms** TTFT, 4,610ms total for a 30-chunk stream. TTFT is dominated by the same per-token generation cost above (there's no separate "prefill vs. decode" distinction visible at this measurement layer) plus prompt processing for the 92-token system+user prompt.

## Concurrency behavior (2 simultaneous requests)

2/2 succeeded, wall time 1.38s, individual latencies 1.38s and 0.97s — the second request's actual generation overlapped with the first rather than queueing sequentially end-to-end, consistent with Ollama's own internal request handling rather than any batching Orneur's gateway performs (the gateway's own concurrency limiter was configured generously enough in this test not to queue either request).

## What this does NOT show

- **No GPU numbers** — this machine has no discrete GPU Ollama is using; all generation above is CPU/unified-memory (Apple Silicon). A real production deployment on GPU hardware (the actual target this Phase 2 architecture is built for) would show materially different numbers — these are a CPU-only development-machine baseline, not a production SLA reference.
- **No sustained-load numbers** — this baseline is a handful of individual requests, not a sustained throughput test under queue pressure. `tests/test_gateway_concurrency.py` and `tests/test_gateway_chaos.py` verify correctness under load (queue limits, backpressure, permit release) but do not report steady-state throughput figures.
- **No comparison across models** — only `orca-nano-v7` was measured; `orca-core-combined-v2` (Llama-3.1-8B) would be slower per-token on this same hardware based on its larger parameter count, but was not separately benchmarked here to keep this measurement pass short.

## Honest takeaway

The current single-host, CPU-only Ollama deployment produces single-digit tokens/sec — real, workable for low-traffic personal/small-team use, and exactly the gap Phase 2's Model Gateway architecture is designed to eventually let a GPU-backed runtime (vLLM/SGLang/TensorRT-LLM) close without requiring cognitive/application code to change, since it already only depends on the `InferenceRuntime` protocol, not Ollama specifically.

---

## Phase 2.1: Integrated path (real API + Gateway), measured post-cutover

The numbers above measured `OllamaRuntime` directly, in isolation. Phase 2.1's cutover means real user traffic now takes a much longer path: `POST /api/stream` → auth/ratelimit/quota/moderation → `_Session`/`AgentLoop`/`ContextManager` → `GatewayBrain` → `ModelGateway.stream()` (circuit breaker + worker/priority-aware concurrency acquire) → `OllamaRuntime`. `scripts/measure_integrated_baseline.py` measures this actual path end-to-end through a real FastAPI `TestClient`, against the same local `orca-nano-v7` model. Raw output: `docs/orneur/phase-2/integrated_baseline_raw.json`.

### Client-observed (full HTTP round trip, 3 runs)

| run | ttft_ms | total_ms |
|---|---|---|
| 1 | 6,404 | 6,404 |
| 2 | 5,039 | 5,039 |
| 3 | 4,843 | 4,843 |

**Caveat:** each run reported `chunk_count: 1` — `TestClient.stream()` does not appear to expose true incremental SSE arrival in-process the way a real network client would, so `ttft_ms` here is effectively "time to full response," not true time-to-first-byte. This is a test-harness limitation, not evidence the Gateway buffers responses (see `Gateway-observed` below, which is measured from inside the actual streaming call and does show real incremental TTFT).

### Gateway-observed (`metrics.get_snapshot()`, from inside the actual `generate`/`stream` calls)

| | |
|---|---|
| requests | 9 |
| successes | 9 |
| avg TTFT | 740.9ms |
| avg total latency | 1,540.0ms |
| avg queue latency | 0.02ms |

**9 requests for 3 user-facing turns is expected, not a bug or Gateway-introduced amplification**: `AgentLoop` (`orca/brain/agent.py`) calls `self.brain.complete()`/`.stream()` from multiple internal call sites (draft, refine/critique, context-policy summarization) per turn — unchanged, pre-existing behavior this phase did not touch. Each of those calls independently goes through the Gateway now, which is exactly the intended effect of the cutover (previously only some of these calls could have been observed by anything resembling a gateway; now all of them are).

### Reading the two numbers together

The Gateway's own instrumented **avg TTFT of 740.9ms** is within noise of Phase 2's raw-runtime baseline (**729.6ms**) — meaning the Gateway itself (deployment resolution, circuit breaker check, concurrency acquire — avg queue latency measured at **0.02ms**, i.e. no contention in this single-client test) adds no measurable per-call overhead. The multi-second client-observed wall time is real, but it is the cost of **AgentLoop's multi-call-per-turn design plus session/context/memory work surrounding the Gateway**, not Gateway overhead — the per-call Gateway numbers make that attribution possible where a black-box HTTP measurement alone could not.

### Novus benchmark: not attempted, and why

Benchmarking `orneur-novus` through this same integrated path was considered and explicitly not done this pass: `docs/orneur/phase-2/LIVE_SERVING_CUTOVER.md`'s policy-decision section already establishes that live traffic registers deployments as `EXPERIMENTAL` lifecycle, and the wiring bridge in `orca/gateway/wiring.py` only maps configured tiers (`nano`/`core`/`ultra`) to installed Ollama models — Novus has no tier mapping and no installed checkpoint on this machine, so there is no real, non-fabricated request to measure. Benchmarking it would require either a synthetic/mocked runtime (which Phase 2's own baseline explicitly rejected as dishonest) or a real Novus checkpoint, which does not exist in this environment. This is disclosed rather than silently skipped.
