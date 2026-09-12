# PHASE 16 — Native Intelligence Baseline & Architecture Audit

Status: AUDIT PHASE ONLY. No model weights modified, no training run, no OCL/epistemic
implementation, no new router logic, no Phase 17 functionality. This document records what
repository evidence actually shows, not what the Phase 16 prompt assumed.

## 0. Repository-path discrepancy (documented per prompt's own honesty rule)

The Phase 16 prompt asserted the local repo is `/Users/ag/Projects/Orneur`. That path exists but
is a **separate, stale clone** of the same GitHub remote (`Guruprasath-Annadurai/Orneur`), checked
out on `main` at `b412e5a` — a commit that predates all Phase 15 work. It does not contain the
stated HEAD `ee299c72...`.

The repository that actually matches every fact the prompt asserted (branch
`session-update-2026-08-25`, HEAD `ee299c72c9daa2d87b0e5fe6e7df522c8e7b73f1`, HEAD's parent
`1945bae95382732a10e6f107da99c59d7bb7549b`) is **`/Users/ag/orca`**. Verified directly:

```
git branch --show-current   -> session-update-2026-08-25
git log -1 --oneline        -> ee299c72 Phase 15.15 evidence: append-only CI truthfulness correction
git log -1 --format=%P HEAD -> 1945bae95382732a10e6f107da99c59d7bb7549b
git status                  -> clean
```

Per the prompt's own instruction ("repository evidence wins... the contradiction must be
documented"), all Phase 16 work is performed in `/Users/ag/orca`.

## 1. Phase 15 baseline (verified, not redone)

Phase 15 closed (per `PHASE15_IMPLEMENTATION_PLAN.md`, `PHASE15_REQUIREMENTS.md`,
`PHASE15_EVIDENCE.md`, all re-inspected this phase) with: durable Mission engine (15-state
machine), operation lifecycle + idempotency ledger, Product Contract / Requirement Compiler,
Production Proof generator, ORNEUR Relay (with security modes, reconnect/idempotency, six-hour
governance), Cognitive Court foundation, anti-test-gaming discipline, and the 15.15 CI-truthfulness
closure (pipefail-safe CI, 3 honest collection-error fixes, 2 deselect waivers removed and
root-caused, full re-qualification on the final commit). None of Phase 15's 46 registered
requirements are intelligence-architecture requirements — all 21 `REQ-*` prefixes in
`PHASE15_REQUIREMENTS.md` are Mission/Relay-scoped. No overlap or double-counting risk with
Phase 16's new `REQ-*` prefixes.

## 2. Repository-wide intelligence inventory

Depth: module docstring + signature/class inspection + test-file cross-reference count (an
audit-appropriate depth per Phase 16 §33's own efficiency framing — this is an INVENTORY, not a
rewrite). Full table:

| Component | Files (lines) | Purpose | Current Reality | Tests (files) | Reuse Decision | Phase Destination |
|---|---|---|---|---|---|---|
| `orca/cognitive/` | kernel.py, contracts.py, errors.py, state_machine.py (2476) | Control-plane layer converting a CognitiveRequest into a plan; explicitly does NOT call inference/RAG/tools/memory itself | VERIFIED_EXISTING (bounded, contract-only layer) | 58 | REUSE — closest existing precursor to Phase 17 OCL entry contract | Phase 17 (entry contract), Phase 16 (contract review only) |
| `orca/registry/` | model_spec.py, checkpoint.py, model_registry.py, training_run.py, evaluation_registry.py, dataset_manifest.py, artifact_retention.py (974) | Model identity, checkpoint provenance, lifecycle/promotion state machine, dataset/training-run manifests | VERIFIED_EXISTING — real, enforced promotion gate (`ModelRegistry.promote()` requires a `PROMOTABLE` `EvaluationReport`, refuses otherwise via `PromotionDenied`) | 24 | REUSE — this is Phase 16 §12's Model Identity Contract already substantially built; audit gap documented below, not redesigned | Phase 16 (reconcile), Phase 18/22+ (training/promotion) |
| `orca/society/` | router.py, profiles.py, lifecycle.py, eval_harness.py, escalation.py, disagreement.py, society_plan.py, role_requirements.py, budget_ledger.py (1527) | Genesis/Novus/Aeternum routing engine; deterministic hard filters + evidence-weighted selection | VERIFIED_EXISTING | 18 | REUSE — routing invariants (§13) validated against this real implementation | Phase 20 (routing implementation extends this) |
| `orca/deliberation/` | court.py, twin.py, causal.py, counterfactual.py, arbiter.py, worldstate_*.py, hypothesis.py, evidence_clerk.py, budget_market.py, replanning.py, risk_counsel.py, compiler.py (1899) | Cognitive Court: structured verdicts (ACCEPT/REVISE/REJECT/INSUFFICIENT_EVIDENCE (the real orca.deliberation.contracts.CourtVerdictState values -- corrected from an earlier draft that misstated this enum) via `CourtVerdictState`), WorldState, Epistemic Twin | VERIFIED_EXISTING | 22 | REUSE — governance-primitive vs model-orchestration boundary already respected in code (see §17 below) | Phase 24 (Twin Distillation extends `twin.py`) |
| `orca/gateway/` | gateway.py, wiring.py, deployment.py, circuit_breaker.py, ollama_runtime.py, frontier_runtime.py, contracts.py, errors.py (2129) | Model Gateway: single call point for inference; normalizes Ollama vs frontier (OpenAI/Anthropic) providers | VERIFIED_EXISTING | 37 | REUSE — natural home for native-vs-external-provider distinction (§15) | Phase 17+ inference plane |
| `orca/agent/` | orchestrator.py, planner.py, contracts.py, capability.py, delegation.py, policy.py, runtime.py, court_hook.py, tool_registry.py, truth_hook.py, memory_hook.py (2196) | Agent runtime: goal→plan compilation, tool execution, capability/policy enforcement | VERIFIED_EXISTING | 31 | REUSE — `policy.py` docstring: "The ONLY thing that may authorize [elevated actions]" — matches Phase 16's governance-boundary requirement | Phase 19+ orchestration |
| `orca/truth/` | truth_fabric.py, llm.py, verification.py, evidence.py, claims.py, contradiction.py, citation.py, provenance.py, graph.py, decomposition.py, search_provider.py, corrective.py, counter_evidence.py, fetch.py, planner.py, state.py (2435) | Evidence-grounded claim verification, citation, retrieval | VERIFIED_EXISTING | 28 | REUSE | Phase 17 evidence-reference contract |
| `orca/brain/` | providers.py, backends.py, memory.py, context_intelligence.py, knowledge_graph.py, reasoning.py, explainability.py, vision.py, agent.py, context.py (1838) | Predates the Gateway/Cognitive split; `providers.py` docstring "Orca Brain — 100% local, 100% yours" and `agent.py` "god-mode reasoning" are legacy-era framing | PARTIAL / LEGACY (superseded in flow by `orca/gateway` + `orca/cognitive`, but `memory.py`'s `SemanticMemory` is still the live, single memory backend — see §16) | 12 | SHOULD_MIGRATE_DURING_NATIVE_PHASES (naming/framing only; `memory.py` itself stays) | Phase 26 (Outcome Memory boundary) |
| `orca/learning/` | curriculum.py, dedupe.py, pipeline.py, provenance.py, regression_suite.py, sanitize.py, security.py, signals.py, training_experiment.py, triage.py, audit.py, observability.py, contracts.py (2079) | Failure→Curriculum native learning loop (Phase 12): triage, dedupe, sanitize, security-gated candidate admission | VERIFIED_EXISTING but thinly tested relative to size | 6 | REUSE — direct precursor to Failure Genome / Capability Delta | Phase 25 (Failure Genome), Phase 27 (Capability Delta) |
| `orca/train/` | losses.py, distill.py, finetune.py, config.py, variants.py, genesis_eval.py, novus_eval.py, aeternum_eval.py, dpo_pairs.py, blind_ab.py, redteam.py, regression.py, prepare.py, cloud.py, eval.py (4962) | QLoRA fine-tuning, distillation, per-family eval sets, red-team suite | VERIFIED_EXISTING (training plane); `variants.py` had a real historical base-model inconsistency now resolved by `model_spec.py` | 14 | REUSE — training/learning plane separation (§14) draws the boundary here vs `orca/registry` | Phase 18 (Twin Distillation training) |
| `orca/governance/` | model_cards.py (401) | Signed model-card provenance; `PERSONA_CLAIM_THRESHOLDS` used by `evaluation_registry.py`'s promotion gating | VERIFIED_EXISTING but thin (1 test file) | 1 | REUSE | Phase 22 (promotion policy) |
| `orca/mcp/` | fs_server.py, memory_server.py (302) | MCP tool servers (filesystem, memory) exposed to external MCP clients | VERIFIED_EXISTING, security-hardened (`_safe_path`) | 1 (+ security test fixed in 15.15) | REUSE, unchanged | N/A — tool layer, not model layer |
| `orca/lens/` | generate.py, intent.py, queue.py, safety.py (464) | Local image generation (Flux.1 schnell) — adjacent capability, not a cognition/model-identity concern | VERIFIED_EXISTING, narrow scope | 3 | INTERNAL_COMPATIBILITY_ACCEPTABLE, out of Phase 16 scope | N/A |
| `orca/memory/` | store.py, arbiter.py, candidates.py, consolidation.py, deletion.py, entity.py, episodic.py, failure.py, firewall.py, procedural.py, reflex.py, refresh.py, retrieval.py, salience.py, significance.py, turn_ingest.py, agent_memory.py (2464) | Memory Continuum (Phase 5): typed candidate pipeline, arbitration, firewall, consolidation — SEPARATE from `orca/brain/memory.py`'s `SemanticMemory` | VERIFIED_EXISTING, real governance discipline (`firewall.py`: "No recalled memory reaches [output] without...") | not fully cross-referenced this pass | REUSE — this, not `orca/brain/memory.py`, is the correct target for Phase 26 Outcome Memory extension | Phase 26 |
| `orca/variants/` | core.py, nano.py, ultra.py (606) | Pre-Gateway "Orca Core/Nano/Ultra" variant definitions — "god-mode variant", "apex multi-agent orchestrator" framing | LEGACY — **zero test files reference this package** | 0 | SAFE_TO_DEPRECATE (naming AND behavior: superseded by `orca/registry/model_spec.py` + `orca/gateway`) | Deprecate before Phase 20 |

Note on depth: this table is built from docstrings, class/enum signatures, and targeted greps
(not full-file reads of all ~30K lines) — adequate for an architecture-baseline audit; any future
phase touching a specific module should re-read it in full before modifying it.

## 3. Legacy ORCA → ORNEUR audit

| Legacy element | Classification | Rationale |
|---|---|---|
| `orca` Python package name / `ORCA_HOME` env var | INTERNAL_COMPATIBILITY_ACCEPTABLE | Naming only, no behavioral risk; already has an explicit deprecation path (`ORCA_HOME` deprecation warning present, `ORNEUR_HOME` preferred) |
| `orca-nano`/`orca-core`/`orca-ultra` legacy Ollama checkpoint names | INTERNAL_COMPATIBILITY_ACCEPTABLE | Explicitly modeled as `legacy_ollama_names` on `ModelSpec` — not silently aliased, not presented as canonical |
| `orca/variants/` (core.py, nano.py, ultra.py) | SAFE_TO_DEPRECATE | 0 test references; fully superseded by `orca/registry` + `orca/gateway`; "god-mode"/"apex orchestrator" framing conflicts with Phase 16's authority-boundary language |
| `orca/brain/agent.py` ("god-mode reasoning"), `orca/brain/providers.py` framing | SHOULD_MIGRATE_DURING_NATIVE_PHASES | Naming/framing predates the Gateway/Cognitive split; `SemanticMemory` inside `orca/brain/memory.py` is still load-bearing and must not be deleted, only re-homed/renamed later |
| `ORCA_OPENAI_API_KEY`, `ORCA_ALLOW_UNSIGNED_WEBHOOKS` env vars | INTERNAL_COMPATIBILITY_ACCEPTABLE | Already deprecated with warnings, `ORNEUR_*` fallback exists |
| `orca/agent/court_hook.py` name "Court" pre-dating the real Cognitive Court | INTERNAL_COMPATIBILITY_ACCEPTABLE (already resolved) | Phase 15's own implementation plan already flagged this as "a narrow existing hook" prior to the Phase 15.9 real Court build; current `court_hook.py` correctly delegates to `orca/deliberation/court.py` |
| No legacy element found requiring MUST_REMOVE_BEFORE_PHASE17 or flagged ARCHITECTURAL_CONFLICT | — | No code was found where legacy naming carries legacy *authority-bypassing* behavior |

## 4. Model artifact truth audit (Genesis / Novus / Aeternum)

No model weights were moved, deleted, or altered during this audit.

- **Genesis**: canonical V1 target is `unsloth/Qwen2.5-3B-Instruct` (`model_spec.py`). No canonical
  checkpoint trained. The historical `orca-nano`/`orca-nano-v4`/`orca-nano-v7` Ollama artifacts are
  forensically confirmed **Qwen2.5-7B-class** (7.6B params) — legacy, marked RETIRED in the local
  registry, explicitly documented as NOT the canonical 3B target. `LifecycleState` for these: RETIRED.
- **Novus**: canonical target `unsloth/Meta-Llama-3.1-8B-Instruct`. A real ~8B Llama fine-tuned
  checkpoint (`orca-core-combined-v2`) exists locally, marked `EXPERIMENTAL` lifecycle. Per
  `ModelRegistry.promote()`'s enforced gate, promotion to PRODUCTION requires a `PROMOTABLE`
  `EvaluationReport` — none is on record for this checkpoint, so it remains **NOT eligible for
  promotion** (there is no literal `NOT_PROMOTABLE` lifecycle value; the correct honest statement is
  "EXPERIMENTAL, no PROMOTABLE evaluation on record").
- **Aeternum**: `reg.mark_family_absent("aeternum")` was called deliberately at seed time — "by
  design, not an oversight." No checkpoint, canonical or legacy, exists under any name.
  `ModelRegistry.lookup_production("aeternum")` returns `None` by construction. **Corrected this
  closure**: the family's `base_model` is now `None`
  (`base_model_status="UNSELECTED_PROVISIONAL"` in `orca/registry/model_spec.py`) — the earlier
  Phase 16 pass incorrectly carried the historical `unsloth/Meta-Llama-3.1-70B-Instruct` literal as
  if it were the current canonical training target. That plan is legacy/stale; no final base model
  has been selected, and `~14B` is recorded only as a non-binding provisional research hypothesis
  (`ModelSpec.provisional_parameter_hypothesis`). `require_base_model("aeternum")` now raises
  `ValueError` rather than resolving to any base model, selected or stale — verified by
  `tests/test_registry_model_spec.py::test_require_base_model_fails_closed_for_aeternum`.

## 5. 9-layer architecture map (L0–L8) — CORRECTED, see canonical architecture doc

**Correction notice**: this section originally substituted its own 9-layer breakdown instead of
the owner's required canonical L0–L8 map, and its authority-boundary claim was worded more
strongly than the cited evidence proved (import-absence grep alone, not the actual Phase 15 tests
that prove Court-is-not-authority / stale-authority-cannot-execute / state-machine-cannot-be-
bypassed). Both are corrected in `PHASE16_CANONICAL_ARCHITECTURE.md`'s "9-layer map" and
"Dependency-graph and authority-boundary evidence" sections — see that document for the current,
owner-canonical L0–L8 map (Human Sovereignty / Constitution-Identity-Authority / Mission-Operation-
Execution-Governance / Evidence-Verification-Production-Proof / Cognitive Protocol / Intelligence
Router / Model Runtime / Learning Plane / Evaluation-Qualification-Promotion) and the narrowed,
test-cited authority-boundary evidence. Not duplicated here to avoid two documents drifting apart.

## 6. Conceptual (non-implemented) stable contracts — Section 11

Defined at concept level only (no code changes in this section): CognitiveRequest/Result,
Epistemic metadata (assertion vs measured-fact vs policy-fact vs external-evidence vs unknown),
Model identity/generation/capability, Routing request/decision, Escalation request, Evidence
reference, Checkpoint/artifact reference, Training candidate, Promotion decision. See
`PHASE16_CANONICAL_ARCHITECTURE.md` §Contracts for the frozen shapes, reconciled against the real
`orca/cognitive/contracts.py`, `orca/registry/*`, and `orca/society/contracts.py` types already in
the repository (this is inventory-and-validate, not blank-slate design — see Finding below).

**Finding**: much of what §11/§12 asked to be "designed" already has substantial real
implementation. The honest gap is narrower than the prompt assumed: `LifecycleState` uses
`EXPERIMENTAL/TRAINED/EVALUATING/CANDIDATE/APPROVED/PRODUCTION/REJECTED/RETIRED`, not the prompt's
assumed `EXPERIMENTAL/CANDIDATE/QUALIFIED/PROMOTED/RETIRED/NOT_PROMOTABLE`. `NOT_PROMOTABLE` exists
only as an `EvaluationReport.pass_fail_status` value, never a lifecycle state. This is documented,
not silently reconciled by renaming existing enums (renaming a used enum is out of Phase 16's
allowed-change list in §22 unless proven necessary for Phase 17 safety — it is not).

## 7. Routing / inference-training-plane / external-provider / memory / society boundaries

- **Routing invariants (§13)**: verified in code — `router.py`'s `RoutingReason` enum
  (`ARTIFACT_UNAVAILABLE`, `NOVUS_REJECTED_LIFECYCLE`, `AETERNUM_ABSENT`, `LIFECYCLE_DISQUALIFIED`,
  `CONTEXT_REQUIREMENT_UNMET`, `ENTITLEMENT_LIMIT`, `DEPLOYMENT_UNHEALTHY`, `EXCLUDED_BY_CALLER`,
  `NO_ELIGIBLE_CANDIDATE`, `SELECTED`, `LEGACY_GENESIS_SELECTED_FOR_FAST_ROLE`,
  `VERIFICATION_QUALITY_PREFERRED`, `LOW_LATENCY_PREFERENCE`) shows selection is reason-coded and
  auditable, not silent. No code path lets a model self-select or self-promote.
- **Inference vs training/learning plane (§14)**: `orca/gateway` (inference-only, calls Ollama or
  frontier APIs) is structurally separate from `orca/train` + `orca/learning` (training/candidate
  generation) — no import from `orca/gateway` into `orca/train`/`orca/learning` found.
- **External-provider classification (§15)**: `orca/gateway/frontier_runtime.py` ("Frontier API
  passthrough runtime (OpenAI/Anthropic)") is the correct, already-isolated `EXTERNAL_PROVIDER`
  boundary — distinct from `ollama_runtime.py` which serves native ORNEUR-controlled artifacts.
- **Memory/learning boundary (§16)**: TWO distinct memory systems exist — `orca/brain/memory.py`'s
  `SemanticMemory` (legacy-era, diskcache-backed, process-wide — the source of the Phase 15
  `all_sessions_summary` shared-state incident fixed in 15.15) and `orca/memory/` (Phase 5's Memory
  Continuum: typed candidates, `firewall.py`, `significance.py`, per-agent scoping via
  `agent_memory.py`). Phase 26's Outcome Memory **must build on `orca/memory/`**, not
  `orca/brain/memory.py` — the latter's process-wide shared-key pattern is exactly the defect class
  that caused the 15.15 incident and must not be inherited.
- **Society/Court audit (§17)**: `orca/deliberation/court.py`'s `CourtVerdictState` maps directly
  to the four/five required verdict values; verdicts are mapped to string labels
  (`COURT_ACCEPTED`, `COURT_REJECTED`, etc.) for downstream consumption but **never** to an
  authorization/execution flag in the same module — `orca/agent/policy.py` remains the sole
  authorizer, confirmed by the absence of any `orca.deliberation` import inside `policy.py`'s
  authorization path. No blurring of Court-ACCEPT-as-authority was found in this audit pass.

## 8. Threat model, invariants, dependency graph, architecture options

See `PHASE16_THREAT_MODEL.md` for the full ~30-item threat table and
`PHASE16_CANONICAL_ARCHITECTURE.md` for the 9-layer diagram, dependency-graph evidence, testable
invariants (INV-NATIVE-*, INV-BOUNDARY-*, INV-PHASE-*), and the A/B/C architecture-option
comparison (Option B — a thin `orneur.intelligence` boundary adapting existing `orca.*` modules —
is selected; see that document for the full trade-off table).

## 9. Baseline test numbers (recorded before any Phase 16 edits)

- Collection count (via project `.venv`, matching CI's install): **2574 tests collected**, 0
  collection errors — unchanged from Phase 15.15's final number, confirmed freshly this phase
  (not assumed).
- **Environment hazard found and documented, not silently worked around**: this development
  machine's `PATH` resolves a global Homebrew `pytest`/`python3.14` ahead of the project's
  `.venv`, so running `scripts/ci/run_deterministic_tests.sh` directly on this machine produces 38
  false collection errors (`ImportError: orca.serve...` etc.) — this is a **local-shell PATH
  artifact**, not a real regression and not a CI risk (CI's `uv pip install --system` puts the
  right interpreter first). Confirmed via `which pytest` → `/opt/homebrew/bin/pytest`. Full
  deterministic regression for this baseline was instead run with `.venv/bin/python -m pytest`
  directly; result recorded in `PHASE16_EVIDENCE.md`.
