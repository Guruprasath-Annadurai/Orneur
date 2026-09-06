# Ollama Test Reliability — Root Cause and Fix

## 1. Exact flaky test, from fresh logs

**File:** `tests/test_api_production_cutover.py`
**Function:** `test_free_user_complex_request_is_downgraded_not_elevated`
**Assertion:** `assert resp.status_code == 200`
**Observed:** `assert 500 == 200`
**Server-side log:** `WARNING orca.gateway:gateway.py:275 inference request failed`, `error_class` = a classified `InferenceError` (timeout family — see §4).

A second test in the same file, sharing the identical mechanism, also failed independently during reproduction: `test_aeternum_still_unavailable_through_kernel_authoritative_chat` (same 500, same log line).

A third, unrelated real-Ollama test also failed independently during reproduction on this same machine under the same real load: `tests/test_gateway_compat_brain.py::test_live_gateway_brain_end_to_end_matches_orca_brain_interface` — confirming the instability is environmental, not specific to Phase 3.1's cognitive/entitlement code.

## 2. Reproduction (fresh, this session)

### Individual, 10× sequential (original message, before fix)

`test_free_user_complex_request_is_downgraded_not_elevated` run alone, 10 times in a row:

| run | result | duration |
|---|---|---|
| 1 | **FAIL** | 202s |
| 2 | pass | 72s |
| 3 | pass | 62s |
| 4 | pass | 54s |
| 5 | pass | 70s |
| 6 | **FAIL** | 222s |
| 7 | pass | 68s |
| 8 | pass | 42s |
| 9 | pass | 41s |
| 10 | pass | 123s |

**8/10 passed, 2/10 failed (20% failure rate)**, even with zero other tests running — ruling out cross-test contamination as the primary cause for this specific failure. Durations cluster bimodally: ~40–75s (normal) vs. ~200–225s (failing runs) — both failing runs land just above **180 seconds**, which is exactly `ModelGateway`'s default `TimeoutPolicy.total_request_timeout_s`.

### After the fix (bounded test message, see §5)

Same test plus its sibling, run together, 5 times:

| run | result | duration (both tests) |
|---|---|---|
| 1 | pass | 169s |
| 2 | pass | 71s |
| 3 | pass | 84s |
| 4 | pass | 72s |
| 5 | pass | 150s |

**0/5 failed** (10 individual test executions). Durations still vary (confirming real environmental variance persists) but no run exceeded the failure threshold.

### Grouped / after other live-Ollama tests

Ran together with `tests/test_api_gateway_integration.py` and `tests/test_api_cognitive_kernel_cutover.py` (23 tests total, `test_api_production_cutover.py` running last): **23/23 passed** in two separate runs after the fix, ~10 minutes each.

### Full suite

Post-fix full suite: **726 passed, 0 failed**, ~14 minutes (see `PHASE_3_FINAL_CLOSURE.md` for the exact final run).

## 3. Root cause: RESOURCE SATURATION (measured, not assumed)

This machine (Apple M4, 16GB) is a **shared, actively-used development workstation**, not a dedicated CI runner — confirmed directly during this investigation:

```
$ uptime
load averages: 2.82 4.38 5.24   (10 physical cores — not CPU-saturated by count, but sustained)
$ vm_stat
Pages free: 5874   (× 16KB page size ≈ 94MB free)
```

A completely isolated, single, trivial `/api/stream` call (`"hi"`, fresh process, fresh Gateway, nothing else running) was directly measured taking **80.58 seconds** — proving the latency variance is real and environmental, not an artifact of accumulated test-suite state. Ollama's own `/api/ps` showed both `orca-nano` (5.29GB) and `nomic-embed-text` (370MB) resident simultaneously, on a 16GB machine already under real memory pressure from this Claude Code session, a browser, and other running applications.

### The specific mechanism

`test_free_user_complex_request_is_downgraded_not_elevated`'s message ("Orchestrate this multi-step task: compare and analyze the trade-offs, comprehensive, in depth.") is intentionally classified `DEEP`/`AGENTIC` by the Cognitive Kernel so it defers to the existing `AgentLoop` path (this is the exact behavior the test verifies). `AgentLoop.run()` makes **up to three sequential real Ollama calls** per turn: `_plan()` (fast, small JSON), a **draft** completion, and — if the draft exceeds `REFLECTION_THRESHOLD` (150 words) — a **reflect** completion. A "comprehensive, in depth" instruction reliably produces a draft well over 150 words, triggering the second full generation.

Under this machine's *normal* CPU-only throughput (~7–8 tokens/sec, per the Phase 2 baseline), two such calls comfortably fit under 180s. Under measured real resource contention, per-token throughput degrades, and the **cumulative** time for draft + reflect on this one AgentLoop turn occasionally exceeds `ModelGateway.TimeoutPolicy.total_request_timeout_s` (180s default) on one of the two calls, which `gateway.py`'s `asyncio.wait_for(..., timeout=...)` wrapper turns into a `GenerationTimeoutError` — logged as `InferenceError` at `gateway.py:275`, caught by `orca/serve/api.py`'s existing (pre-Phase-3.1, unchanged) `except Exception as e: return JSONResponse(..., 500)` around the deferred-to-AgentLoop call.

### Classification (per the taxonomy this phase requires)

| Candidate | Verdict | Evidence |
|---|---|---|
| **APPLICATION REGRESSION** | Ruled out | Identical failure mode reproduces on an unrelated, pre-existing test (`test_live_gateway_brain_end_to_end_matches_orca_brain_interface`) untouched by Phase 3/3.1. |
| **RESOURCE SATURATION** | **Confirmed** | Directly measured load average 2.8–5.2, ~94MB free memory, an isolated trivial request taking 80s alone. |
| **COLD-START CONDITION** | **Confirmed as a contributing factor** | `test_live_gateway_brain_end_to_end_matches_orca_brain_interface` constructs a brand-new `ModelGateway`/`OllamaRuntime` each run and requests only 5 tokens — its failure can only be explained by model-load time, not generation time. |
| **RUNTIME TRANSIENT** | Confirmed | Same test passes reliably (8/10, then 5/5 after the fix) — not a deterministic failure. |
| **TEST HARNESS DEFECT** | **Confirmed, and the primary fixable factor** | The test requested an unbounded-length "comprehensive, in-depth" response with no reason to — it only asserts on status code and a boolean field, never on response content or length. This unnecessarily tripled the test's own real Ollama workload (draft + reflect) for no verification benefit. |
| **TIMEOUT CONFIGURATION PROBLEM** | Ruled out as the primary cause | 180s is a reasonable production budget for a CPU-only, single-turn generation; the actual problem was two sequential generations being needed at all when zero were required for what the test verifies. Not blindly increased (see §9 of the phase spec — no evidence supported raising the production default). |

## 4. Cross-test state — investigated and ruled out as a factor in this specific failure

- **Gateway concurrency permits**: `gateway.concurrency.stats(deployment_id)` measured `active=0, queued=0` for 15 seconds immediately after a completed `/api/stream` call in a fresh process — no permit leak observed at the Gateway layer itself.
- **Circuit breaker**: every test file that touches the shared Gateway singleton calls `gateway_wiring.reset_for_tests()` in an autouse fixture, which constructs a fresh `ModelGateway()` (and therefore a fresh `CircuitBreaker()`) — verified by inspection across all 9 live-Ollama test files.
- **Rate limiting / auth DB**: two real, independent test-isolation bugs *were* found and fixed in Phase 3.1's own verification pass (`ratelimit._local_counters` cross-file exhaustion; `orca.auth.db.AUTH_DB` left pointing at a deleted `isolated_home` temp path) — both already fixed in `tests/test_api_production_cutover.py`'s own fixture. Neither produces the specific `gateway.py:275` signature seen here; they were a separate, already-closed class of failure.
- **Orphaned background task (found and fixed this phase, see §5)**: `orca/serve/api.py`'s `/api/stream` handler spawns a fire-and-forget `asyncio.create_task(asyncio.to_thread(sess.knowledge_graph.extract_and_add, ...))` for every stream response — a real Gateway call (`brain.complete()`) that was, until this phase, requested at the **same `INTERACTIVE` priority as foreground user requests**, with no tracking, cancellation, or bounding. This does not explain the specific failure investigated above (which reproduced in complete single-test isolation with no prior `/api/stream` calls), but it is a genuine, separate contributor to aggregate resource contention under sustained full-suite load, and is fixed as a real (if secondary) hardening measure — see §5.

## 5. Fixes applied

1. **Bounded test workload** (primary fix): `test_free_user_complex_request_is_downgraded_not_elevated` and `test_aeternum_still_unavailable_through_kernel_authoritative_chat`'s message now ends with "Answer in one short sentence." — verified (via `orca.cognitive.intent`/`complexity`) to still classify `DEEP`/`AGENTIC` exactly as before (the classifier keys on keywords, not response length), while eliminating the reflection-triggering long draft. This is the change that took the isolated-repro failure rate from 2/10 to 0/5.
2. **Background work no longer contends with foreground requests at equal priority**: `GatewayBrain.complete()`/`.stream()` gained an optional `priority` parameter (default `"INTERACTIVE"`, preserving every existing caller's behavior unchanged); `KnowledgeGraph.extract_and_add()` now defaults to `priority="BACKGROUND"`. Phase 2.1's own aging-based priority scheduler now naturally yields a deployment's bounded concurrency permits to real foreground requests ahead of this fire-and-forget enrichment work, without starving it outright.
3. **Centralized readiness helper** (`tests/ollama_test_support.py`): deduplicates the `_ollama_reachable()`/skip-if-unreachable pattern previously copy-pasted across 9 test files, and adds `warm_model(tier)` — a deliberate, generously-timed (90s) warmup call issued before a test's own timed assertions, so a cold model load is absorbed in a dedicated step rather than charged against whichever test happens to run first.
4. **Bounded, classified retry** (`tests/ollama_test_support.py::retry_transient`): applied to `test_gateway_compat_brain.py`'s real end-to-end test, which calls `GatewayBrain.complete()` directly (a clean exception boundary, unlike the HTTP-layer tests where `orca/serve/api.py` intentionally converts internal errors to a generic 500 before they ever reach the test). Retries **only** on `GenerationTimeoutError`/`QueueTimeoutError` (the two classes actually observed), bounded to 2 attempts total, with backoff and a printed record of every retry — the test still fails if the second attempt also times out.

## 6. Why no retry was added at the HTTP-layer tests

`orca/serve/api.py`'s existing (unchanged, pre-Phase-3.1) exception handling around the deferred-to-AgentLoop call intentionally converts any internal exception to a generic `JSONResponse(..., 500)` — correct production behavior (never leak internal exception types to an API client). This means the HTTP-layer tests in `test_api_production_cutover.py` cannot cleanly distinguish "the Gateway hit a classified transient timeout" from "something else broke" without re-parsing the response body's error string, which would not meet this phase's explicit bar for retries ("classified error types," not string-matching). The bounded-workload fix (§5.1) removes the actual cause of excess real generation time at this layer instead, which is the more direct, honest fix — a retry-around-a-500 was deliberately not added here.
