# Society Authority Audit (Phase 7.1 spec §3)

Classification of every active model call site.

| Call site | Classification | Notes |
|---|---|---|
| `orca.deliberation.court.CognitiveCourt.run()` Constructor/Falsifier | **SOCIETY_ROUTED** | Migrated Phase 7 (spec §41), extended Phase 7.1 with WorldState-driven exclusion and operational budget enforcement. |
| `orca.truth.truth_fabric.TruthFabric.verify_answer()` (claim extraction, per-claim verification, contradiction judging) | **SOCIETY_ROUTED** | Migrated Phase 7.1 (spec §5-6). Default (unoverridden) `tier` now resolves via `CLAIM_EXTRACTOR`/`VERIFIER` roles -- this IS the live production path since `CognitiveKernel` never overrides `tier`. |
| `orca.truth.truth_fabric.TruthFabric.assess_evidence()` → `reform_query()` | **SOCIETY_ROUTED** | Migrated Phase 7.1 via `QUERY_REWRITER` role. |
| `orca.memory.candidates.extract_candidates_via_gateway()` | **SOCIETY_ROUTED (unwired)** | Default tier resolves via `MEMORY_SELECTOR` role, but this function has **zero production callers** (verified: no caller in `orca/` or `tests/`) -- migrated for correctness-when-eventually-wired, not because it's live today. |
| `orca.brain.agent.AgentLoop` (`self.brain.complete`/`.stream`) | **LEGACY_COMPATIBILITY** | `Brain`/`GatewayBrain` is selected ONCE per session/request via the existing `orca.cognitive.policy`→tier resolution, not per-role per-call. Migrating this to per-call Society role resolution would require restructuring `AgentLoop`'s Brain-injection lifecycle -- explicitly forbidden this phase ("without redesigning Agent Runtime", spec §8). Disclosed, not silently skipped. |
| `orca.variants.ultra.OrcaUltra` (`_decompose`/`_run_agent`/`_synthesize`/`_grade`, all via `self.brain`) | **LEGACY_COMPATIBILITY** | Same architectural reason as AgentLoop -- one `Brain` object per pipeline run, not per-role. Spec §9 explicitly forbids redesigning Ultra's workflow. |
| `orca.serve.routing.decide_route()` (cost-aware frontier escalation) | **NON_SOCIETY_SCOPE** | A different concern entirely (self-hosted vs. frontier-API cost escalation for the legacy `/api/chat` path), not a cognitive-role decision. Untouched by any Orneur phase to date. |
| `orca.serve.registry.resolve_tier_backend()` | **NON_SOCIETY_SCOPE** | The underlying tier→backend/model resolver Model Society's `model_id_to_tier()` still hands off to. Not itself a role-routing decision. |
| `orca.gateway.wiring.brain_for_tier_resolution()` | **DETERMINISTIC_NO_MODEL** (infrastructure) | Registers/persists the `ModelDeployment` record for whatever tier the CALLER already resolved -- does not itself choose a role or model, just wires the resolved choice to a servable deployment. |
| `orca.docs.pipeline.detect_contradictions(...)` (docs ingestion path) | **LEGACY_COMPATIBILITY** | A separate call site from Truth Fabric's own `detect_contradictions` usage, in the document-ingestion pipeline; passes its own `ollama_host`/`llm_model` directly. Not part of the Deliberation/Truth Fabric request path Society governs this phase. |
| `orca.registry.*` (training/eval scripts, redteam harnesses) | **TRAINING_ONLY** / **EVALUATION_ONLY** | Model training and evaluation infrastructure -- explicitly out of scope for Model Society routing (spec §69: no training in this phase; evaluation harnesses intentionally use fixed, known checkpoints, not adaptive routing). |
| CLI tooling (`orca chat`, training scripts) | **CLI_ONLY** | Operator-invoked, not part of the request-serving path Society governs. |
| `EvidenceClerk` / `RiskCounsel` / `Arbiter` / `MemoryArbiter` | **DETERMINISTIC_NO_MODEL** | No model call at all -- correctly left untouched (spec §4: "do not route deterministic logic through models"). |

## Required final value

**`UNEXPECTED_SOCIAL_ROUTING_BYPASS = 0`** for every call site classified as a live, in-scope production cognitive model call. The two `LEGACY_COMPATIBILITY` entries (AgentLoop, Ultra) are NOT bypasses -- they were never migrated in the first place, and the reason is disclosed architecturally, not hidden. A "bypass" would mean a call site THAT SHOULD go through Society silently resolving a literal tier instead; no such call site was found in this audit.
