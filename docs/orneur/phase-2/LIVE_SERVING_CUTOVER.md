# Live Serving Path — Cutover to ModelGateway

## BEFORE (Phase 2 baseline, verified by re-reading the code, not assumed)

```
POST /api/stream (orca/serve/api.py:592)
  → ratelimit.enforce() / quota / model-gate / moderation checks (unchanged, preserved)
  → _resolve_backend_for_chat(variant) → registry.resolve_tier_backend()
      (returns TierResolution: tier, backend, model, data_left_infrastructure)
  → _apply_cost_aware_routing() → routing.decide_route()
  → IF backend != "ollama":
        _generate_via_frontier_backend()
          → build_backend(resolution.backend, resolution.model, api_key=...)  [orca/brain/backends.py]
          → backend.generate(prompt, system, max_tokens)   ← RAW backend call, no Gateway
  → ELSE (backend == "ollama"):
        _get_session() → _Session.__init__()
          → get_brain(_model_name_for_variant(model_variant))   [orca/brain/providers.py]
              → resolve_tier_model() → OrcaBrain(model=...)     ← RAW Ollama client, no Gateway
          → AgentLoop(brain=OrcaBrain_instance, tools, session_id)
        sess.agent.stream(enriched, persona_system)
          → self.brain.stream(messages, system)   ← calls OrcaBrain.stream() directly,
                                                       httpx straight to Ollama's /api/chat
```

Two genuinely separate raw-backend call sites reached user traffic: `OrcaBrain` (Ollama, via `providers.py`) and `Backend.generate()` (frontier, via `backends.py`) — neither went through anything resembling the Model Gateway built in Phase 2.

## TARGET (this phase)

```
POST /api/stream
  → [UNCHANGED] auth / ratelimit / quota / moderation / model-gate
  → [UNCHANGED] registry.resolve_tier_backend() / routing.decide_route()
      -- this remains "the existing Orneur Router": it still decides
      WHICH tier/backend/model policy applies. The cutover does not touch
      this decision layer at all.
  → [NEW] orca.gateway.wiring.brain_for_tier_resolution(resolution)
      → ensures a ModelDeployment is registered for this exact
        (backend, model) pair on the shared ModelGateway (idempotent --
        safe to call every request)
      → returns a GatewayBrain -- an object with the EXACT SAME interface
        AgentLoop/api.py already call (.complete/.stream/.is_available/.name),
        so nothing above this line needs to change
  → sess.agent.stream(...) → self.brain.stream(...)
      → GatewayBrain.stream() → ModelGateway.stream() [ASYNC]
          → resolve_deployment() -- lifecycle/health/warmup/artifact-
            availability eligibility, exactly as tested in Phase 2
          → circuit_breaker.allow_request()
          → concurrency.acquire() -- now worker-aware and priority-aware
            (see WORKER_ROUTING.md, PRIORITY_SCHEDULING.md)
          → OllamaRuntime.stream() / FrontierRuntime.stream()
              -- the ONLY place that speaks Ollama/OpenAI/Anthropic
                 request syntax
```

## The one deliberate policy decision this cutover makes explicit

**Today's live traffic has never been gated by Phase 1's promotion system** — `CONFIG.ollama.model_core` (`orca-core-combined-v2`) is served to every ordinary chat request today regardless of its real `NOT_PROMOTABLE` lifecycle, because the promotion/lifecycle system didn't exist until Phase 1, and nothing in the serving path ever consulted it. Cutting the serving path over to `ModelGateway` while **preserving existing behavior** (an explicit instruction) therefore means: the tier-resolution bridge (`orca/gateway/wiring.py`) registers these dynamic deployments as `EXPERIMENTAL` lifecycle (their honest, real state) and calls the Gateway with `allow_experimental=True`. This is not "turning Novus into a production model" — it is the Gateway now truthfully modeling what has always been true (nothing is promoted yet) instead of having no lifecycle concept at all. A caller that wants the STRICT production-only guarantee can call `ModelGateway.generate()` directly with a bare `model_id` and `allow_experimental=False` (or the default) and correctly gets `ModelNotRoutableError` today, for every model, since nothing has cleared promotion — that behavior is unchanged and untouched by this cutover.

## Frontier path

`_generate_via_frontier_backend` now resolves through `orca.gateway.wiring.brain_for_tier_resolution()` too (which detects `resolution.backend != "ollama"` and registers/uses a `FrontierRuntime`), so the same `GatewayBrain` interface serves both paths — `orca/serve/api.py` no longer imports or calls `build_backend`/`Backend.generate()` directly for the live chat/stream endpoints. `BUFFERED_ONLY` streaming remains exactly what it was (word-chunked after a synchronous call) — the Gateway does not invent real streaming for a provider that can't do it.

## Genesis/Aeternum through the live path — honest disclosure

`registry.resolve_tier_backend()`'s existing step-down chain (`ultra → core → nano`) runs **before** the Gateway ever sees a request — this is unchanged, preserved existing behavior. Since no Aeternum checkpoint exists, an "ultra" tier request is *already* silently resolved to "core"'s model by the pre-existing router, long before `orneur-aeternum` would ever reach `ModelGateway.resolve_deployment()`. This means the live HTTP API cannot currently exercise Aeternum's `MODEL_NOT_ROUTABLE` path end-to-end — that is proven at the Gateway-unit level (Phase 2's tests) and at the wiring level (this phase's tests, see `PHASE_2_CLOSURE.md`), but not observable through a real `/api/chat` request today, because the existing step-down router never lets a request reach that far. This is disclosed here rather than silently left unstated.
