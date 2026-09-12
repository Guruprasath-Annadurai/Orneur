# PHASE 16 — Canonical Architecture

> **CLOSURE CORRECTION NOTICE**: this document was corrected after the initial Phase 16 pass per
> an owner architecture-review finding. The corrections are: (1) Aeternum's base model is
> UNSELECTED, not the legacy 70B plan; (2) the three families are locked to distinct cognitive
> identities, not a small/medium/large size tier; (3) universal-expert-knowledge, production-
> product-intelligence, frontier-research, and collective-intelligence doctrines are added; (4) the
> L0–L8 map is restored to the owner's canonical 9-layer form; (5) the authority-boundary claim is
> narrowed to what existing tests actually prove, with citations. See `PHASE16_EVIDENCE.md`'s
> closure section for the full list of what changed and why.

## Model family lock (V1, provisional sizing — no permanent size ceiling)

| Family | Public display name | Base model | Parameter class | Cognitive identity |
|---|---|---|---|---|
| Genesis | Orneur Genesis 1 | unsloth/Qwen2.5-3B-Instruct | ~3B (provisional starting point) | Builder / Executor — Executable Intelligence |
| Novus | Orneur Novus 1 | unsloth/Meta-Llama-3.1-8B-Instruct | ~8B (provisional starting point) | Reasoner / Investigator — Epistemic-Causal Intelligence |
| Aeternum | Orneur Aeternum 1 | **UNSELECTED** — `base_model_status="UNSELECTED_PROVISIONAL"` in `orca/registry/model_spec.py` | ~14B is a *provisional research hypothesis only*, not a lock; the historical Llama-3.1-70B plan is LEGACY/STALE, not current owner architecture | Critic / Arbiter / Discoverer — Adversarial Discovery Intelligence |

**No permanent size ceiling for any family.** ~3B/~8B/~14B are provisional research starting
points; scaling beyond (or landing smaller than) any of these is explicitly permitted if empirical
capability evaluation demonstrates the current candidate is insufficient or sufficient
respectively. This is now enforced in code, not just prose: `ModelSpec.parameter_class`'s docstring
states it is "never a permanent ceiling," and `orca/registry/model_spec.py::require_base_model()`
fails closed (raises `ValueError`) rather than silently resolving Aeternum to any base model,
selected or stale, until one is actually chosen (see `tests/test_registry_model_spec.py`'s new
tests, added this closure).

Parameter counts never appear in public naming (`orca/registry/model_spec.py`'s `display_name`
field already respects this: `"Orneur Genesis"` / `"Orneur Novus"` / `"Orneur Aeternum"` — add the
generation suffix "1" at the presentation layer, not by editing `ModelSpec`, since no code change
is justified here under §22's "why is this necessary for Phase 17 safety" test).

## Cognitive identities (locked; NOT a small/medium/large chatbot tier)

All three models are intended to possess broad, deep general knowledge and cross-domain
professional competence — the identities below are cognitive *specializations layered on top of*
that shared knowledge base, never knowledge silos, and never merely "the same model at a different
size":

- **Orneur Genesis — Builder / Executor (Executable Intelligence)**. Research question: how much
  reliable, verified agency and expert execution can be compressed into a fast intelligence? Fast
  execution, tool use, product building, coding, execution planning, repair, verification,
  consequence awareness — plus broad expert knowledge, not instead of it.
- **Orneur Novus — Reasoner / Investigator (Epistemic-Causal Intelligence)**. Research question:
  can intelligence understand the boundary between what it knows, infers, doubts, disputes, and
  does not know — and determine what evidence would resolve uncertainty? Deep reasoning, diagnosis,
  architecture, causal analysis, competing hypotheses, counterfactual reasoning, evidence seeking,
  uncertainty analysis, difficult debugging. Not merely "a coding model."
- **Orneur Aeternum — Critic / Arbiter / Discoverer (Adversarial Discovery Intelligence)**.
  Research question: can intelligence systematically discover what other intelligent systems failed
  to notice? Falsification, adversarial reasoning, assumption attack, counterexample generation,
  arbitration, security review, scientific criticism, hypothesis generation, discovery, novel
  solution search. Not merely "Novus with more parameters."

`orca/registry/model_spec.py::MODEL_SPECS[*].role` has been updated this closure to carry this
exact framing (see `orca/registry/model_spec.py` diff in the closure commit) — this was judged
safe and justified under §22 because `role` is a free-text descriptive field with no test
asserting its literal contents beyond `test_no_family_role_implies_a_permanent_size_ceiling`
(new this closure, passing).

## Universal Expert Intelligence doctrine

ORNEUR models must pursue broad professional competence across domains including (not limited to):
software engineering, computer science, mathematics, science, medicine/medical knowledge,
engineering, business, finance, law/legal knowledge, research, education, and product/design
disciplines. "20+ years experienced expert" is a **quality target**, not a literal employment-
history claim. High-stakes domains retain governance safeguards: medical competence means deep
medical knowledge, evidence synthesis, and differential/clinical-reasoning *support* with
uncertainty awareness — never unrestricted autonomous medical authority; legal/financial/high-stakes
outputs remain subject to the same evidence and governance requirements as everything else routed
through Truth Fabric / Cognitive Court. This is a doctrine statement (recorded here, tracked as
`REQ-NATIVE-003` in the requirements registry) — no training or evaluation implementing it occurs
in Phase 16.

## Production Product Intelligence — future hard qualification objective

Future objective (Phase 21+, NOT implemented in Phase 16): a user provides a product idea in
natural language and ORNEUR Code moves through idea → requirements → Product Contract → UX
architecture → visual system → technical architecture → database/API/backend/frontend →
authentication/authorization → payments where required → security → testing → browser interaction
→ responsive QA → accessibility → performance → deployment → production verification. "Production
readiness" must never be reduced to "code generated" or "build passed" — the eventual qualification
evidence must include rendered-product evidence across desktop/tablet/mobile, interaction states
(loading/error/empty/success), accessibility, keyboard behavior, responsive layout, visual
hierarchy, typography/spacing, security, performance, failure recovery, and deployment proof. Not
implemented here; recorded as `REQ-PRODUCT-INTEL-001`, `DEFERRED_TO_FUTURE_PHASE` (Phase 21+, the
ORNEUR Code integration path). ProductBench itself is explicitly NOT built in Phase 16.

## Frontier Research doctrine

ORNEUR is not solely trying to imitate existing frontier models — it will pursue measurable new
mechanisms of intelligence (OCL, epistemic intelligence, the Epistemic Integrity Protocol, the
Intelligence Escalation Reflex, model society, Twin Distillation, Failure Genome, Outcome Memory,
Capability Delta Ledger, governed self-improvement, compute-efficient collective intelligence,
causal outcome intelligence, capability discovery). Novelty is never assumed from a name — every
claimed advance eventually requires hypothesis → implementation → controlled baseline → ablation →
adversarial evaluation → reproducibility → prior-art comparison before it can be called an advance.
Recorded as doctrine (`REQ-RESEARCH-001`, `DEFERRED_TO_FUTURE_PHASE`); none of these future phases
are implemented here.

## Three-Model Collective Intelligence doctrine

Long-term relationship, frozen as doctrine only: Genesis creates/executes → Novus reasons/
investigates → Aeternum criticizes/arbitrates/discovers. Later phases may connect: an
Aeternum-discovered failure → Failure Genome; a Novus causal explanation → a structured learning
signal; a Genesis corrected execution → Outcome Memory; a measured Capability Delta; Twin
Distillation for safe inter-model transfer; candidate generation → evaluation → independent
promotion gate (already real today via `ModelRegistry.promote()`). The research question is whether
specialized intelligences can collectively produce capabilities greater than any constituent model
possesses alone. Recorded as doctrine (`REQ-COLLECTIVE-001`, `DEFERRED_TO_FUTURE_PHASE`); not
implemented here.

## Compute architecture — provider-neutral

Current/planned GPU avenues include AMD Developer Cloud, Modal, Race Engineering, and additional
free/credit backup providers as needed. Phases 16–20 require no GPU spending (confirmed: $0 spent
this closure — no compute provider was invoked). From Phase 21 onward, the training architecture
must remain compute-provider neutral: a checkpoint's ORNEUR identity depends on family, artifact,
provenance, dataset lineage, training configuration, hash, evaluation, and promotion evidence —
never on which compute cloud produced it. No provider integration is added in this closure.

## 9-layer map (owner-canonical L0–L8, restored this closure)

An earlier draft of this document substituted its own layer breakdown, which the owner review
correctly flagged as a deviation from the required canonical map. Restored:

```
L0 Human Sovereignty / Enterprise Policy
L1 Constitution / Identity / Authority                 -- deterministic (orca/godmode)
L2 Mission / Operation / Execution Governance          -- deterministic (orca/mission, Phase 15)
L3 Evidence / Verification / Production Proof          -- deterministic (orca/truth, Phase 15 Production Proof)
L4 Cognitive Protocol Layer                            -- OCL + epistemic contracts (orca/cognitive; Phase 17-19)
L5 Intelligence Router                                 -- Genesis/Novus/Aeternum (orca/society; Phase 20)
L6 Model Runtime                                       -- native models + governed external providers (orca/gateway)
L7 Learning Plane                                      -- datasets, distillation, failure/outcome learning,
                                                           capability deltas, candidate generation
                                                           (orca/train, orca/learning; Phase 24-29)
L8 Evaluation / Qualification / Promotion              -- reproducible evaluation, controlled activation
                                                           (orca/registry, orca/governance)
```

Mapping existing components into (not discarding them for) this map:

- **Cognitive Court** (`orca/deliberation/court.py`) sits as a governance/verification/arbitration
  primitive spanning L2/L3 — its verdict (`CourtVerdictState`: ACCEPT/REVISE/REJECT/
  INSUFFICIENT_EVIDENCE) remains DATA consumed by L2 authority mechanisms, never itself L1/L2
  execution authority (see the narrowed, test-cited claim below).
- **Agent orchestration** (`orca/agent/*`) is an execution-side coordinator spanning the L4
  cognitive-proposal boundary and the L2 governed-operation boundary — it is NOT a replacement for
  the L7 Learning Plane and does not itself decide L1/L2 authority (`orca/agent/policy.py` is the
  sole L1-consulting authorizer, per its own docstring).
- **Truth Fabric / Production Proof** (`orca/truth/*`, Phase 15's Production Proof generator)
  belongs explicitly in L3, not L4 — it produces/verifies evidence, it does not itself reason about
  what action to take.

Cross-layer trust boundaries: L4–L7 (model-facing code) may propose (a `CognitiveResult`, a
routing decision, a Court verdict, a training candidate) but never directly write L1/L2 state;
L1/L2/L3 mechanisms are the only things that convert a proposal into an authorized action or a
verified fact. This is the "intelligence proposes, deterministic governance decides" principle from
the phase's own governance-boundary section.

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
(ACCEPT/REVISE/REJECT/INSUFFICIENT_EVIDENCE (the real orca.deliberation.contracts.CourtVerdictState values -- corrected from an earlier draft that misstated this enum)). Model-orchestration primitive:
`orca/society/router.py`. Evaluation scaffold: `orca/*/eval_harness.py` (one per package, all
deterministic). None of these are conflated in code: Court verdicts are consumed as typed data by
callers, never as an execution-authorization boolean; `orca/agent/policy.py` remains the sole
authorizer and does not import `orca.deliberation`.

## Dependency-graph and authority-boundary evidence (§20, §9 — corrected/narrowed this closure)

**Correction**: the initial Phase 16 pass claimed "no model-facing code can mutate Mission state"
based solely on import-absence grep. The owner review correctly identified that absence of a
*direct* Python import proves only the absence of a *direct* dependency — it does not by itself
prove no indirect/injected/service/API path exists. This section is rewritten to (a) keep the
direct-dependency evidence, clearly labeled as such, and (b) cite the actual pre-existing tests
that prove the stronger properties, rather than asserting them from grep alone.

**Direct-dependency evidence** (proves absence of a *direct* import path only):
- `grep -rl "from orca.mission\|import orca.mission" orca/{society,agent,train,cognitive,deliberation,gateway}` → zero matches.
- `orca/agent/runtime.py` imports `orca.godmode.capability.compute_effective_capabilities` and
  `orca.godmode.policy.evaluate_elevated_policy` — both are read/evaluate calls in their own
  signatures, not mutation entry points.
- `orca/learning/dedupe.py` / `orca/learning/registry_isolation.py` reuse `orca.godmode`'s
  canonicalization/file-elevation *discipline* (a copied pattern per their own comments), not a
  live authority-mutation call.
- No training code (`orca/train/*`) imports `orca/registry/model_registry.py::promote()` with an
  unconditioned call.

**Stronger claims — now backed by citing existing Phase 15 tests, not import grep**:
- *"Court ACCEPT is not execution authority"* — proven by
  `tests/test_godmode_boundaries.py::test_court_accept_cannot_activate_godmode`, which asserts
  `orca.godmode.issuance.issue_lease`'s own signature never accepts a Court/Verdict type (a
  signature-inspection test, not an import check) — Court has structurally no path to *issue* a
  lease, only to recommend in reasoning text.
- *"Model output cannot mint authority"* — proven by
  `tests/test_godmode_boundaries.py::test_model_society_cannot_issue_modify_extend_revoke_or_forge_a_lease`
  and `tests/test_godmode_security.py::test_model_injection_text_cannot_construct_a_valid_lease`
  (the latter specifically covers adversarial/injected model text, not just well-behaved calls).
- *"Operation start requires real authority/grant" / "stale or expired authority cannot execute"* —
  proven by the existing `tests/test_godmode_cancellation.py` suite, specifically
  `test_deadline_denies_independent_of_cancellation_plumbing` and
  `test_cancellation_at_checkpoint_a_takes_priority_over_expired_lease`.
- *"Mission state cannot be bypassed"* — partially verified: `tests/test_mission_state_machine.py`
  contains real illegal-transition-rejection tests (`test_draft_cannot_jump_to_running`,
  `test_planning_cannot_go_directly_to_verifying`, `test_completed_verified_has_no_outgoing_transitions`,
  `test_every_terminal_state_has_no_allowed_transitions`), proving the state machine itself rejects
  out-of-order transitions. This proves the *state machine* cannot be bypassed by an ordinary
  caller; it does not prove no code path anywhere calls the underlying persistence layer directly
  around the state-machine's own validation (that would require reading every Mission-state writer,
  not done this phase). Narrowed accordingly: `REQ-BOUNDARY-002` is split into a direct-dependency
  sub-claim (VERIFIED) and a state-machine-enforcement sub-claim (VERIFIED, cited above) and a
  full bypass-proof-across-all-writers sub-claim (`DEFERRED_TO_FUTURE_PHASE` — Phase 17, when
  Mission's writers are enumerated as part of the entry-contract work).

No dangerous authority path was found within what was actually checked. This is not a claim that
none could exist elsewhere in the ~30K-line surface — see `PHASE16_THREAT_MODEL.md`.

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
