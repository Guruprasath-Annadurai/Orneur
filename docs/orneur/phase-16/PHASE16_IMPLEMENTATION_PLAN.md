# PHASE 16 — Implementation Plan

## Scope actually implemented (per §22's allow-list)

1. **Architecture-invariant tests** (`tests/test_phase16_architecture_invariants.py`, 2 tests):
   `INV-NATIVE-001` (no model-facing package imports `orca.mission`) and `INV-NATIVE-002`
   (`orca/agent/policy.py` does not import `orca.deliberation`). Both are real dependency-boundary
   tests over actual source via `ast`, not constant assertions. Verified to genuinely detect a
   synthetic violation (see PHASE16_EVIDENCE.md).
2. **Six required documents** under `docs/orneur/phase-16/`.
3. **No production `orca/*` code was modified.** No model identity types were added/renamed, no
   registry code touched, no router code touched. This reflects the audit's own finding: the
   requested contracts (Model Identity, Checkpoint/Artifact reference, Training candidate,
   Promotion decision) already exist with sufficient real implementation in `orca/registry/*`, and
   no gap was found that requires new code to make Phase 17 architecturally safe (the §22 test).

## What was explicitly NOT done (per absolute prohibitions)

No OCL semantics, no epistemic reasoning implementation, no new escalation algorithm, no training
run, no router replacement, no Twin Distillation, no Outcome Memory, no automatic
self-improvement, no LoRA/QLoRA, no GPU job, no large dataset download, no paid API campaign, no
new production DB migration, no model weight modification, no candidate promotion.

## Why each change was necessary for Phase 17 safety (§22 justification)

- The invariant tests exist because Phase 17 will build the OCL entry contract directly on top of
  `orca/cognitive/contracts.py` and the routing/authority boundary described in this audit — a
  regression in either boundary (model-facing code touching Mission, or Court verdicts becoming an
  implicit authorization path) would make Phase 17's OCL layer unsafe by construction. Encoding
  these as tests now means Phase 17 inherits a protected boundary rather than a documented-but-
  unenforced one.
- The six documents exist because §24 requires them and because Phase 17 needs a frozen, evidence-
  backed baseline (model identity vocabulary gap, memory-boundary binding rule, threat model) to
  build against without re-deriving it.

## Phase 17 entry contract (frozen by this plan, §26)

Phase 17 MUST consume:
- `CognitiveRequest`/`CognitiveResult` envelopes conceptually aligned with the existing
  `orca/cognitive/contracts.py` types (not yet a formal OCL language — that is Phase 17's own job).
- Model identity via `orca/registry/model_spec.py`'s real `ModelSpec`/`LifecycleState`, using the
  mapping table in `PHASE16_CANONICAL_ARCHITECTURE.md` rather than a new vocabulary.
- A strict assertion vs measured-fact vs deterministic-policy-fact vs external-evidence vs
  uncertainty/unknown distinction in every envelope field — this is the concrete fix for Threat
  #15/#29 (model output mistaken for policy fact). Phase 17 must not ship its first working
  version of OCL without this distinction being enforceable in the type system, not just prose.
- Fail-closed semantics: an envelope with an unset/ambiguous authority field must be treated as
  "no authority", never defaulted to permissive.
- External vs native provider tagging on every model-identity reference (§15's classification),
  serialized so a frontier response can never be silently relabeled native.
- Versioning: envelope types must carry an explicit schema version field from their first Phase 17
  commit (this is a fail-closed-by-design requirement, not implemented in Phase 16 since no
  envelope code exists yet to version).
- Protecting tests: any Phase 17 PR touching these envelopes must also run
  `tests/test_phase16_architecture_invariants.py` (already collected by the normal suite; no
  special wiring needed since it's a standard pytest file).

Phase 16 explicitly does NOT define the OCL reasoning language itself — only this entry contract.

## Commits

Work is split into logical, "Phase 16:"-prefixed commits: (1) architecture-invariant tests, (2) the
six required documents. No Phase 15 commit is amended. No force-push. No merge to main.
