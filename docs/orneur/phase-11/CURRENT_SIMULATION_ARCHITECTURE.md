# Phase 11 — Current Simulation Architecture Audit

Every existing mechanism resembling "simulation," classified before any
Simulation Chamber code was written.

| Mechanism | File | Classification | Notes |
|---|---|---|---|
| Phase-6 Counterfactual engine | `orca/deliberation/counterfactual.py` | COUNTERFACTUAL_ONLY | Model/reasoning-based "what if X were different" projections, explicitly carrying `uncertainty_note`, capped at `MAX_COUNTERFACTUALS_PER_REQUEST=3`. This is NOT executable simulation — it never touches a real tool, provider, or filesystem. Phase 11 reuses it for the specific sub-questions spec §16 names ("what if the action is not taken," "what if assumption A is false") but never conflates it with dry-run/sandbox execution. |
| Cognitive Court risk analysis | `orca/deliberation/court.py`, `orca/deliberation/risk_counsel.py` | STATIC_VALIDATION / COUNTERFACTUAL_ONLY | Deliberative, model-assisted risk/contradiction review. No execution. Reused in Phase 11 as an optional REVIEW step over a `SimulationResult` — Court still cannot authorize (Phase 8's invariant, unchanged). |
| `orca/deliberation/worldstate_ops.py` + `WorldState` | `orca/deliberation/contracts.py` | REAL_SIMULATION substrate (read-only projection target) | The existing typed `WorldStateUpdate`/`apply_update()` machinery is exactly the right shape to project a HYPOTHETICAL WorldState from — Phase 11's `WorldStateProjection` reuses these ops applied to a COPY, never the live `WorldState` instance. |
| `orca/code/sandbox.py` | — | REAL_SIMULATION (for Python code, not agent tool actions) | AST-gated, subprocess-isolated, timeout-bounded Python execution for the Code Interpreter feature. A genuine sandbox, but scoped to a completely different feature (chat-facing code execution) — not reused directly by the agent Simulation Chamber, though its "isolate first, bound hard, no prod credentials" philosophy is the template Phase 11's filesystem sandbox follows. |
| `orca/connectors/fake_provider.py` | — | REAL_SIMULATION substrate for connectors | `FakeProviderState`/`fake_write()`/`fake_read()` already model idempotency and `OUTCOME_UNKNOWN` deterministically (Phase 9). This is the REAL, honest mechanism Phase 11's connector simulation reuses — never a new, second fake. |
| `orca.docs.store.DocStore` (via Phase 9's `search_documents`) | `orca/connectors/document_store.py` | REAL_SIMULATION substrate (read path only) | A session-scoped, tenant-namespaced ChromaDB/keyword store already exists; Phase 11 can preview a DOCUMENT_STORE write only through an ISOLATED test collection (spec §27) — no such write path exists yet in Phase 9 (DOCUMENT_STORE is read-oriented), so this is currently MISSING for writes and disclosed as such, not fabricated. |
| `orca.tools._resolve_in_workspace()` | `orca/tools/__init__.py` | STATIC_VALIDATION substrate | Realpath-resolution/symlink-safety discipline already proven in Phase 8/9/10 (reused again by Godmode's `file_elevation.py`). Phase 11's filesystem simulator reuses this EXACT discipline for its own sandbox-root containment, rather than re-deriving path safety a fourth time. |
| CLI `--dry-run` flags | `orca/cli.py`, `orca/train/distill.py`, `orca/train/redteam.py`, `orca/data/pipeline.py` | DRY_RUN (but for OFFLINE TRAINING/DATA PIPELINE tooling, not agent actions) | Genuine "compute what would happen, print it, don't write" flags — but for the training/data pipeline CLI surface, completely unrelated to the Agent Runtime's tool/connector execution path this phase targets. Not reused directly (different domain), but confirms the codebase already has a real, non-fabricated concept of dry-run elsewhere. |
| "Shadow"/"canary" references | `orca/cognitive/metrics.py`, `orca/auth/db.py`, `orca/serve/api.py`, `orca/memory/eval_harness.py`, `orca/memory/latency_bench.py`, `orca/data/seeds.py` | LEGACY / UNRELATED naming | Read each: these are metric-label strings, DB shadow-column migration helpers, and eval-harness scenario names using "canary"/"shadow" as ordinary English words — NONE of them implement shadow-routing or canary-deployment simulation for agent actions. No SHADOW_EXECUTION or PROVIDER_PREVIEW mechanism exists anywhere in the codebase today. |
| Database connector | `orca/connectors/contracts.py` (`ConnectorType.DATABASE`) | CONTRACT_ONLY / MISSING | No real DB client exists (confirmed in Phase 9's own audit, unchanged). No query-plan/EXPLAIN/rollback-preview mechanism exists. Phase 11 defines a provider-neutral CONTRACT for these hooks (spec §30) without implementing fake SQL execution. |
| Test harnesses (`tests/*.py` fixtures, `pytest` itself) | — | TEST_ONLY | Not part of the production simulation surface; excluded from `SimulationProvider` entirely. |
| Deployment canaries / shadow routing (spec's literal ask) | — | MISSING | No infrastructure-level canary/shadow deployment mechanism exists in this codebase (this is a model-serving/production-infra concept, not something Orca's current architecture implements at all). Disclosed as MISSING, not fabricated. |
| "Reversible write" / "compensating action" metadata | `orca/agent/contracts.py` (`SideEffectClass`) | STATIC_VALIDATION (partial) | `SideEffectClass.REVERSIBLE_WRITE` exists as a coarse tag on `ToolSpec`, but there is no structured `CompensationPlan` type anywhere pre-Phase-11 — the enum value alone does not constitute the compensation mechanism spec §22 asks for. Classified PARTIAL: the taxonomy exists, the plan type does not (built this phase). |

## Findings

- **No REAL_SIMULATION mechanism exists yet for actual agent tool/connector
  actions** — every piece of real, non-fabricated infrastructure found
  (`fake_provider.py`, `DocStore`, `_resolve_in_workspace`,
  `worldstate_ops.py`) is a SUBSTRATE Phase 11 can build on, not a
  finished Simulation Chamber. This audit's honest conclusion: Phase 11
  is building new capability, not wiring up something that secretly
  already existed.
- **Phase-6 Counterfactual reasoning must never be conflated with
  executable simulation** — confirmed by reading its own code: it never
  touches a tool, connector, or filesystem. It is reused ONLY for the
  explicitly model-based "what if" questions spec §16 names.
- **No fake shadow/canary deployment mechanism exists** — the string
  matches found are unrelated naming coincidences, not a hidden
  simulation system to build on.
- **DATABASE connector simulation is correctly scoped as CONTRACT-ONLY**
  in Phase 11 too, matching Phase 9's own honest CONTRACT_ONLY
  classification for that connector family — no fake SQL execution is
  implemented.
