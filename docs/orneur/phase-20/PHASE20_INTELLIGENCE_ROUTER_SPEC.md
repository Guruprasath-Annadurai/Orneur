# PHASE 20 -- GOVERNED INTELLIGENCE ROUTER: SPECIFICATION

## 1. Purpose

`orneur/intelligence/router/` deterministically decides which ORNEUR
cognitive family -- Genesis, Novus, or Aeternum -- **should** handle a
typed unit of cognitive work, given:

- a typed `CognitiveTaskProfile` (untrusted, caller-supplied),
- a trusted, provenance-verified Phase 18 `EpistemicOverlay`,
- an optional Phase 19 `IntegrityReceipt`,
- a trusted `IntelligenceCapabilityProfile` registry (defaults to the
  honest, code-defined current-truth registry in `registry.py`).

The single entrypoint is `route_task()` in `evaluator.py`. Its output,
`RoutingDecision`, is a frozen dataclass -- **data**, not a command and
not a permission.

## 2. Non-authority doctrine

A `RoutingDecision` is never:

- an execution grant, a tool-invocation permission, or a budget/release
  authorization;
- a Cognitive Court verdict (`RoutingStatus` shares zero values with
  `orca.mission.cognitive_court`'s `ACCEPT`/`REJECT`/
  `NEED_MORE_EVIDENCE`/`ESCALATE`/`HUMAN_APPROVAL_REQUIRED`);
- a claim that the selected family's output is correct, verified, or
  safe to act on;
- a mutation of any Phase 18/19 state -- routing is purely a read of
  already-computed epistemic/integrity signals.

`route_task()` never calls a model, a tool, or any network endpoint. It
imports no `orca.*` module (see `tests/router/test_no_authority.py`,
which enforces this via AST import scanning).

## 3. Model-family truth

Routing eligibility must reflect what genuinely exists today, never
aspiration. Per `orca.registry.model_spec.MODEL_SPECS` (cited, not
imported):

| Family   | Role                                    | Trained checkpoint | Lifecycle (Phase 20) | Availability |
|----------|------------------------------------------|---------------------|------------------------|--------------|
| Genesis  | Builder / Executor                       | None (base model SELECTED, never trained) | `NOT_TRAINED` | `UNAVAILABLE` |
| Novus    | Reasoner / Investigator                  | Real ~8B fine-tuned EXPERIMENTAL checkpoint | `EXPERIMENTAL` | `AVAILABLE` |
| Aeternum | Critic / Arbiter / Discoverer            | None (base model UNSELECTED_PROVISIONAL) | `NOT_TRAINED` | `UNAVAILABLE` |

The default `build_default_capability_registry()` therefore has exactly
**one** routing-eligible family: Novus. This is intentional (see
`registry.py`'s module docstring), not a bug. Tests exercising other
behavioral classes supply a custom registry, mirroring how Phase 18/19
tests use synthetic fixtures rather than only production data.

> **Correction (FINAL closure, &sect;9 below).** An earlier revision of
> this document implied that a caller-supplied `capability_registry`
> passing `validate_registry()`'s structural checks was thereby usable.
> **Structural validity is not trusted configuration provenance.** A
> caller-supplied registry now requires an explicit out-of-band trust
> boundary -- see &sect;9.

## 4. Trust boundary: overlay provenance (REUSED, not reimplemented)

Phase 20 reuses `orneur.intelligence.integrity.overlay_trust.
verify_trusted_overlay()` verbatim -- the exact function Phase 19's own
`assess_integrity()` calls internally. `route_task()` never computes
`digest(overlay)` from the overlay it is evaluating and treats that as
provenance: that is the exact forged-overlay anti-pattern Phase 19's
second closure fixed (a forged overlay's self-computed digest trivially
matches itself, proving nothing). The caller must supply an
out-of-band `expected_overlay_digest`, computed by the trusted runtime
*before* the overlay crosses into Phase 20, exactly as Phase 19
requires of its own callers.

`tests/router/test_no_authority.py::
test_no_router_source_file_reimplements_digest_of_incoming_overlay`
is a dedicated regression proving this anti-pattern's absence via
source-text scanning, not just behavioral testing.

## 5. Routing signals

`route_task()` considers, in order:

1. **Integrity status.** If a supplied `IntegrityReceipt.
   integrity_status` is not `SATISFIED`, routing short-circuits to
   `BLOCKED_BY_INTEGRITY` -- no candidate evaluation occurs. Material
   epistemic factors are still conserved on this path. **Correction
   (FINAL closure, &sect;9):** an earlier revision consumed
   `integrity_status` as soon as `isinstance(receipt, IntegrityReceipt)`
   held. **Instance/type membership is not trusted Phase-19
   provenance.** The receipt is now verified for provenance (out-of-
   band digest) and BOUND to the current artifact/overlay before its
   status is ever read -- see &sect;9.
2. **Material epistemic state** (Cognitive Conservation). Every atom
   id in `task.material_epistemic_atom_ids` must exist in the trusted
   overlay's assessments (else `UnknownEpistemicAtomReference`) and its
   `EpistemicState` is preserved in the decision's
   `material_epistemic_factors`, never silently dropped. UNCERTAIN,
   UNKNOWN, DISPUTED, and UNVERIFIABLE states each add an implicit
   requirement (uncertainty resolution, investigation, contradiction
   resolution respectively) and a corresponding typed reason code.
3. **Explicit + derived requirements** against the trusted capability
   registry: a candidate is eligible only if (a) its lifecycle state is
   in `ELIGIBLE_LIFECYCLE_STATES` and its runtime is `AVAILABLE`, and
   (b) its `supported_requirements` is a superset of the task's
   "core" effective requirements (everything except
   `ADVERSARIAL_REVIEW`, which is a separate review-slot signal, not a
   primary-role requirement).
4. **Role priority** when multiple candidates are eligible: an
   investigative signal prefers `REASONER_INVESTIGATOR`, a pure
   implementation signal prefers `BUILDER_EXECUTOR`; a caller's
   `preferred_family` is honored only if it is independently eligible
   (never granted by the request alone -- see &sect;6).
5. **Mandatory review.** If `ADVERSARIAL_REVIEW`,
   `SECURITY_SENSITIVE_REASONING`, or `HIGH_CONSEQUENCE_REASONING` is
   in the effective requirement set, a lifecycle/availability-eligible
   Aeternum entry with a matching supported requirement becomes
   `mandatory_review_family`. Unavailability is surfaced honestly via
   `ADVERSARIAL_REVIEWER_UNAVAILABLE` -- never silently treated as
   "reviewed."

A task whose combined core requirements no single registered family
covers fails closed to `NO_ELIGIBLE_ROUTE` rather than guessing a
partial match or splitting the task across two candidates -- Phase 20's
V1 model is single-primary-owner routing, not multi-agent planning.

## 6. Self-elevation resistance

`task.preferred_family` and `task.metadata` are untrusted. Neither can
grant eligibility, alter lifecycle/availability, or bypass the
capability-registry subset check. A preference that cannot be honored
produces `PREFERENCE_NOT_ELIGIBLE` in `reason_codes`, transparently,
rather than silently being dropped or silently being granted.

## 7. Determinism

Same `task` + same trusted `overlay` + same `integrity_receipt` (or
lack thereof) + same `capability_registry` => byte-identical
`canonical.digest(decision)`, and the same default `decision_id`
(SHA-256 of five constituent digests -- source artifact, overlay,
task, registry, and receipt-or-a-fixed-`"NONE"`-sentinel; never
`uuid4()`/`random`/wall-clock reads -- see &sect;9). Candidate
evaluation order never depends on registry insertion order (registry
entries are validated into a canonical `family.value`-sorted tuple
before evaluation).

## 8. Relationship to `orca.society.router`

A pre-existing, unrelated legacy router (`orca/society/router.py`,
Phase 7 era) performs concrete checkpoint/backend selection against
`orca.registry`'s Ollama-tier model catalog via hard-filter +
soft-ranking. Phase 20 is a distinct, higher layer: cognitive-family/
role selection informed by Phase 18/19 signals the legacy router never
had access to. Phase 20 deliberately does not import from
`orca.society.*` -- consistent with the "no `orca.*` imports" purity
doctrine already established for `orneur.intelligence.epistemic` and
`orneur.intelligence.integrity`.

## 9. FINAL closure: trusted registry, receipt binding, route identity

The initial closure accepted `capability_registry` after only
structural validation, and consumed a supplied `IntegrityReceipt` after
only an `isinstance()` check. Neither is a genuine trust boundary --
both were reproduced live as real self-elevation/binding defects (see
`PHASE20_EVIDENCE.md`) and closed here.

**Registry trust** (`registry.verify_trusted_registry`, mirroring
`overlay_trust.verify_trusted_overlay` exactly): a caller-supplied
`capability_registry` requires `capability_registry_trust_context`
(a genuine `CapabilityRegistryTrustContext` member -- `UNTRUSTED`,
the default, always fails closed) and an `expected_registry_digest`
supplied out-of-band by the trusted router-configuration owner
*before* the registry crosses into `route_task()`. The registry is
first normalized (`validate_registry()` -- every entry's
`supported_requirements` coerced into an immutable `frozenset`, so a
caller's own mutable `set()` cannot be mutated post-validation to
retroactively change an already-computed digest or an already-returned
decision) and only then digested and compared. `capability_registry=
None` uses the code-defined default registry, trusted by construction
-- no out-of-band digest needed.

**Integrity receipt trust** (`receipt_trust.verify_trusted_receipt`,
a NEW Phase-20-owned seam analogous to `overlay_trust`, since Phase 20
is the consumer of this Phase-19 artifact): a supplied `integrity_receipt`
requires `integrity_receipt_trust_context` (a genuine
`IntegrityReceiptTrustContext` member -- `UNTRUSTED` fails closed) and
an `expected_integrity_receipt_digest` supplied out-of-band by the
trusted Phase-19 caller. Provenance-verified receipts are then
structurally validated (`_validate_receipt_structure` -- every field
checked with typed `require_string`/`require_enum_member`, since a
dataclass does not enforce field types at construction) and finally
**bound** to the current routing inputs
(`_validate_receipt_binding`): `receipt.source_artifact_id`,
`receipt.source_artifact_digest`, and `receipt.source_overlay_digest`
must all match the artifact/overlay actually being routed, or
`IntegrityReceiptBindingInvalid` is raised. All three checks happen
strictly before `receipt.integrity_status` is ever read.

**Route identity.** `RoutingDecision` now carries
`source_integrity_receipt_digest: str | None` (`None` when no receipt
was supplied). The default `decision_id` is SHA-256 of all five
constituent digests (source artifact, overlay, task, registry, and
receipt-or-a-fixed-`"NONE"`-sentinel) -- so two otherwise-identical
routes differing only in which integrity receipt (or none) was
supplied always produce different `decision_id`s.

**Empty-requirement semantics.** If, after epistemic derivation,
`effective_requirements` is empty, `route_task()` returns
`NO_ELIGIBLE_ROUTE` with `NO_COGNITIVE_REQUIREMENT` rather than
selecting an "available" family with no adequacy signal behind the
choice. This replaces the prior implicit alphabetical-fallback
behavior for the fully-unspecified-task case.

**Review honesty.** A family can never be reported as both
`primary_family` and `mandatory_review_family` in the same decision --
that would ambiguously imply a family independently reviewed its own
primary work. If the only otherwise-eligible reviewer coincides with
the selected primary family, `mandatory_review_family` is cleared to
`None` and `MANDATORY_REVIEWER_CANNOT_BE_PRIMARY_FAMILY` is recorded.

## 10. Non-goals

- Not a scheduler, load balancer, or concrete backend/checkpoint
  selector (that remains `orca.society.router`'s and the deployment
  layer's concern).
- Not an execution-permission or tool-invocation gate.
- Not a multi-agent task decomposition/planning system.
- Does not call, warm, or health-check any model runtime.
