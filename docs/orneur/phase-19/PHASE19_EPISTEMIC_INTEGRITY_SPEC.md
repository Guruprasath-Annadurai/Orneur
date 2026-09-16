# Phase 19 — Epistemic Integrity Protocol Specification

Canonical architecture document for `orneur/intelligence/integrity/`.
Phase 19 CONSUMES Phase 18 Epistemic State
(`orneur/intelligence/epistemic/`) and Phase 17 OCL
(`orneur/intelligence/ocl/`) read-only — it does not modify either
package's schema or semantics.

## Core doctrine

ORNEUR must never present an epistemically weaker state as an
epistemically stronger claim. Phase 18 determines what ORNEUR currently
knows, infers, disputes, cannot verify, is uncertain about, or does not
know. **Phase 19 enforces what ORNEUR is permitted to PRESENT as
knowledge.** Phase 19 grants NO authority — an `IntegrityReceipt` is
data, never execution/policy/Court/approval/verification-truth/
model-promotion/tool/budget/release authority. It calls no model, tool,
or router, and does not begin Phase 20.

## Non-goal: this is not natural-language understanding

**Phase 19 validates a STRUCTURED proposed assertion contract
(`IntegrityProposal`/`ProposedAssertion`) against a trusted
`EpistemicOverlay`. It does not parse, scan, or semantically interpret
arbitrary natural-language prose.** There is no keyword matcher, no
regex-over-free-text, no fuzzy semantic classifier anywhere in this
package (see `tests/integrity/test_no_authority.py` for the
no-model/no-network architecture proof). A future renderer is
responsible for producing structured assertions from whatever
higher-level answer it constructs, and for rendering only the
integrity-approved ones; Phase 19 judges those structures
deterministically.

## Compound assertions — explicitly out of scope this version

A `ProposedAssertion` references **exactly one** `source_atom_id`.
Multi-atom/compound assertions (AND/OR necessity semantics inferred
from a Python list) are deliberately not supported — inferring that
semantics would be exactly the kind of "fake sophistication" this
protocol must not build. A smaller, formally correct contract is
preferable to a larger, ambiguous one.

## The hard epistemic floor

Centralized, executable source of truth: `floor.py`. Never scattered
`if` statements. May be narrowed by an `IntegrityPolicy`, never widened
(see "Policy monotonicity" below).

| Phase-18 State | Permitted Treatments | Forbidden Treatments | Required Disclosure |
|---|---|---|---|
| `KNOWN` | `ESTABLISHED` (polarity must match), `INFERENCE`, `UNCERTAIN`, `ABSTAIN` | `DISPUTE`, `UNKNOWN`, `UNVERIFIABLE` (would misrepresent an actually-resolved proposition, not merely hedge it) | none (a fully resolved, one-sided proposition needs no special disclosure beyond correct polarity) |
| `INFERRED` | `INFERENCE` (polarity must match), `UNCERTAIN`, `ABSTAIN` | `ESTABLISHED` | `QUALIFICATION_REQUIRED` |
| `UNCERTAIN` | `UNCERTAIN`, `ABSTAIN` | `ESTABLISHED`, `INFERENCE`, `DISPUTE`, `UNKNOWN`, `UNVERIFIABLE` | `UNCERTAINTY_DISCLOSURE_REQUIRED` |
| `DISPUTED` | `DISPUTE`, `UNCERTAIN`, `ABSTAIN` | `ESTABLISHED`, `INFERENCE` (would collapse the dispute to one side) | `DISPUTE_DISCLOSURE_REQUIRED` |
| `UNKNOWN` | `UNKNOWN`, `ABSTAIN` | `ESTABLISHED`, `INFERENCE`, `UNCERTAIN`, `DISPUTE`, `UNVERIFIABLE` | `UNKNOWN_DISCLOSURE_REQUIRED` |
| `UNVERIFIABLE` | `UNVERIFIABLE`, `ABSTAIN` | `ESTABLISHED`, `INFERENCE`, `UNCERTAIN`, `DISPUTE`, `UNKNOWN` (silently rewriting UNVERIFIABLE as UNKNOWN loses meaningful information) | `UNVERIFIABLE_DISCLOSURE_REQUIRED` |

`ABSTAIN` is permitted for every state — abstention never overclaims.

## Polarity

Phase 19 reuses `orneur.intelligence.epistemic.EpistemicPolarity`
directly (`AFFIRMED`/`REFUTED`/`MIXED`/`UNRESOLVED`) — never redefined.
An assertion using `ESTABLISHED` or `INFERENCE` treatment must supply a
matching `asserted_polarity`; a missing or mismatched polarity is a
`POLARITY_MISMATCH` violation. `DISPUTE`/`UNCERTAIN`/`UNKNOWN`/
`UNVERIFIABLE`/`ABSTAIN` treatments carry no polarity requirement — there
is no single correct answer to assert for an unresolved or MIXED-polarity
proposition.

## Trust boundary

Phase 19 trusts a `EpistemicOverlay` only after
`orneur.intelligence.epistemic.verify_overlay_binding(overlay, artifact)`
succeeds (source-artifact-id AND canonical-digest match). A mismatch is
caught and re-raised as Phase 19's own `errors.OverlayBindingInvalid` —
never trusting an object merely because it is shaped like an
`EpistemicOverlay`. There is no cryptographic/authenticated provenance
mechanism in this repository; this document does not claim one exists.
Phase 19's guarantee is precisely: *a correctly validated Phase-18
overlay bound to the exact source `CognitiveArtifact` supplied to the
same call*. A digest proves content identity, not authentication (same
doctrine as OCL/Phase-18's own `digest()` functions).

## Cognitive Conservation (material scope)

`IntegrityProposal.required_scope_atom_ids` is the explicit, caller-
supplied material scope — Phase 19 cannot and does not infer relevance
from free-form intent. For every scope atom whose Phase-18 state is in
`floor.MATERIAL_CONSERVATION_STATES` (`UNCERTAIN`, `DISPUTED`, `UNKNOWN`,
`UNVERIFIABLE`) and which has no corresponding assertion in the
proposal, a `REQUIRED_SCOPE_ATOM_OMITTED` violation is raised (blocking).
Omitting a `KNOWN`/`INFERRED` scope atom is recorded in
`omitted_scope_atom_ids` for audit but does not by itself block — a
resolved or derivable fact left out of an answer is a completeness
concern this protocol does not claim to police; silently dropping
unresolved material uncertainty is exactly what it exists to catch.

## Policy monotonicity

`IntegrityPolicy.stricter_permitted_treatments` may, for any
`EpistemicState`, declare a treatment set that is a **subset** of the
hard floor's own set for that state — narrowing only. `floor.validate_policy()`
rejects (raises `errors.PolicyAttemptedToWeakenHardFloor`) any policy
that declares a treatment NOT in the hard floor's set for that state —
an attempted widening is refused outright rather than silently
intersected away, so the attempt is observable and testable. The
evaluator always computes `HARD_FLOOR ∩ POLICY`, never `POLICY` alone.

## Freshness

Explicit-policy-only, never a universal age heuristic and never a
wall-clock read. `IntegrityPolicy.max_overlay_age_seconds` requires the
caller to also pass `evaluated_at` to `assess_integrity()` — there is
exactly one source of truth for "now," never two competing timestamp
fields. If no freshness policy is configured, no staleness check runs
at all (absence is never silently treated as "fresh"). `floor.is_overlay_stale()`
is a pure comparison of two explicitly supplied ISO-8601 timestamps.

## Deterministic receipt

`IntegrityReceipt.receipt_id` defaults (when the caller does not supply
one) to a SHA-256 of `(source_artifact_digest, source_overlay_digest,
proposal_digest, policy_digest, evaluated_at)` — never `uuid4()`.
Canonicalization (`canonical.py`) mirrors Phase 18/OCL's own chain
exactly: sorted collections → JSON-safe normalization →
`json.dumps(sort_keys=True, ...)` → SHA-256. `IntegrityReceipt`
deliberately has no self-referential `canonical_digest` field — callers
compute `canonical.digest(receipt)` externally, exactly as Phase 18
callers compute `epistemic.canonical.digest(overlay)`.

## Self-contained error taxonomy (a deliberate, justified duplication)

`orneur/intelligence/integrity/typecheck.py` and `freeze.py` duplicate
Phase 18's own `typecheck.py`/`freeze.py` algorithms exactly, rather
than importing them. This is intentional: importing Phase 18's
validators directly would raise `orneur.intelligence.epistemic.errors.*`
for malformed Phase-19 input, leaking a foreign exception type across
Phase 19's own public boundary and violating "every invalid public
input must raise a typed `IntegrityError` subclass." The validation
*logic* is not novel; only the *exception types* differ, and that
difference is the entire point.

## Integrity status classification

`IntegrityStatus`: `SATISFIED` (no violations), `REQUIRES_REVISION`
(violations exist, all of a kind a revised proposal could plausibly fix
— wrong treatment, polarity mismatch), `BLOCKED` (a structural/
proposal-level violation exists that changing one assertion cannot fix
— `REQUIRED_SCOPE_ATOM_OMITTED`, `STALE_EPISTEMIC_OVERLAY`,
`DUPLICATE_ASSERTION_ID`, `DUPLICATE_SCOPE_ATOM`; see
`enums.BLOCKING_VIOLATION_REASONS`). This is never a Cognitive Court
verdict — Phase 19 does not import, reuse, or redefine
`ACCEPT`/`REJECT`/`NEED_MORE_EVIDENCE`/`ESCALATE`/
`HUMAN_APPROVAL_REQUIRED`.

## Non-goals (this phase)

- No hard behavioral enforcement of what a model does with a `BLOCKED`
  receipt (abstention execution, answer repair) — that is a future
  consumer's responsibility; Phase 19 only computes the receipt.
- No router/escalation integration to Genesis/Novus/Aeternum (Phase 20).
- No claim-level natural-language entailment verifier.
- No cryptographic overlay-provenance authentication (see "Trust
  boundary" above).
- No compound/multi-atom assertion support (see "Compound assertions").
