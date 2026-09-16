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

---

## Closure: strict boundary, immutability, freshness & policy correction (appended, not rewriting the above)

Six genuine gaps were named by an independent audit and reproduced
live, before any fix.

### 1. Explicit `receipt_id`/root metadata type gaps (reproduced)

```
BAD receipt_id=123 accepted! receipt_id field: 123 <class 'int'>
BAD metadata=abc accepted! metadata field: abc <class 'str'>
BAD proposal.metadata=abc accepted!
BAD nested proposal metadata object() accepted! proposal_digest computed
fine, metadata not even touched by freeze
```

`receipt_id` was stored verbatim regardless of type. `metadata="abc"`
was accepted at the receipt level because `freeze.validate_and_freeze()`
correctly treats a bare string as a valid *nested* value but nothing
enforced the metadata *root* must be a mapping.
`IntegrityProposal.metadata` was not read by the evaluator **at all**
before this closure — not validated, not frozen, not bound to the
digest. **Fix**: `require_string(receipt_id)`;
`evaluator._require_mapping_root()` enforced at all three metadata entry
points (receipt/proposal/assertion) before `validate_and_freeze()` runs.

### 2. Proposal digest omitting metadata (reproduced)

Confirmed by direct inspection of `_proposal_digest()`'s payload
construction: `proposal.metadata` and `assertion.metadata` were both
absent from the hashed payload. **Fix**: both are now included via
`_metadata_to_json_safe()`, with metadata key-order permutation tests
confirming the addition did not introduce a new order-dependence.

### 3. Policy caller-mutation isolation (reproduced)

Confirmed by direct inspection: every existing test (including this
session's own prior closure's tests) constructed `IntegrityPolicy` with
a plain mutable `dict`, and `floor.validate_policy()`/
`effective_permitted_treatments()` read `policy.stricter_permitted_treatments`
directly — a live reference to the caller's own object. **Fix**:
`floor.normalize_policy()` deep-freezes a snapshot before any of those
functions run, called once at the top of `assess_integrity()`.

### 4. Freshness timezone safety (reproduced)

```
naive evaluated_at accepted, status: ...
$ python -c "... evaluated_at='2026-06-01T00:00:00' ..."
TypeError: can't subtract offset-naive and offset-aware datetimes
```

An offset-aware `overlay.assessed_at` (`...+00:00`, as every Phase 18
fixture produces) subtracted against an offset-naive `evaluated_at`
raised a **raw Python `TypeError`** that escaped `assess_integrity()`'s
public boundary entirely -- a direct violation of "no raw TypeError may
escape." **Fix**: `floor.parse_aware_iso8601()` rejects any naive
timestamp with a typed error before any subtraction is attempted;
applied to `evaluated_at` unconditionally (independent of whether a
freshness policy is even active) and defensively to
`overlay.assessed_at` inside `is_overlay_stale()`.

### 5. Policy-aware `permitted_maximum_treatment` (reproduced)

```
permitted_maximum_treatment under ABSTAIN-only policy: PresentationTreatment.ESTABLISHED
```

Under a policy narrowing `KNOWN` to `ABSTAIN`-only, the correction hint
still reported `ESTABLISHED` — a treatment the active policy itself
forbade. **Fix**: `floor.effective_maximum_treatment()` walks
`TREATMENT_STRENGTH_ORDER[state]` against the policy-intersected
permitted set, never the unmodified hard floor alone.

### 6. Receipt object permutation-determinism (reproduced)

```
required_disclosures ab: (DisclosureRequirement(assertion_id='as1', ...), DisclosureRequirement(assertion_id='as2', ...))
required_disclosures ba: (DisclosureRequirement(assertion_id='as2', ...), DisclosureRequirement(assertion_id='as1', ...))
disclosures equal? False
receipt equal? False
```

Two permuted-but-semantically-identical proposals produced receipts
with equal canonical digests but **unequal Python objects** --
`required_disclosures` retained input order; only `canonical.py`'s
`canonicalize()` (invoked at serialization time, not construction time)
sorted it. **Fix**: `assess_integrity()` now sorts
`required_disclosures`/`violations` at construction, using the same
stable sort keys `canonical.py` already used for serialization.

### New test files added this closure

`test_input_boundary_closure.py` (20), `test_proposal_binding_closure.py`
(4), `test_policy_normalization_closure.py` (8),
`test_freshness_timezone_closure.py` (8),
`test_receipt_object_determinism_closure.py` (4) -- 44 new tests, all
passing after the corresponding fix, plus 2 new sdist tests in
`tests/test_packaging_invariant.py`.

### Regression re-verification after the fix

`tests/integrity/`: 199 passed (155 prior + 44 new), 0 failed.
`tests/integrity + tests/epistemic + tests/ocl`: 685 passed, 0 failed.
`tests/test_packaging_invariant.py` (now building and inspecting BOTH
wheel and sdist): 8 passed, 0 failed. Phase 16 regression: 30 passed, 0
failed.

### Corrected claim (see PHASE19_REQUIREMENTS.md EPI-INTEGRITY-IMMUTABILITY-004)

The prior closure's requirements doc overstated a compile-time field
*annotation* ("all contract dataclass fields are immutable types") as a
runtime guarantee for raw, caller-constructed input contracts
(`IntegrityPolicy`/`ProposedAssertion`/`IntegrityProposal`), which a
caller could in fact construct with plain mutable `dict`/`set`/`list`
values (confirmed by item 3 above). The corrected claim distinguishes
RAW/UNTRUSTED input (caller-constructed, may be mutable) from
NORMALIZED canonical internal state (deep-frozen before semantic use)
from the CANONICAL RECEIPT (deep-frozen on output) -- see
PHASE19_EPISTEMIC_INTEGRITY_SPEC.md's "Policy normalization" section.

---

## Closure: trusted overlay provenance & policy type-boundary (appended, not rewriting the above)

Two genuine defects were named by an independent audit and reproduced
live, before any fix.

### 1. Forged overlay content, unchanged artifact binding (reproduced)

```
original overlay state: EpistemicState.UNKNOWN
original source_artifact_id: art-1
original source_artifact_digest: d576487d4cc52b42632624ddc86b0b76c8ae366ab4873a634106a8f0d5a17253
forged overlay source_artifact_id (unchanged): art-1
forged overlay source_artifact_digest (unchanged): d576487d4cc52b42632624ddc86b0b76c8ae366ab4873a634106a8f0d5a17253
forged overlay state: EpistemicState.KNOWN
verify_overlay_binding: PASSED (no exception) -- binding check does not detect forgery
Phase19 result with forged overlay: IntegrityStatus.SATISFIED
```

A real Phase-18 overlay (produced by `assess_artifact()`, genuinely
`UNKNOWN`) had its single `EpistemicAssessment` replaced via
`dataclasses.replace(overlay, assessments=(forged,))` with a fabricated
`KNOWN`/`AFFIRMED` assessment, while `source_artifact_id`/
`source_artifact_digest` were left completely unchanged.
`verify_overlay_binding()` -- the ONLY overlay-related check Phase 19
performed before this closure -- passed without raising, and
`assess_integrity()` consumed the forged assessment as genuine,
returning `SATISFIED` for an `ESTABLISHED`/`AFFIRMED` proposal about an
atom that was actually `UNKNOWN`. This proved artifact binding and
overlay-content provenance are genuinely different guarantees, and only
the former existed.

**Fix**: `assess_integrity()` now requires an explicit
`overlay_trust_context: IntegrityOverlayTrustContext` (isinstance-checked,
default `UNTRUSTED`, which always fails closed) plus, under
`TRUSTED_PHASE18_RUNTIME`, a caller-supplied `expected_overlay_digest`
-- computed by the trusted caller from the overlay BEFORE it crosses
into Phase 19, never derived from the overlay object being evaluated.
A mismatch (`epistemic.canonical.digest(overlay) != expected_overlay_digest`)
raises `OverlayProvenanceInvalid` before any assessment is read.
Re-running the exact reproduction above after the fix:
`test_overlay_provenance_closure.py::test_forged_assessment_with_correct_artifact_binding_is_now_rejected`
confirms `OverlayProvenanceInvalid` is now raised instead of `SATISFIED`
being returned.

### 2. `normalize_policy()` raw `TypeError` on unhashable members (reproduced)

```
{} -> TypeError unhashable type: 'dict'
[] -> TypeError unhashable type: 'list'
{'x': 1} -> TypeError unhashable type: 'dict'
```

`IntegrityPolicy(stricter_permitted_treatments={KNOWN: [{}]})` caused
`frozenset(declared)` to raise a raw Python `TypeError` before any
member-type validation ran -- a direct violation of "no raw TypeError
may escape." **Fix**: every member's type is now validated by iterating
the raw `declared` container FIRST; `frozenset()` is only ever called
on an already-type-validated collection.

### Test-suite migration (section 11)

Because `assess_integrity()`/`require_integrity()` gained a required
overlay-trust boundary with a fail-closed `UNTRUSTED` default, every
existing Phase-19 test call site (16 files, ~199 pre-existing call
sites) was migrated to supply an explicit trusted invocation. Rather
than hand-edit every call, `tests/integrity/conftest.py` gained
`assess_integrity_trusted()`/`require_integrity_trusted()` wrapper
functions that supply `overlay_trust_context=TRUSTED_PHASE18_RUNTIME`
and `expected_overlay_digest=epistemic.canonical.digest(overlay)` --
correct specifically because, in every one of those tests, `overlay` is
the exact, un-tampered object the test just built via a real
`assess_artifact()` call (never a value derived from a forged/mutated
object). Each of the 16 files' imports were mechanically rewritten to
alias `assess_integrity_trusted as assess_integrity` (and
`require_integrity_trusted as require_integrity` where used), so no
individual call site's arguments needed manual editing. Tests that
specifically exercise the trust boundary itself
(`test_trust_boundary.py`, `test_overlay_provenance_closure.py`) call
the REAL `evaluator.assess_integrity()` directly with explicit trust
arguments instead, so they can exercise `UNTRUSTED`/malformed/forged
paths the wrapper deliberately cannot produce.

### New test files added this closure

`test_overlay_provenance_closure.py` (13), `test_policy_type_boundary_closure.py`
(13) -- 26 new tests, all passing after the corresponding fix.
`test_trust_boundary.py` was also rewritten (7 tests, same count,
updated to use explicit trust arguments and to add
`test_fabricated_overlay_source_artifact_digest_field_still_rejected`,
a more precisely-named replacement for the previous, less specific
`test_fabricated_overlay_with_valid_looking_fields_still_rejected`).

### Corrected claim (see PHASE19_REQUIREMENTS.md EPI-INTEGRITY-BOUNDARY-002)

The prior closure's row for "fabricated overlay with valid-looking
fields still rejected" only ever tested changing
`overlay.source_artifact_digest` to an obviously-wrong value -- a field
`verify_overlay_binding()` already checked. It did not test (and
therefore did not prove) that a forged ASSESSMENT with a CORRECT,
UNCHANGED artifact binding would be rejected -- which, per item 1
above, it was not. The row is corrected to describe precisely what it
tests, and the new EPI-INTEGRITY-PROVENANCE-* requirement group covers
the stronger guarantee this closure actually adds.

### Regression re-verification after the fix

`tests/integrity/`: 225 passed (199 prior + 26 new), 0 failed.
`tests/integrity + tests/epistemic + tests/ocl`: 711 passed, 0 failed.
`tests/test_packaging_invariant.py` + Phase 16 regression: 38 passed, 0
failed.
