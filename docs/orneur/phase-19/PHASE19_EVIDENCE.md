# Phase 19 Evidence Log

Recorded as work proceeded. Distinguishes **observed** (a command was
actually run and its output recorded), **tested** (a pytest assertion
exists and passed), **inferred** (a reasonable conclusion drawn from
observed/tested facts), and **deferred** (explicitly not attempted this
phase).

## Starting state (observed)

```
$ git status --short
(empty -- clean tree)
$ git branch --show-current
session-update-2026-08-25
$ git rev-parse HEAD
377f6d3bba2ae6e93ddf94861b49b3d5d1163e5f
```
Matched the required starting SHA exactly.

## Baseline tests (observed, before any Phase 19 code)

```
$ pytest tests/epistemic tests/ocl -q
486 passed, 1 warning in 3.64s
```
(138 epistemic + 348 OCL, matching the Phase-18 closure's own reported
counts exactly — no drift.)

```
$ pytest tests/test_phase16_architecture_invariants.py \
         tests/test_phase16_canonical_training_identity.py \
         tests/test_phase16_court_reconciliation.py \
         tests/test_phase16_training_fail_closed.py \
         tests/test_packaging_invariant.py -q
36 passed, 2 warnings in 13.43s
```
(30 Phase-16 + 6 packaging, matching prior baseline.) Baseline was
green — no pre-existing regression to bury Phase-19 work under.

## Section 34 TDD evidence: demonstrating the missing enforcement layer

Rather than fabricate a Phase-18 "bug" (none exists — Phase 18 has no
presentation concept at all, so there is nothing there to be buggy),
this closure demonstrates the missing layer directly:
`tests/integrity/test_phase18_integration.py::test_step1_real_ocl_compile_then_real_phase18_assess_then_real_phase19_evaluate`
builds a real OCL artifact with **zero evidence**, compiles it, runs it
through the real `assess_artifact()`, and confirms the resulting
overlay's state is `UNKNOWN` — Phase 18's own public API returns this
state and stops; there is no method on `EpistemicOverlay` or function in
`orneur.intelligence.epistemic` that could be asked "is presenting this
as ESTABLISHED allowed?" The question is simply not expressible in
Phase 18's vocabulary. The same test then constructs an
`IntegrityProposal` presenting that atom as `ESTABLISHED`/`AFFIRMED` and
confirms `assess_integrity()` returns `BLOCKED` — the enforcement layer
that did not exist before Phase 19 now exists and works end to end with
real (non-mocked) Phase 17/18 objects.

## Implementation order and gates

1. **Contracts + enums + errors + limits** (`contracts.py`, `enums.py`,
   `errors.py`, `limits.py`) written first. **GATE: PASS** (import
   smoke-tested immediately).
2. **Hard floor** (`floor.py`) written, encoding the state matrix from
   first principles per the closure spec's normative requirements.
   **GATE: PASS**.
3. **Canonicalization** (`canonical.py`) mirroring Phase 18's own chain.
   **GATE: PASS**.
4. **Evaluator** (`evaluator.py`) written, initially importing Phase
   18's `typecheck`/`freeze` directly for reuse. `tests/integrity/test_canonical_cases.py`
   (all 12 required CASE A-L scenarios) written and run: **all 12
   passed on the first run** — the core algorithm design (permitted-
   treatment lookup, polarity check, scope coverage, policy
   intersection, overlay-binding translation) required zero correction.
   **GATE: PASS**.
5. **Trust-boundary tests** (`test_trust_boundary.py`) written and run:
   2 of 7 failed —
   `test_malformed_overlay_type_rejected`/`test_malformed_artifact_type_rejected`
   expected `orneur.intelligence.integrity.errors.InvalidObjectType` but
   received `orneur.intelligence.epistemic.errors.InvalidObjectType`,
   because `evaluator.py` was directly importing and calling Phase 18's
   `typecheck.require_instance()`, which raises Phase-18-namespaced
   errors. **This is a genuine Phase-19 design defect, not a Phase-18
   bug**: reusing another phase's validator function means reusing its
   exception types too, which violates "every invalid public input must
   raise a typed IntegrityError subclass." **Fix**: wrote Phase 19's own
   `typecheck.py`/`freeze.py` (same isinstance-based algorithm,
   deliberately re-implemented so the raised exceptions are Phase-19's
   own), and switched every internal call site. Re-ran: **all 37 passed**.
   **GATE: PASS** (after one real, documented correction).

## Full Phase-19 targeted suite (observed)

```
$ pytest tests/integrity/ -q
155 passed, 1 warning in 0.48s
```

Breakdown: `test_canonical_cases.py` 12, `test_state_preservation.py`
18, `test_trust_boundary.py` 7, `test_hard_state_matrix.py` 49 (42
state×treatment combinations + 7 polarity/coverage checks),
`test_determinism.py` 7, `test_type_boundary.py` 26,
`test_deep_immutability.py` 6, `test_staleness.py` 7,
`test_no_authority.py` 7, `test_cognitive_conservation.py` 5,
`test_policy_monotonicity.py` 6, `test_phase18_integration.py` 2,
`test_performance_and_require_integrity.py` 3.

## Hostile self-review (section 50, observed)

Grep sweep over `orneur/intelligence/integrity/*.py` for: `uuid`,
`random`, `datetime.now`, `time.time`, `hash(`, `set(`, `confidence`,
`trusted`, `approved`, `authorized`, `verified`, `ACCEPT`,
`HUMAN_APPROVAL_REQUIRED`, `except Exception`, `: Any`, `cast(`,
`type: ignore`.

Findings: `set(`/`frozenset(` occurrences are all local dedup-detection
sets in validators or frozenset literals in the hard-floor matrix —
never a mutable field on a frozen contract. `confidence`/`trusted`/
`approved`/`verified` occur only inside docstrings explicitly
documenting their ABSENCE as fields (the "deliberately absent" doctrine)
or as ordinary English adjectives describing the trust boundary in
prose — never as an actual dataclass field name (confirmed separately by
`test_no_authority.py::test_integrity_receipt_has_no_authority_bearing_field_names`).
`ACCEPT`/`HUMAN_APPROVAL_REQUIRED` occur only in a docstring explaining
Phase 19 does NOT reuse them (confirmed by
`test_integrity_status_does_not_reuse_court_verdict_vocabulary`). Zero
occurrences of `uuid`, `random`, `datetime.now`, `time.time`, `hash(`,
`except Exception`, `: Any`, `cast(`. One `type: ignore[arg-type]`
occurrence (`evaluator.py`, the `is_overlay_stale` call), immediately
preceded by a comment explaining exactly why the narrowing is safe
(`validate_policy()` already guaranteed `evaluated_at is not None` on
this path) — kept, justified inline.

Separately confirmed: no `: dict`/`: list` field-type annotation exists
anywhere in `contracts.py`'s dataclasses — every collection field is
`tuple[...]` or `MappingProxyType`.

## Regression re-verification after Phase 19 was complete (observed)

```
$ pytest tests/integrity tests/epistemic tests/ocl -q
641 passed, 1 warning in 2.42s
```
(155 + 138 + 348 = 641, exact.)

```
$ pytest tests/test_packaging_invariant.py -q
6 passed, 1 warning in 11.63s
```
(Extended this closure to add `orneur/intelligence/integrity/` to
`REQUIRED_WHEEL_PATHS` and an isolated-venv
`import orneur.intelligence.integrity` check — both passed.)

```
$ pytest tests/test_phase16_architecture_invariants.py \
         tests/test_phase16_canonical_training_identity.py \
         tests/test_phase16_court_reconciliation.py \
         tests/test_phase16_training_fail_closed.py -q
30 passed, 2 warnings in 1.65s
```

## Deterministic receipt example (observed)

For a `KNOWN`/`AFFIRMED` atom presented as `ESTABLISHED`/`AFFIRMED`
(`test_canonical_cases.py::test_case_l_*`), two independent calls to
`assess_integrity()` with identical inputs and no explicit `receipt_id`
produced byte-identical `receipt_id`, canonical JSON, and digest —
confirmed programmatically, not merely asserted in prose.

## Full deterministic suite and CI

Recorded in the Final Report's TESTS/CI sections, gathered after all
Phase 19 code, tests, and docs were complete and pushed.

## Known limitations (deferred, stated precisely)

- Compound/multi-atom assertions: **deferred**, not attempted.
- Cryptographic overlay-provenance authentication: **deferred**, not
  attempted; documented as a real, acknowledged gap rather than
  papered over.
- Behavioral enforcement of a `BLOCKED` receipt (what a caller actually
  *does* in response): **deferred** — out of Phase 19's declared scope
  by design (see spec's Non-goals).
- Semantic validation of arbitrary natural-language prose: **explicitly
  never claimed** — this protocol validates structured cognitive
  assertions only, stated in the spec's own "Non-goal" section and
  enforced structurally (no NLP code exists anywhere in the package).
