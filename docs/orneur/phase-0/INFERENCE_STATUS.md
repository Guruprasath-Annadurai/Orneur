# Orneur Phase 0 — Inference Status

Verified by direct code audit (file:line cited in source findings). No claims here are from README/docstrings alone.

## Runtime

- Self-hosted inference is **Ollama HTTP API only** (`orca/brain/backends.py:142`, `/api/generate`, `/api/embeddings`). No vLLM, SGLang, TensorRT-LLM, or direct llama.cpp-serve integration anywhere.
- Frontier passthrough: `OpenAIBackend` uses the official `openai` SDK (real, standard integration). `AnthropicBackend` uses the `anthropic` SDK via deferred import — **the module's own docstring flags this path as UNVERIFIED / untested live**, not just unverified by this audit.

## Streaming

- `/api/stream` does **real token-level SSE streaming** for the Ollama path (`agent.stream()` → `brain.stream()`, yielding chunks as generated).
- The frontier-passthrough branch does **not** stream — it generates the full response synchronously, then fakes streaming by splitting on words and yielding with `asyncio.sleep(0)`, explicitly commented "Fake-stream" in the code. Any Orneur SLA/UX claim about streaming must caveat this distinction.

## Serving mechanics — what's absent

No KV-cache management, prefix caching, continuous batching, model warmup, or GPU health checks anywhere in `orca/serve/*` or `orca/brain/*` — confirmed absent, not present in disguised form. No request cancellation beyond underlying HTTP client timeouts. No backpressure/load-shedding against the inference engine itself (no queue-depth check, no "Ollama busy" signal).

## Rate limiting — real, but scoped

`orca/serve/ratelimit.py` is a genuine fixed-window counter: Redis `INCR`/`EXPIRE` when configured, else an in-process dict with a lock and a 50,000-entry eviction cap (prevents unbounded memory growth). Keyed by IP, respecting `X-Forwarded-For` — correct behind a real proxy, but **trusts that header unconditionally**: if Orneur is ever deployed without a proxy that strips/sets it, a client can spoof their own rate-limit bucket. Fails **open** (allows the request) on any backend exception — Redis outage silently degrades distributed rate limiting to per-process-only, which under N server instances effectively multiplies the real limit by N. Full endpoint-by-endpoint coverage (every route actually calling `check_rate_limit()`) was **not exhaustively re-verified** — UNVERIFIED, only the primitive itself was confirmed correct.

## Cost-aware routing — real, narrowly-scoped rules engine

`orca/serve/routing.py`'s `decide_route()` gates escalation behind four independent checks: operator opt-in flag, the data-sovereignty lock (hard override), a configured+keyed frontier backend, and `QueryComplexity.suggests_escalation` — which is a **regex heuristic** (time-sensitive words, long/complex phrasing patterns), explicitly documented in its own code as "a heuristic, not a certainty... no trained classifier." A daily escalation spend cap exists but is an **in-memory counter, not persisted** — it resets on process restart, a real gap for a production spend guarantee. This is a legitimate rules-based router, not a trained query-complexity classifier and not a stub — but any "our routing model decides" language needs to say "rules engine," not "classifier."

## Cost/token tracking — real per-request, not aggregated

`BackendResponse` carries real per-request token/cost data (from Ollama's `prompt_eval_count`/`eval_count` or OpenAI/Anthropic's `usage` fields) and logs it to the audit log per request. `orca/serve/metrics.py` itself only aggregates routing-escalation and moderation-fallback **counts** — it does not maintain a queryable running total of cumulative cost/tokens across requests. Pricing tables are hand-maintained snapshots, explicitly flagged in code as "do not treat cost_usd as billing-grade."

## Model resolution (not a registry)

`orca/serve/registry.py` resolves each tier to whichever Ollama model is currently installed on the host, with a strict step-down fallback chain (ultra→core→nano→generic open model — never upgrades a lower tier to substitute for a missing higher one, explicitly to prevent a plan-gating leak). This is host-state-dependent name resolution with graceful degradation, not a versioned model registry — see `MODEL_TRAINING_STATUS.md` for why that distinction matters for Orneur's eventual registry work.

## Summary for Orneur planning

Inference today is single-process, single-host, Ollama-bound for self-hosted serving, with a real but basic rate limiter and a real but rules-based (not learned) router. None of continuous batching, KV/prefix caching, multi-instance horizontal scaling, canary/rollback deployment, or GPU-fleet health checks exist. This is the primary gap behind the "networking/scaling" concern raised earlier in this project's planning — there is currently no story for serving more than one host's worth of GPU capacity.
