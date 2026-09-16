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
   epistemic factors are still conserved on this path.
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

Same `task` + same trusted `overlay` + same `integrity_receipt` + same
`capability_registry` => byte-identical `canonical.digest(decision)`,
and the same default `decision_id` (SHA-256 of the four constituent
digests -- never `uuid4()`/`random`/wall-clock reads). Candidate
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

## 9. Non-goals

- Not a scheduler, load balancer, or concrete backend/checkpoint
  selector (that remains `orca.society.router`'s and the deployment
  layer's concern).
- Not an execution-permission or tool-invocation gate.
- Not a multi-agent task decomposition/planning system.
- Does not call, warm, or health-check any model runtime.
