# Current Inference Path — Audit (Phase 2, pre-implementation)

Read directly from code before any Phase 2 implementation. No behavior described here was assumed from names or docstrings alone — file:line cited throughout.

## Full request path (self-hosted / Ollama)

```
POST /api/stream  (orca/serve/api.py:592)
  → ratelimit.enforce()                                    (orca/serve/ratelimit.py)
  → detect_generation_intent() — image/video short-circuit
  → check_quota() — per-user daily message quota
  → model_access_allowed() — plan-gating check
  → check_input() — moderation (block/support/flag)
  → _resolve_backend_for_chat(variant)                      (api.py:125)
      → registry.resolve_tier_backend(tier, ...)             (orca/serve/registry.py:159)
          → resolves (backend, model) via CONFIG.*, cached `ollama list`,
            data-sovereignty lock check, step-down chain (ultra→core→nano)
  → _apply_cost_aware_routing(resolution, message)           (api.py:152)
      → routing.decide_route()                               (orca/serve/routing.py:163)
          → regex-heuristic query classification, opt-in escalation,
            daily cap (in-memory, not persisted)
  → IF backend != "ollama": frontier passthrough (see below)
  → ELSE: _get_session() → _Session.__init__               (api.py:212)
      → get_brain(_model_name_for_variant(...))              (orca/brain/providers.py:240)
      → build_registry(memory_engine) — tool registry
      → AgentLoop(brain, tools, session_id)                  (orca/brain/agent.py:76)
  → sess.memory.recall_context() — short/long-term memory injection
  → IF docs loaded: run_deep_rag() — 7-stage RAG pipeline
  → get_persona_system(variant) — governance-gated persona prompt
  → AgentLoop.stream(enriched_message, persona_system)        (agent.py:145)
      → self._plan() — 1 LLM call (direct vs. tools)
      → self._execute_tools() — ≤6 tool calls, no retry loop
      → self.brain.stream(messages, system)                  (orca/brain/providers.py:162)
          → OrcaBrain._build_payload() → httpx.stream POST /api/chat
          → real per-token SSE parsing from Ollama's own streaming response
  → check_web_citations() on final text
  → SSE emission to client (StreamingResponse, media_type=text/event-stream)
```

`/api/chat` (non-streaming, api.py:425) follows the same resolution/routing/session logic but calls `AgentLoop`'s non-streaming path and returns a single JSON response instead of SSE.

## Frontier passthrough path (OpenAI/Anthropic)

Branches at `backend_resolution.backend != "ollama"` (api.py:649, and the equivalent branch in `/api/chat`). Does **not** construct a `_Session`/`AgentLoop` at all — no tools, no memory, no RAG for this path (explicitly documented as an honest scope limitation in `_generate_via_frontier_backend`'s docstring, api.py:179).

```
_generate_via_frontier_backend(resolution, persona_system, message)   (api.py:179)
  → build_backend(resolution.backend, resolution.model, api_key=...)   (orca/brain/backends.py:271)
  → backend.generate(prompt, system, max_tokens=1024)                  (backends.py: OllamaBackend/OpenAIBackend/AnthropicBackend)
  → returns BackendResponse (synchronous, single-shot, no streaming)
```

## Two separate, non-unified Ollama HTTP clients (real duplication, confirmed)

1. **`orca/brain/providers.py`'s `OrcaBrain`** — used by the main self-hosted chat/agent path. Talks to `/api/chat` (message-array format), has its own model-resolution fallback (`_resolve_model`, distinct from `registry.py`'s), its own retry logic (1 retry on `httpx.TimeoutException`, distinguishing pre-output vs. mid-stream timeout), 120s timeout.
2. **`orca/brain/backends.py`'s `OllamaBackend`** — used only by the frontier-passthrough cost-aware-routing path (`build_backend("ollama", ...)`, reachable when `_apply_cost_aware_routing` resolves back to Ollama after a frontier attempt, or by direct construction). Talks to `/api/generate` (single-prompt format, not message-array), no retry logic, 120s timeout, no streaming method at all (`generate()` only).

These are genuinely separate implementations with different request formats, different retry behavior, and no shared abstraction — exactly the "duplicate model client logic" Phase 2's audit was asked to find.

## Streaming: real vs. fake (confirmed, not assumed)

- **Ollama path**: real, token-level SSE streaming. `OrcaBrain.stream()` (providers.py:162) opens `httpx.stream(..., "/api/chat")` and yields each `message.content` delta as Ollama produces it — genuine incremental output.
- **Frontier passthrough path**: **fake streaming**, explicitly labeled as such in the code's own comment (api.py:677: `"Fake-stream: ... are synchronous only ... so chunk the finished text by word"`). The full response is generated synchronously via `asyncio.to_thread`, then split on whitespace and yielded word-by-word with `await asyncio.sleep(0)` — no actual incremental generation, just a post-hoc illusion of streaming for the frontend's existing per-chunk SSE renderer.

## Timeouts (found, all single-valued — no category separation exists yet)

| Call site | Timeout | Retry |
|---|---|---|
| `OrcaBrain.complete()`/`.stream()` (providers.py) | 120s | 1 retry on `httpx.TimeoutException`, but only if a stream retry happens **before** any content has been yielded — a mid-stream timeout raises instead of retrying (correctly, to avoid duplicating partial output) |
| `OllamaBackend.generate()` (backends.py:142) | 120s | none |
| `OllamaBackend.is_available()` (backends.py:125) | 5s | none |
| `registry.py`'s `_list_installed_models` | 5s | none, but result cached 15s to avoid hammering `/api/tags` |
| `redteam.py`'s `_generate()` (training/eval tooling, not the serving path) | 60s hardcoded | none |

No distinction exists anywhere between queue-wait time, connect time, time-to-first-token, and total-generation time — it is one timeout value per call site, exactly as Phase 2's brief anticipated.

## Request cancellation

**None found.** No code path propagates a client disconnect or an explicit cancel signal down into the Ollama HTTP call. A client closing its SSE connection early does not stop `AgentLoop.stream()`'s generator from continuing to pull tokens from Ollama and burn compute — the generator simply stops being iterated by FastAPI once the response is discarded, but the underlying `httpx.stream` request to Ollama is not explicitly aborted by any code found in this audit (Starlette/FastAPI's connection-close handling may implicitly cancel the coroutine at the `await` boundary inside `iter_lines()`, but no code in this repo does this deliberately or tests for it).

## Rate limiting / concurrency

`orca/serve/ratelimit.py`'s `enforce()` is a per-IP fixed-window request-count limiter (Redis-backed if configured, else in-process dict, 50k-entry eviction cap) — this caps **requests per time window**, not **concurrent in-flight generations**. No semaphore, queue, or concurrency cap on simultaneous Ollama calls was found anywhere in `orca/serve/` or `orca/brain/`. Multiple simultaneous chat requests each independently open their own `httpx` connection to Ollama with no coordination — confirmed as the direct cause of this session's own CPU-contention timeouts during Phase 0.5/1 evaluation runs on a memory/CPU-constrained machine.

## Model aliases / health checks

- **Aliases**: `CONFIG.ollama.model_nano/core/ultra` (env-configurable Ollama tag names) plus `registry.py`'s step-down chain (ultra→core→nano→none). No versioned alias concept (`orneur-novus:production` vs `:candidate`) exists in the serving path — that's Phase 1's registry/lifecycle work, which is currently **not integrated** with this resolution logic at all (two entirely separate systems today).
- **Health checks**: `OllamaBackend.is_available()` and `OrcaBrain.is_available()` both just hit `/api/tags` with a short timeout and return a bool — no distinction between "Ollama reachable" and "this specific model is loaded and ready to generate," no warmup concept, no health state machine (just a boolean).

## Token counting / context-length handling

Token counts are read from Ollama's own response fields (`prompt_eval_count`, `eval_count`) after the fact — there is no pre-flight estimate of input token count against a model's context limit anywhere in the serving path. `CONFIG.brain.context_length` is passed as `num_ctx` to Ollama, but nothing validates a request would actually fit before sending it; an oversized request's failure mode is whatever Ollama itself does (silent truncation or an error, depending on Ollama's own behavior), not a structured, caught-in-advance error from Orca's own code.

## Error handling

Errors surface as either a raised `RuntimeError` (self-hosted path, generally caught by FastAPI's default exception handling → 500) or an inline `{"type": "error", "text": str(e)}` SSE event (frontier passthrough and several pre-flight checks in `/api/stream`, e.g. quota/model-gate/moderation-block). **No structured, typed error taxonomy exists** — every error is either a raw exception message or an ad-hoc string, with no consistent error-code field a client could branch on programmatically.

## Direct application-code dependence on Ollama-specific behavior

Confirmed direct couplings that Phase 2's Model Gateway must abstract away:
- `orca/serve/api.py`'s `_Session.__init__` calls `get_brain()` (an `OrcaBrain`, Ollama-specific) directly — no runtime-agnostic construction path exists.
- `orca/brain/agent.py`'s `AgentLoop` takes a `brain` object typed as `OrcaBrain` implicitly (duck-typed, but every call site constructs the concrete class) — cognitive/application logic (`_plan`, `_execute_tools`, `stream`) calls `self.brain.stream(...)`/`self.brain.complete(...)` with `OrcaBrain`'s exact method signatures, not an abstracted runtime interface.
- `orca/serve/registry.py`'s tier resolution talks to Ollama's `/api/tags` directly to determine "is this model installed" — there is no generic "is this deployment available" concept a non-Ollama runtime could satisfy.

## Summary for Phase 2 scoping

Everything in this document is real, current behavior — nothing here is aspirational. The two most load-bearing findings for the Model Gateway design: (1) there are genuinely **two** separate Ollama clients today, not one, both of which need to end up behind a single adapter without regressing either's real fixes (the retry/timeout robustness in `providers.py`, the frontier-passthrough scope honesty in `backends.py`); (2) fake streaming is real, already labeled honestly in its own code comment, and must not be allowed to silently pass as "streaming" once wrapped behind a clean interface — the Model Gateway must expose the NATIVE_STREAMING/BUFFERED_ONLY distinction explicitly, not paper over it.
