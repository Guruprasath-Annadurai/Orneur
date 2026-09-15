# Phase 18 Evidence Log

Recorded as work proceeded. Not rewritten to look cleaner after the
fact — genuine bugs found during TDD are documented as found.

## Baseline (before any Phase 18 code)

- Starting HEAD: `c8e733be02bb6927b14bf6463140db362e9c0385`, clean tree,
  branch `session-update-2026-08-25`.
- `tests/ocl/` baseline: 348 passed (gathered via an Explore agent read
  of the full OCL contract — enums, artifact/atom/relation shapes,
  evidence anchors, trust boundary, compiler entrypoints, canonical
  JSON/digest pattern, checkpoint identity, error hierarchy, diff
  pattern, observer pattern, `__init__.py` exports, typecheck/limits
  patterns, and `docs/orneur/phase-17/` doctrine).

## Architecture decisions made from the OCL contract read

- `EpistemicOverlay` is a wholly separate object from `CognitiveArtifact`/
  `CognitiveAtom`, bound by `source_artifact_id` + `source_artifact_digest`
  (an OCL `canonical.digest()` value) — never a field added to OCL's own
  schema. `resolver.py::assess_artifact()` recompiles the input through
  OCL's real `compile_artifact()` at the boundary rather than trusting an
  object merely typed `CognitiveArtifact`.
- `EpistemicResolutionTrustContext` mirrors OCL's `CompilationTrustContext`
  pattern exactly: a required, strictly-typed keyword argument to the
  resolver, checked via `isinstance()` (not membership-by-value) so a
  bare string can never pass as trusted.
- `ResolvedEvidence`/`VerificationFeasibilityRecord` are explicit,
  separately-typed parameters — never parsed from atom/artifact
  `metadata`. This is the structural mechanism (not a metadata
  blocklist) that makes model self-elevation impossible.

## Layer-by-layer implementation and gates

- **Layer 18.2** (enums + immutable contracts): `enums.py`, `errors.py`,
  `limits.py`, `typecheck.py`, `models.py` written. Smoke import test
  passed immediately. **GATE: PASS**.
- **Layer 18.3** (trust + evidence-resolution context): `trust.py`
  written; `test_epistemic_trust.py` (5 tests) passed on first run.
  **GATE: PASS**.
- **Layer 18.4/18.5/18.6** (direct assessment, graph derivation,
  contradiction/dispute, UNKNOWN/UNCERTAIN/UNVERIFIABLE edges):
  `graph.py` + `resolver.py` written together. `test_direct_assessment.py`
  (10 tests) passed on first run with zero fixes needed. **GATE: PASS**.
- **Layer 18.7** (canonical overlay + digest + idempotence):
  `canonical.py` written; `test_canonicalization.py` (5 tests) passed on
  first run. **GATE: PASS**.
- **Layer 18.8** (epistemic diff/transitions): `diff.py` written;
  `test_epistemic_diff.py` (7 tests, covering all 6 required transitions)
  passed on first run. **GATE: PASS**.
- **Layer 18.9** (adversarial + performance + compatibility closure):
  `test_self_elevation_attacks.py`, `test_inference_graph.py`,
  `test_unverifiable.py`, `test_overlay_binding.py`,
  `test_epistemic_performance.py`, `test_epistemic_architecture.py`
  written and run; two real bugs found and fixed (below). **GATE: PASS**.

## Failing-first reproductions (real bugs found during TDD, not
retrofitted)

1. **`test_circular_derived_from_with_no_evidence_root_stays_not_inferred`**
   (as originally written) failed with
   `orneur.intelligence.ocl.errors.InvalidRelationShape` instead of
   returning an overlay. Root cause: `DERIVED_FROM` is already in OCL's
   own `ACYCLIC_RELATION_KINDS` — a circular `DERIVED_FROM` graph cannot
   compile at all, so it never reaches Phase 18's resolver. This is a
   correct, stronger defense-in-depth outcome, not a Phase 18 defect.
   **Fix**: rewrote the test as
   `test_circular_derived_from_is_already_rejected_by_ocl_before_phase_18_sees_it`,
   asserting the OCL-level rejection directly, and documented the
   distinction from the `SUPPORTS`-cycle test (which OCL does allow to
   compile, and which Phase 18's own evidence-rooted BFS correctly
   refuses to bootstrap).
2. **`test_metadata_verified_true_is_ignored`** (as originally written)
   failed with `orneur.intelligence.ocl.errors.ForbiddenAuthorityConstruct`
   instead of returning an overlay. Root cause: `"verified"` is already
   one of OCL's own `FORBIDDEN_METADATA_KEYS` — the artifact fails to
   compile before Phase 18's resolver runs at all. **Fix**: rewrote the
   test as `test_metadata_verified_true_is_rejected_by_ocl_before_phase_18_sees_it`,
   asserting the OCL-level rejection, while the sibling tests for keys
   OCL does NOT reserve (`epistemic_state`, `confidence`) confirm Phase
   18's own independent metadata-blindness.

No other test required a fix on first run — the algorithm design
(worklist BFS seeded only from direct qualified roots; trust context as
a required, isinstance-checked, out-of-band parameter; resolution
records as explicit typed parameters never read from metadata) held up
against the full adversarial matrix without further correction.

## Targeted test results

```
tests/epistemic/ -- 79 passed, 0 failed
```

Breakdown: `test_direct_assessment.py` 10, `test_disputes.py` 6,
`test_epistemic_architecture.py` 2, `test_epistemic_diff.py` 7,
`test_epistemic_enums.py` 8, `test_epistemic_performance.py` 1,
`test_epistemic_trust.py` 5, `test_inference_graph.py` 8,
`test_overlay_binding.py` 9, `test_self_elevation_attacks.py` 11,
`test_unknown_uncertain.py` 3, `test_unverifiable.py` 4,
`test_canonicalization.py` 5.

## Regression results

- `tests/ocl/` (Phase 17): 348 passed, 0 failed — unchanged, no OCL
  source file modified.
- `test_phase16_architecture_invariants.py` +
  `test_phase16_canonical_training_identity.py` +
  `test_phase16_court_reconciliation.py` +
  `test_phase16_training_fail_closed.py` (Phase 16): 30 passed, 0
  failed.
- `tests/test_packaging_invariant.py`: 6 passed, 0 failed, including two
  new assertions added this phase (`orneur/intelligence/epistemic/`
  paths present in the built wheel; isolated-venv
  `import orneur.intelligence.epistemic` succeeds).

## Performance evidence

1,000-atom synthetic `SUPPORTS` chain, single evidence root, full
`assess_artifact()` call (including OCL recompilation + evidence-rooted
BFS + canonical overlay construction): **0.0480s** measured
(`test_epistemic_performance.py`). No quadratic/exponential behavior
observed; the worklist BFS enqueues each atom at most once per
direction.

## Full deterministic suite

Recorded in the Final Report below (section P), gathered after all
Phase 18 code, tests, and docs were complete.
