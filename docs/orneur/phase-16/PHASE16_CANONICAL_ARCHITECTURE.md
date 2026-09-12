# PHASE 16 — Canonical Architecture

## Model family lock (V1, provisional sizing)

| Family | Public display name | Base model | Parameter class | Role |
|---|---|---|---|---|
| Genesis | Orneur Genesis 1 | unsloth/Qwen2.5-3B-Instruct | ~3B | fast cognition |
| Novus | Orneur Novus 1 | unsloth/Meta-Llama-3.1-8B-Instruct | ~8B | operational cognition |
| Aeternum | Orneur Aeternum 1 | unsloth/Meta-Llama-3.1-70B-Instruct | ~70B (planned target, no run exists) | deep cognition |

Parameter counts never appear in public naming (`orca/registry/model_spec.py`'s `display_name`
field already respects this: `"Orneur Genesis"` / `"Orneur Novus"` / `"Orneur Aeternum"` — add the
generation suffix "1" at the presentation layer, not by editing `ModelSpec`, since no code change
is justified here under §22's "why is this necessary for Phase 17 safety" test).

## 9-layer map

See `PHASE16_NATIVE_INTELLIGENCE_BASELINE_AUDIT.md` §5 for the full L0–L8 diagram and verified
edges. Reproduced principle:

> Authority MUST flow downward only through deterministic authority mechanisms (L1 `orca/godmode`,
> L2 `orca/mission`, L3 Court verdicts consumed only as data). Model output (L4–L7) must never
> itself become authority. Verified by absence of any `orca.mission` import inside
> `orca/{agent,society,train,cognitive,deliberation,gateway}`, and by `orca/agent/policy.py`
> importing no `orca.deliberation` symbol.

## Model Identity Contract (reconciled with existing code, §12)

Actual `LifecycleState` (from `orca/registry/model_spec.py`, NOT redefined here):
`EXPERIMENTAL → TRAINED → EVALUATING → CANDIDATE → APPROVED → PRODUCTION`, with `REJECTED` and
`RETIRED` as terminal/exit states. `PromotionDenied` is raised by `ModelRegistry.promote()`, not a
lifecycle value.

Gap vs the Phase 16 prompt's assumed 6-state vocabulary (`EXPERIMENTAL|CANDIDATE|QUALIFIED|
PROMOTED|RETIRED|NOT_PROMOTABLE`): the real system has finer-grained states (`TRAINED`,
`EVALUATING`, `APPROVED` are additional) and calls the final state `PRODUCTION` rather than
`PROMOTED`. **Decision**: do NOT rename the existing, tested, working `LifecycleState` enum to
match the prompt's assumed vocabulary — no Phase-17-safety justification exists for that rename
(§22 test), and renaming a state machine 24 test files depend on is exactly the kind of
destructive, unjustified churn §21/§22 warn against. Instead, this document freezes the mapping:

| Prompt's assumed term | Real `LifecycleState` equivalent |
|---|---|
| EXPERIMENTAL | `EXPERIMENTAL` |
| CANDIDATE | `CANDIDATE` (also see `TRAINED`, `EVALUATING` as intermediate real states) |
| QUALIFIED | closest real state is `APPROVED` |
| PROMOTED | `PRODUCTION` |
| RETIRED | `RETIRED` |
| NOT_PROMOTABLE | not a lifecycle state — it is `EvaluationReport.pass_fail_status == "NOT_PROMOTABLE"`, consumed by `ModelRegistry.promote()` as a gate input |

Model Identity fields already real and sufficient: `family`, `checkpoint_id`, `base_model`,
`legacy_ollama_names`/`legacy_note`, `lifecycle_state`, `artifact_checksum`, `validation_state`,
`availability` (a genuinely separate axis from lifecycle — see `ArtifactAvailability` docstring).
No new Model Identity type is created in Phase 16; this document is the audit record of what
exists.

## Routing architecture invariants (design boundary only, §13)

- Escalation direction is Genesis → Novus → Aeternum only (never reversed by policy).
- Router must not use parameter count as sole competence proxy, must not auto-prefer Aeternum,
  must not grant models authority, must not silently downgrade high-risk tasks, must not bypass
  policy, must not self-promote weights, must not fabricate availability for a missing checkpoint.
- Verified against real code: `RoutingReason.ARTIFACT_UNAVAILABLE`/`AETERNUM_ABSENT` exist
  specifically to make missing-checkpoint cases explicit rather than silently substituted.
- No Phase 20 routing implementation changes are made in Phase 16.

## Inference-plane vs training/learning-plane separation (§14)

Inference plane: `orca/gateway/*` (Ollama + frontier passthrough), consumed by `orca/society`,
`orca/agent`, `orca/cognitive`. Training/learning plane: `orca/train/*`, `orca/learning/*`,
`orca/registry/training_run.py`+`dataset_manifest.py`. No import from the inference plane into the
training plane exists (verified by grep); the only sanctioned bridge is
`orca/registry/model_registry.py`, which both planes read/write through the single `promote()`
gate.

## External-provider classification (§15)

`EXTERNAL_PROVIDER` = anything served via `orca/gateway/frontier_runtime.py` (OpenAI/Anthropic).
`ORNEUR_NATIVE_MODEL` = anything with a `ModelSpec` entry + a real ORNEUR-controlled artifact chain
through `orca/registry/checkpoint.py` (checksum + lineage_parent). Native identity requires the
artifact chain; a frontier API model can never be classified as Genesis/Novus/Aeternum regardless
of naming.

## Memory/learning boundary (§16)

Two systems, not one:
- `orca/brain/memory.py::SemanticMemory` — legacy-era, process-wide `diskcache` backing, the
  source of the Phase 15 `all_sessions_summary` shared-state defect (fixed in 15.15 by scoping the
  test, not the production code — the underlying shared-key architecture is still live).
- `orca/memory/*` (Phase 5 Memory Continuum) — typed candidate pipeline, `firewall.py` gating what
  reaches output, `agent_memory.py` per-agent scoping, `significance.py` filtering.

**Binding rule for Phase 26 (Outcome Memory)**: MUST build on `orca/memory/*`'s typed,
firewall-gated, scoped pattern. MUST NOT introduce another global/shared cache key of the
`SemanticMemory` kind. This document does not implement Outcome Memory — it fixes the boundary
Phase 26 must respect.

## Society/Court audit (§17)

Governance primitive: `orca/deliberation/court.py`'s `CourtVerdictState`
(ACCEPT/REJECT/NEED_MORE_EVIDENCE/ESCALATE/HUMAN_APPROVAL_REQUIRED). Model-orchestration primitive:
`orca/society/router.py`. Evaluation scaffold: `orca/*/eval_harness.py` (one per package, all
deterministic). None of these are conflated in code: Court verdicts are consumed as typed data by
callers, never as an execution-authorization boolean; `orca/agent/policy.py` remains the sole
authorizer and does not import `orca.deliberation`.

## Dependency-graph evidence (§20)

Checked directly (not by intuition):
- `grep -rl "from orca.mission\|import orca.mission" orca/{society,agent,train,cognitive,deliberation,gateway}` → **zero matches**. No model/routing/agent/training code can mutate Mission state.
- `orca/agent/runtime.py` imports `orca.godmode.capability.compute_effective_capabilities` and
  `orca.godmode.policy.evaluate_elevated_policy` — both are **read/evaluate** calls, not mutation
  entry points, matching the "propose vs decide" boundary.
- `orca/learning/dedupe.py` and `orca/learning/registry_isolation.py` reuse `orca.godmode`'s
  canonicalization/file-elevation *discipline* (copied pattern, referenced in comments), not live
  authority mutation.
- No training code (`orca/train/*`) imports `orca/registry/model_registry.py`'s `promote()`
  directly with an unconditioned call — `promote()` itself is the enforcement point and always
  requires a `PROMOTABLE` evaluation report.

No dangerous authority path was found in this pass. This is not a claim that none could exist
elsewhere in the ~30K-line surface — see `PHASE16_THREAT_MODEL.md` for what remains unverified.

## Testable architectural invariants (§19)

- `INV-NATIVE-001`: No module under `orca/{agent,society,train,cognitive,deliberation,gateway}`
  imports `orca.mission` (a dependency-boundary test, not a constant assertion).
- `INV-NATIVE-002`: `orca/agent/policy.py` does not import `orca.deliberation` (Court output stays
  data, never becomes an authorization call site).
- `INV-BOUNDARY-001`: `ModelRegistry.promote()` raises `PromotionDenied` when
  `evaluation_report.pass_fail_status != "PROMOTABLE"` (already covered by existing registry
  tests — verified present, not newly written, since it is an existing enforced behavior).
- `INV-PHASE-001`: no file under `orca/` references Phase 17+ concept names (`Twin Distillation`
  implementation, `Failure Genome` implementation, `Outcome Memory` implementation, `Capability
  Delta` implementation) as executable code — only as docstring/comment forward-references.

`INV-NATIVE-001` and `INV-NATIVE-002` are implemented as real dependency-boundary tests in Phase 16
(see `tests/test_phase16_architecture_invariants.py`, added under §22/§23's allowed-change list).

## Architecture option comparison (§21)

| | A: retrofit in place | B: `orneur.intelligence` adapter boundary | C: full migration/rename now |
|---|---|---|---|
| Regression risk | Low | Low | High |
| Coupling | Unchanged (still tight to `orca.*`) | Reduced at the boundary only | Fully decoupled, but touches ~30K lines |
| Clarity | Low (legacy naming persists) | Medium — new callers see clean names | High, but at high short-term cost |
| Migration cost | None now, compounds later | Small (adapter functions only) | Very high, out of Phase 16's cost-control budget (§28) |
| Testability | Unchanged | Adapter itself is easily tested | High test churn risk |
| Phase 17 suitability | Workable but leaves legacy framing (`orca/variants`, `orca/brain/agent.py`'s "god-mode") visible to new code | Good — Phase 17 code imports `orneur.intelligence`, never raw legacy names | Best long-term, wrong timing |
| Backward compatibility | Full | Full (adapter wraps, doesn't replace) | Broken until migration completes |
| Future model-family support | OK | Good — identity contract already centralized in `orca/registry` | OK |

**Decision: Option B.** No `orneur.intelligence` adapter package is created in Phase 16 itself
(creating it without a Phase 17 consumer would be scope creep beyond §22's allowed changes) — this
document records the selection so Phase 17 can create it as its first real consumer.
