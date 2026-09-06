# Orneur Phase 0 — Current Architecture (as of Orca)

**Repository**: `/Users/ag/orca` · **Branch**: `session-update-2026-08-25` · **HEAD**: `8eb4ee6c54d999402a6878d9899945d232ce33b2` (2026-08-29)

This document states what EXISTS, verified against code, versus what is PLANNED (found only in docs/roadmaps). Nothing here was invented — see the companion audit docs for file:line citations behind each claim.

## Repository shape

Single Python package, not a monorepo. `pyproject.toml`: pip name `orca-ai`, importable module `orca`, CLI binary `orca` (same as module — `[project.scripts] orca = "orca.cli:app"`).

```
orca/
  serve/     — FastAPI app: api.py, routing.py, registry.py, ratelimit.py,
               moderation.py, dlp.py, session_store.py, metrics.py,
               export.py, account_delete.py, web/ (landing page + static UI)
  auth/      — apikeys.py, rbac.py, totp.py, middleware.py, tokens.py,
               crypto.py, db.py, org_store.py, privacy.py,
               migrate_to_postgres.py
  brain/     — memory.py (4-layer memory engine), agent.py (AgentLoop),
               backends.py (Ollama/OpenAI/Anthropic model backends),
               knowledge_graph.py
  docs/      — RAG pipeline: chunker.py, semantic_chunker.py, extractor.py,
               citation_check.py, hallucination_check.py, pii_redact.py,
               query_engine.py, reranker.py, sufficiency.py, store.py
  tools/     — web_search, run_code, read/write_file, shell, security_scan,
               memory_recall, investor_research (registry in __init__.py)
  train/     — distill.py, dpo_pairs.py, losses.py, redteam.py,
               genesis_eval.py, novus_eval.py, eval.py, blind_ab.py,
               finetune.py, cloud.py, config.py, variants.py, prepare.py,
               regression.py, persona_eval.py, aeternum_eval.py
  governance/— model_cards.py (persona-claim gate, reads eval/redteam JSON)
  variants/  — core.py, nano.py, ultra.py (CLI-facing per-tier runtime)
  mcp/       — fs_server.py, memory_server.py (Orca exposed AS an MCP server)
  lens/      — image generation (generate.py, intent.py, safety.py)
  license/   — stripe_hook.py, keys.py, mailer.py
  ops/       — backup.py
  personas.py, character.py, config.py, cli.py, doctor.py, tui.py
```

## Service map (EXISTS)

- **Single FastAPI process** (`orca/serve/api.py`) serving `/api/chat`, `/api/stream`, `/api/session/*`, `/healthz`, auth routes, admin/export routes.
- **Inference backends**: Ollama over local HTTP (`/api/generate`, `/api/embeddings`) is the only self-hosted engine — no vLLM/SGLang/TensorRT-LLM/llama.cpp-serve integration. Frontier passthrough to OpenAI (official SDK) and Anthropic (SDK, flagged UNVERIFIED/untested live path in its own docstring) exists for opt-in cost-aware escalation.
- **Storage**: SQLite at `~/.orca/auth.db` by default; Postgres via `ORCA_DATABASE_URL` for multi-instance (schema includes RLS policies, but the module itself documents these as "not wired into every call site yet"). ChromaDB (vector) for RAG/long-term-memory, falling back to on-disk JSONL + hand-rolled BM25-style TF-IDF if chromadb is unavailable. Redis (optional, `ORCA_REDIS_URL`) for cross-instance session continuity and rate-limit counters — fails open (falls back to in-process) if Redis is down.
- **Fine-tuning**: entirely offline, decoupled from serving — Kaggle/Colab notebooks (T4-class single GPU) running plain HF `Trainer` or Unsloth+TRL depending on the tier, producing LoRA adapters merged and exported to GGUF for Ollama import.

## Data flow (EXISTS)

1. Request → `orca/serve/middleware` (auth: API key or JWT) → rate limit check → `orca/serve/registry.py` resolves tier (nano/core/ultra) to a currently-installed Ollama model, or to a frontier backend if cost-aware escalation is enabled and the data-sovereignty lock allows it.
2. `orca/brain/agent.py`'s `AgentLoop` runs a **single fixed pipeline** — Plan (1 LLM call) → Act (≤6 tool calls, hard-capped, no retry loop) → Respond → optional single Reflect pass. Not an iterative ReAct loop; bounded by construction, not by a runtime guard.
3. If document/web context is available, `orca/docs/pipeline.py` runs real Self-RAG/CRAG-style retrieval: query rewriting, multi-hop decomposition, HyDE, multi-query expansion, one bounded corrective-retrieval round, LLM-as-reranker (RRF fusion), and a sufficiency/contradiction judge — then `citation_check.py` enforces that at least one `[D#]`/`[S#]` marker appears in the response (marker-presence only, not claim-to-source verification).
4. `orca/brain/memory.py`'s 4-layer `MemoryEngine` (short-term window, long-term vector store, episodic session logs, LLM-distilled semantic facts) plus a separate `KnowledgeGraph` (entity/relationship extraction) run alongside the main turn.
5. Response streams via SSE for the Ollama path (real token-level streaming); the frontier-passthrough path fakes streaming by generating the full response then splitting it into a simulated stream.

## Training architecture (EXISTS, decoupled from serving)

Distill (teacher→student data-gen) → DPO-pair generation (safety_refusal, honesty_hedging, bias_mitigation domains, probe-grounded) → SFT/DPO/joint-combined-SFT training notebook (single T4 GPU) → adapter saved → separate merge+GGUF-export notebook (fp16 merge, Unsloth GGUF export or `llama.cpp convert_hf_to_gguf.py` fallback) → `ollama create` import. No dataset versioning/checksums, no active experiment tracking (wandb is wired but the flag is never flipped on; mlflow has zero references), no model registry with promotion/rollback — `orca/serve/registry.py` only resolves "whichever Ollama model is currently installed" per tier with a strict step-down fallback chain.

## Deployment architecture (EXISTS)

`Dockerfile` + `Dockerfile.fly` (COPY orca/, CMD `["orca", "serve", ...]`), `docker-compose.yml`, `k8s/{deployment,service,configmap}.yaml` (**no Terraform**), `fly.toml` (app name `orca-demo`). CI: `.github/workflows/{test.yml,seed.yml,eval.yml}` (pytest, data-seed, model-eval jobs). **Naming inconsistency already present pre-Orneur**: k8s and docker-compose resource names are `atheris`/`atheris-config`/`atheris-secrets`/`atheris-pvc`/`atheris-ingress` — a *third* brand name already live in deployment manifests, distinct from both "Orca" (code/package) and the target "Orneur" — see `BRAND_MIGRATION_PLAN.md`.

## EXISTS vs PLANNED — quick reference

| Area | EXISTS | PLANNED / absent |
|---|---|---|
| Model tiers | 3 tiers wired (nano/core/ultra), nano+core have real trained adapters | Ultra ("Aeternum") has **no confirmed fine-tuned checkpoint yet** — test suite explicitly covers the zero-training-data case |
| Live search | DuckDuckGo scrape + citation + injection-sanitization, wired into agent tools | A paid real-time search API (Brave/Bing/Serper) — the one specific gap `docs/DEVELOPMENT_PHASES.md` Phase 2 calls out; the rest of Phase 2 (citations, sanitization) is already shipped, making that roadmap doc stale |
| Hallucination detection | `hallucination_check.py`'s LLM-judge grounding check is fully implemented | **Not wired into any call site** — dead code, zero callers found repo-wide |
| Agentic loop | Bounded single-pass agent loop (nano/core); real bounded multi-agent pod for "ultra" (parallel roles, dependency graph, capped self-heal retries) | An iterative, tool-result-informed re-planning loop does not exist for any tier |
| Enterprise connectors | None | GitHub/Slack/Drive/Notion/email/calendar — entirely absent, confirmed net-new |
| Model registry | Tier→currently-installed-model resolver with fallback | Versioning, promotion workflow, rollback command |
| Distributed training | None | All training is single-GPU (T4-class); zero references to `torch.distributed`/`deepspeed`/DDP in first-party code |
| Container/K8s naming | Working Docker/k8s/Fly manifests | Consistent branding — currently split across Orca/Atheris even before Orneur |
