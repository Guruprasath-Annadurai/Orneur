# Phase 2.1 Closure — Model Gateway Cutover, Worker Routing, Priority Scheduling

## Scope reminder

This pass closed exactly three Phase 2 gaps, narrowly: (1) cut the real chat/generation serving path over to `ModelGateway`, (2) make routing worker-aware, (3) activate bounded-fairness priority scheduling. Explicitly out of scope and untouched: Gateway redesign, model training, Cognitive Kernel work, RAG/Memory/Agent system redesign.

## Direct-Ollama call-site audit (repo-wide, post-cutover)

Every direct reference to Ollama's HTTP surface (`/api/generate`, `/api/chat`, `/api/tags`, `CONFIG.ollama.host`, `11434`) or to the legacy `OrcaBrain`/`Backend` classes, classified:

| Site | Classification | Notes |
|---|---|---|
| `orca/serve/api.py` `_Session.__init__` → `brain_for_tier_resolution()` | **RUNTIME_ADAPTER (via Gateway)** | `/api/chat`, `/api/stream` main path. Cut over in the original pass. |
| `orca/serve/api.py` `/api/ultra` → `OrcaUltra(..., brain=ultra_brain)` | **RUNTIME_ADAPTER (via Gateway)** | **Found as a bypass by this audit, fixed this pass** — see below. |
| `orca/serve/api.py` `/api/status` → `get_brain(CONFIG.ollama.model_core)` | **CLI_ADMIN / diagnostic** | Only calls `.is_available()`/`.name` for a health display field — never `.complete()`/`.stream()`. Not a generation path. |
| `orca/gateway/frontier_runtime.py` → `build_backend` (`orca/brain/backends.py`) | **RUNTIME_ADAPTER** | This IS the Gateway's own frontier adapter — legitimate, internal to the Gateway. |
| `orca/brain/providers.py` (`OrcaBrain`, `get_brain`) | **LEGACY_COMPATIBILITY** | The interface `GatewayBrain` mimics. Still the real implementation for CLI callers below. |
| `orca/cli.py`, `orca/tui.py`, `orca/doctor.py` | **CLI_ADMIN** | Local, single-user, out of Gateway scope (unchanged classification from Phase 2). |
| `orca/variants/nano.py`, `core.py`, `ultra.py` (`get_brain()` in `__init__`) | **CLI_ADMIN** | Only ever constructed from `orca/cli.py`; not reachable from any live HTTP endpoint (confirmed by import audit — `orca/serve/api.py` only imports `OrcaUltra`, and that call site now injects a Gateway brain, see above). |
| `orca/brain/reasoning.py` (`ReasoningEngine`) | **LEGACY_COMPATIBILITY (dead code)** | `get_brain()` in `__init__`, but zero callers found repo-wide (`grep -rln "ReasoningEngine("` returns nothing). No live risk; not fixed since nothing invokes it. |
| `orca/brain/agent.py`, `knowledge_graph.py`, `context_intelligence.py` | **N/A — not call sites** | Only import `OrcaBrain` for type hints; they accept `brain` as a constructor/function parameter (the same injection point used for the Gateway cutover), never call `get_brain()` themselves. |
| `orca/serve/registry.py` (`resolve_tier_model`/`resolve_tier_backend` → `/api/tags`) | **RUNTIME_ADAPTER (registry lookup)** | Pre-existing, unchanged tier-resolution router — queries installed models, never generates. Explicitly preserved per this phase's own constraints. |
| `orca/serve/account_delete.py`, `_Session.__init__`'s `DocStore(...)` | **RAG_EMBEDDING** | Embeddings, out of scope (`WITHOUT redesigning RAG/Memory`). |
| `orca/docs/reranker.py`, `query_engine.py`, `hallucination_check.py`, `sufficiency.py` | **RAG_EMBEDDING** | RAG support calls, out of scope, unchanged from Phase 2. |
| `orca/train/*.py` (dpo_pairs, novus_eval, persona_eval, redteam, aeternum_eval, distill, genesis_eval, eval, blind_ab) | **TRAINING** | Explicitly out of scope (`DO NOT train models`), unchanged from Phase 2. |
| `orca/brain/vision.py` | **N/A — not a call site** | Docstring reference to `/api/chat`'s `images` field only; no HTTP call. |
| `orca/serve/ratelimit.py` | **N/A — not a call site** | Docstring/comment reference to `/api/chat` only; no HTTP call. |

**`UNEXPECTED_APPLICATION_BYPASS` count: 1 found, 1 fixed, 0 remaining.**

The one bypass: `/api/ultra` (a live, Pro-license-gated multi-agent SSE endpoint) built its own `OrcaBrain` via `get_brain()` inside `OrcaUltra.__init__`, missed by the original cutover pass which focused on `/api/chat`/`/api/stream`. Fixed by giving `OrcaUltra` an optional injected `brain` parameter and having `/api/ultra`'s handler resolve one via `brain_for_tier_resolution()`, exactly like `_Session.__init__` does. CLI usage of `OrcaUltra` (`orca ultra`) is unaffected. Verified with a real end-to-end test against local Ollama (`tests/test_api_ultra_gateway_cutover.py`) proving the request now emits real Gateway metrics. Full detail: `LIVE_SERVING_CUTOVER.md`.

## Two additional bugs found during closure verification (both fixed)

Verifying the closure checklist's cancellation and timeout requirements surfaced two real correctness bugs in this phase's **own new code** (not carried over from Phase 2, and fixing them is not "redesigning the Gateway" — it's finishing this phase's own plumbing):

1. **Cancellation not propagated on client disconnect** (`orca/gateway/sync_bridge.py`): closing the sync generator early (exactly what a client disconnect on `/api/stream` triggers) blocked the calling thread until the abandoned generation finished on its own — reproduced directly, a 30-second abandoned generation blocked `close()` for the full 30 seconds. Fixed by running the drain as a cancellable `asyncio.Task`, cancelled via `loop.call_soon_threadsafe` on close — now returns in ~0ms and the abandoned generator's cleanup genuinely runs. See `LIVE_SERVING_CUTOVER.md` and `tests/test_gateway_sync_bridge.py::test_run_async_gen_in_thread_cancels_promptly_on_early_close`.
2. **Concurrency state loss on re-registration** (`orca/gateway/concurrency.py`): `configure()` unconditionally replaced the `_DeploymentLimiter` object, and `register_deployment()` calls `configure()` on every request (deliberate idempotent registration) — under real concurrent traffic this could silently discard another in-flight request's `_active` count and orphan its `_waiters`. Fixed by updating limits in place instead of replacing the object. See `PRIORITY_SCHEDULING.md` and `tests/test_gateway_concurrency.py::test_reconfigure_while_a_permit_is_held_does_not_lose_it`.

## Checklist verification

| Item | Status |
|---|---|
| Real chat/generation serving path routes through `ModelGateway` | ✅ `/api/chat`, `/api/stream`, `/api/ultra` (`LIVE_SERVING_CUTOVER.md`) |
| Worker health/capacity consulted by routing | ✅ `WORKER_ROUTING.md`, `tests/test_gateway_worker_routing.py` (11 tests) |
| Bounded request-priority scheduling active | ✅ `PRIORITY_SCHEDULING.md`, `tests/test_gateway_priority_scheduling.py` (4 tests) |
| Existing behavior preserved (auth/ratelimit/conversation/RAG/memory/agent/SSE/model-selection) | ✅ All pre-existing tests pass unchanged; one exact-dict-equality assertion updated for the additive `/healthz` field only |
| Novus never accidentally becomes "production" through the cutover | ✅ Deployments register as `EXPERIMENTAL`, not `PRODUCTION` — `tests/test_gateway_wiring.py::test_deployment_is_registered_as_experimental_not_production` |
| Aeternum still gets `MODEL_NOT_ROUTABLE`, never falls back to Novus | ✅ At the Gateway/wiring level (Phase 2 + this phase's tests); disclosed that the pre-existing `ultra→core→nano` step-down router resolves away from "ultra" before the Gateway sees it, so this isn't observable through a live `/api/chat` request today — see `LIVE_SERVING_CUTOVER.md` |
| Legacy Genesis-7B vs. canonical future Genesis-3B distinction preserved | ✅ `tests/test_gateway_wiring.py::test_legacy_genesis_7b_cannot_silently_become_canonical_future_3b` |
| Worker routing excludes UNHEALTHY/OFFLINE/DRAINING/stale-heartbeat | ✅ `tests/test_gateway_worker_routing.py` |
| Priority scheduling has starvation prevention (bounded fairness) | ✅ `tests/test_gateway_priority_scheduling.py::test_aging_prevents_indefinite_starvation` |
| Priority never defeats bounded backpressure | ✅ `tests/test_gateway_priority_scheduling.py::test_priority_does_not_bypass_bounded_queue_depth` |
| Direct-Ollama audit: `UNEXPECTED_APPLICATION_BYPASS = 0` | ✅ 1 found and fixed this pass (see above); table above |
| Real cancellation through the real API path | ✅ Bug found and fixed (see above); `tests/test_gateway_sync_bridge.py` |
| Real timeout through the integrated path | ✅ `tests/test_api_gateway_integration.py::test_queue_timeout_surfaces_through_the_real_api_without_reaching_ollama` (found and fixed the `configure()` bug above along the way) |
| Old serving path retirement (no duplicate live-serving branches bypass the Gateway) | ✅ Confirmed via the audit table — `/api/status`'s `get_brain()` call is diagnostic-only, not a generation path; every other live HTTP generation path now resolves through `brain_for_tier_resolution()` |
| Security re-verification | ✅ `tests/test_mcp_fs_server_sandbox.py` + `tests/test_registry_id_sanitization.py`: 31 passed |
| Integrated performance baseline (real API + Gateway) measured | ✅ `INFERENCE_BASELINE.md`'s "Phase 2.1" section — Gateway's own instrumented TTFT (740.9ms) matches the Phase 2 raw-runtime baseline (729.6ms) within noise; Novus not benchmarked (no installed checkpoint on this machine, disclosed rather than fabricated) |
| Documentation deliverables | ✅ `LIVE_SERVING_CUTOVER.md`, `WORKER_ROUTING.md`, `PRIORITY_SCHEDULING.md`, `PHASE_2_CLOSURE.md` (this document) |

## Test suite state

Full suite: **625 passed, 0 failed** (106 pre-existing deprecation warnings, unrelated to this phase). Security suite specifically: **31 passed**. All new tests added this phase exercise real code paths — real local Ollama for every HTTP-level integration test (auto-skipping, not failing, when unreachable), real `FastAPI TestClient` end-to-end requests, real `asyncio` concurrency primitives for the concurrency/priority/cancellation tests — no mocked runtime stands in for a claim about real behavior anywhere in this phase's new tests.

## What remains genuinely unverified, disclosed rather than hidden

- Aeternum's `MODEL_NOT_ROUTABLE` path is proven at the Gateway-unit and wiring levels but not observable through a live `/api/chat` request today, because the pre-existing step-down router (`ultra→core→nano`) resolves away from "ultra" before the Gateway ever sees the request. This is pre-existing router behavior, untouched by this phase, and disclosed in `LIVE_SERVING_CUTOVER.md`.
- No GPU numbers, no sustained-load throughput figures, no Novus benchmark — same disclosed limitations as Phase 2's baseline, now also true of the integrated-path measurement.
- `orca/brain/reasoning.py`'s `ReasoningEngine` still calls `get_brain()` directly and was not cut over, since it has zero callers anywhere in the repository — flagged as dead code, not fixed, since there is no live behavior to change.

## READY TO ADVANCE TO PHASE 3: YES

All three Phase 2.1 gaps are closed, every closure-checklist item is verified with a real (not mocked) test, the direct-Ollama audit found and closed its one bypass, two additional real bugs surfaced during verification were found and fixed with their own regression tests, and the full suite plus the security suite are green. Per the original instruction, this phase now **STOPS** — no Cognitive Kernel (Phase 3) work has been started, and none will begin without explicit human approval.
