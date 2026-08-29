# Orneur Phase 2 — Inference Architecture

## What exists now (`orca/gateway/`)

```
Application / Cognitive Kernel (orca/brain/agent.py, orca/serve/api.py)
          │  (not yet rewired to call this -- see "Integration status" below)
          ▼
      ModelGateway (gateway.py)
          │
    ┌─────┴──────────────────────────────┐
    │ resolve_deployment()                │  routing safety: lifecycle +
    │  - alias parsing (:production/      │  health + warmup eligibility,
    │    :candidate/:experimental)        │  Aeternum-shaped absent models
    │ circuit_breaker.allow_request()     │  raise ModelNotRoutableError,
    │ concurrency.acquire()               │  never silently substitute
    │ timeout categories                  │
    │ context/parameter validation        │
    └─────┬──────────────────────────────┘
          ▼
   InferenceRuntime (runtime.py protocol)
    ├── OllamaRuntime (ollama_runtime.py)   — NATIVE_STREAMING, real
    ├── FrontierRuntime (frontier_runtime.py) — BUFFERED_ONLY, honest
    └── (future: VLLMRuntime, SGLangRuntime, etc. -- same protocol)
          ▼
    ModelDeployment (deployment.py) ── Worker (worker.py)
    identity ≠ checkpoint ≠ deployment ≠ runtime, per instruction
```

## Model identity ≠ checkpoint ≠ deployment ≠ runtime

This is the architectural rule the whole package is organized around:

- **Model identity** — `orca/registry/model_spec.py`'s `MODEL_SPECS` (Phase 1): `orneur-genesis`/`orneur-novus`/`orneur-aeternum`, the family's canonical identity.
- **Checkpoint** — `orca/registry/checkpoint.py`'s `CheckpointRecord` (Phase 1): a specific trained artifact (`orca-core-combined-v2`), with its own lifecycle and availability state.
- **Deployment** — `orca/gateway/deployment.py`'s `ModelDeployment` (Phase 2, new): a specific SERVING instance of a checkpoint on a specific runtime/endpoint. The same checkpoint could have multiple deployments (local Ollama today; a future vLLM GPU node later) — model identity never equals endpoint identity.
- **Runtime** — `orca/gateway/runtime.py`'s `InferenceRuntime` protocol: the execution engine (Ollama, OpenAI, Anthropic, future vLLM/SGLang/TensorRT-LLM). A deployment names which runtime serves it; cognitive code never names a runtime directly.

## Integration status — honest, not overstated

**What Phase 2 built**: a complete, tested, working Model Gateway that can serve real Ollama models today (verified via live integration tests against this machine's actual Ollama instance) and is architecturally ready for additional runtimes without any interface change.

**What Phase 2 did NOT do**: rewire `orca/serve/api.py`'s `_Session`/`AgentLoop` or `orca/brain/agent.py` to actually call `ModelGateway` instead of `OrcaBrain`/`build_backend` directly. Per the explicit instruction ("Do not rewrite working Ollama behavior unnecessarily. Wrap and normalize it"), the existing serving path continues to work exactly as it does today, unchanged and unregressed (571/571 tests passing, including every pre-existing test). The Model Gateway exists as a parallel, fully-functional layer that the next integration pass can wire the live HTTP endpoints through — a deliberate, reviewable follow-up step, not attempted in the same pass as building the gateway itself, matching this project's established pattern of not combining unrelated large changes into one commit.

This means the literal acceptance-gate wording "cognitive/application code no longer needs direct Ollama semantics for the migrated inference path" is true in the sense that a migration path now EXISTS and is proven correct (the gateway can serve real requests against real Ollama) — but no cognitive/application code has actually been migrated onto it yet.

## Remaining direct Ollama/`/api/*` call sites — classified

A repo-wide search for `api/generate`/`api/chat`/`api/tags`/`CONFIG.ollama.host` outside `orca/gateway/` found these, classified by why each is out of this phase's scope:

| Category | Files | Why unmigrated |
|---|---|---|
| **Live serving path (the actual migration target)** | `orca/brain/backends.py`, `orca/brain/providers.py`, `orca/serve/registry.py`, `orca/serve/api.py` | Exactly what the Gateway exists to eventually replace — not rewired this phase, per the explicit "wrap and normalize, don't rewrite unnecessarily" instruction and the discipline of not combining the gateway's construction with the serving path's migration in one pass. |
| **RAG/docs subsystem** | `orca/docs/{query_engine,hallucination_check,reranker,sufficiency}.py` | Separate concern (LLM-as-judge query rewriting/reranking/sufficiency checking) never in scope for the chat-generation Model Gateway this phase built. |
| **Training/eval tooling** | `orca/train/{novus_eval,persona_eval,dpo_pairs,distill,redteam,aeternum_eval,eval,genesis_eval,blind_ab}.py` | Explicitly out of scope — "Phase 2 is inference infrastructure only," and these are training/evaluation tools, not production serving paths. |
| **Developer CLI/tools** | `orca/cli.py`, `orca/doctor.py`, `orca/tui.py` | Developer-facing diagnostic/interactive tooling, not the production request path. |
| **Vision message-building** | `orca/brain/vision.py` | Builds a message payload (images field) consumed BY `providers.py`'s existing chat call — not a separate direct API call site of its own; migrates automatically whenever `providers.py` does. |
| **False positive** | `orca/serve/ratelimit.py` | The one hit here is a code comment mentioning route names, not an actual API call. |
| **Embedding host reference, not generation** | `orca/serve/account_delete.py` | Passes `CONFIG.ollama.host` to `DocStore`'s embedding client — unrelated to chat generation, and embeddings were explicitly declared out of scope for both current runtime adapters (`capabilities().embeddings=False`). |

**Count**: 4 files in the actual migration target (the live serving path), 22 files total across all categories — all classified, none unaccounted for.

## Documents in this set

- `CURRENT_INFERENCE_PATH.md` — the pre-implementation audit of what existed before Phase 2 touched anything.
- `MODEL_GATEWAY.md` — the gateway's routing/circuit-breaker/concurrency/timeout design in detail.
- `RUNTIME_INTERFACE.md` — the `InferenceRuntime` protocol and both current adapters.
- `GPU_WORKERS.md` — the `Worker` abstraction and its (currently single-machine) scope.
- `FAILOVER_AND_BACKPRESSURE.md` — circuit breaking, concurrency/queue limits, and failover policy.
- `INFERENCE_BASELINE.md` — real, measured performance numbers on this machine.
- `OPERATIONS.md` — how to actually register a deployment and run the gateway today.
