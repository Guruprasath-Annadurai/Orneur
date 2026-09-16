# PHASE 20 -- REQUIREMENTS

## Functional

1. `route_task(task, *, overlay, artifact, overlay_trust_context,
   expected_overlay_digest, integrity_receipt=None,
   capability_registry=None, decision_id=None, metadata=None) ->
   RoutingDecision` is the single deterministic entrypoint.
2. Overlay provenance MUST be verified via the reused Phase 19
   `overlay_trust.verify_trusted_overlay()` seam -- never a locally
   reimplemented digest comparison.
3. A supplied `IntegrityReceipt` with `integrity_status is not
   SATISFIED` MUST short-circuit routing to `BLOCKED_BY_INTEGRITY`
   before any candidate is evaluated.
4. Every atom id in `task.material_epistemic_atom_ids` MUST exist in
   `overlay.assessments`; otherwise `UnknownEpistemicAtomReference`.
5. Material epistemic state MUST be preserved in
   `RoutingDecision.material_epistemic_factors` (Cognitive
   Conservation) on every path, including the integrity-blocked path.
6. UNCERTAIN / UNKNOWN / DISPUTED / UNVERIFIABLE material atoms MUST
   each add an implicit requirement and a typed reason code -- never
   silently ignored.
7. Candidate eligibility MUST require both lifecycle/availability
   eligibility (`registry.is_eligible`) AND full coverage of the
   task's core (non-`ADVERSARIAL_REVIEW`) effective requirement set.
8. A `preferred_family` MUST be honored only if independently
   eligible; otherwise `PREFERENCE_NOT_ELIGIBLE` is recorded and role-
   priority selection proceeds unaffected.
9. `ADVERSARIAL_REVIEW` / `SECURITY_SENSITIVE_REASONING` /
   `HIGH_CONSEQUENCE_REASONING` in the effective requirement set MUST
   attempt to assign `mandatory_review_family`, evaluated independently
   of the primary candidate's core-requirement coverage; unavailability
   MUST be recorded via `ADVERSARIAL_REVIEWER_UNAVAILABLE`, never
   silently treated as satisfied.
10. No eligible primary candidate MUST yield `NO_ELIGIBLE_ROUTE`,
    `primary_family=None`, and `NO_CANDIDATE_ELIGIBLE` -- never a fake
    fallback family.
11. `RoutingStatus` MUST NOT reuse any Cognitive Court verdict value.
12. `route_task()` MUST be deterministic: identical input produces a
    byte-identical `canonical.digest(decision)` and identical default
    `decision_id` (never `uuid4()`/`random`/wall-clock).
13. Candidate evaluation order MUST NOT depend on registry
    insertion/iteration order.
14. The package MUST NOT import any `orca.*` module and MUST NOT call
    any model, tool, or network endpoint.
15. All untrusted input (task fields, registry entries, metadata) MUST
    be validated via typed, self-contained `typecheck.py`/`freeze.py`
    helpers -- never a raw `TypeError`/`KeyError`/`AttributeError`
    escaping to the caller.

## FINAL closure (trusted registry, receipt binding, route identity)

16. A caller-supplied `capability_registry` MUST require a genuine
    `CapabilityRegistryTrustContext` member (`UNTRUSTED` fails closed)
    and an out-of-band `expected_registry_digest` -- structural
    validity alone (`validate_registry()`) MUST NOT be treated as
    trusted provenance. `capability_registry=None` uses the code-
    defined default registry, trusted by construction.
17. Every accepted registry entry's `supported_requirements` MUST be
    normalized into an immutable `frozenset` (never left as a caller-
    supplied mutable `set()`), so post-validation caller-side mutation
    cannot retroactively change a route already computed from it.
18. A supplied `integrity_receipt` MUST require a genuine
    `IntegrityReceiptTrustContext` member (`UNTRUSTED` fails closed)
    and an out-of-band `expected_integrity_receipt_digest` --
    `isinstance(receipt, IntegrityReceipt)` alone MUST NOT be treated
    as trusted Phase-19 provenance.
19. A supplied receipt MUST be structurally validated BEFORE any
    digest is computed on it. **Correction (ROLE/STRUCTURE closure,
    requirement 29 below):** this requirement previously read "every
    field" while the implementation at the time validated only the six
    top-level scalar fields (`protocol_version`, `receipt_id`,
    `source_artifact_id`, `source_artifact_digest`,
    `source_overlay_digest`, `integrity_status`) -- an overclaim,
    corrected here and in the implementation: validation now covers
    every top-level field AND every nested `AssertionAssessment`/
    `DisclosureRequirement`/`IntegrityViolation` record (see
    requirement 29). Only THEN is a provenance-verified, structurally-
    valid receipt bound to the artifact/overlay currently being routed
    (`source_artifact_id`/`source_artifact_digest`/
    `source_overlay_digest` all matching) before `integrity_status` is
    ever consumed. A binding mismatch MUST raise
    `IntegrityReceiptBindingInvalid`.
20. `RoutingDecision` MUST carry `source_integrity_receipt_digest`
    (`None` when no receipt was supplied), and the default
    `decision_id` MUST incorporate it, so a decision computed with a
    receipt is never identical to one computed without, and two
    decisions differing only in which valid receipt was supplied are
    never identical.
21. A task with no explicit AND no epistemically-derived cognitive
    requirement MUST fail closed to `NO_ELIGIBLE_ROUTE` /
    `NO_COGNITIVE_REQUIREMENT`, never select an arbitrary "available"
    family.
22. `mandatory_review_family` MUST NOT equal `primary_family` in any
    returned decision; if the only otherwise-eligible reviewer
    coincides with the primary family, `mandatory_review_family` MUST
    be cleared to `None` and `MANDATORY_REVIEWER_CANNOT_BE_PRIMARY_
    FAMILY` MUST be recorded.

## ROLE-DRIVEN closure (role, not family name, drives selection)

23. Primary selection MUST be a function of a derived
    `CognitiveRole` (via a full, fixed-precedence partition of every
    `CognitiveRequirementKind`), never a hardcoded family-name priority
    list, even one that currently agrees with canonical registry truth.
24. Among capability-eligible candidates whose role matches the
    preferred role, selection MUST use a stable family-value tie-break.
25. A caller's `preferred_family` MUST be honored only if independently
    eligible AND its role matches the preferred role -- role adequacy
    MUST NOT be bypassable by preference.
26. If eligible candidates exist but none holds the preferred role,
    this MUST NOT be silently treated as a match: `NO_ELIGIBLE_ROUTE`
    with `ROLE_ADEQUACY_NOT_SATISFIED` MUST be returned instead.
27. Mandatory-reviewer selection MUST filter by
    `CognitiveRole.CRITIC_ARBITER_DISCOVERER`, never by
    `family is CognitiveFamily.AETERNUM` or any other literal family
    check.
28. A task whose entire effective work is review/adversarial
    requirement kinds MUST be treated as the review itself: its
    preferred role MUST be `CRITIC_ARBITER_DISCOVERER`,
    `mandatory_review_family` MUST stay `None`, and the mandatory-
    review-slot search MUST be skipped. A MIXED task (primary work +
    a distinct review requirement) MUST retain the two-slot meaning
    (distinct primary and reviewer families).
29. An `IntegrityReceipt` MUST undergo FULL structural pre-validation
    (every top-level field, and every nested `AssertionAssessment`/
    `DisclosureRequirement`/`IntegrityViolation` record) BEFORE
    `integrity_canonical.digest()` is ever called on it -- never after.
    A structurally malformed receipt MUST fail with a typed
    `RouterError`, never a raw `AttributeError`/`TypeError`/
    `KeyError`/`ValueError`.
30. Any exception `integrity_canonical.digest()` itself raises (defense
    in depth, in case structural pre-validation has a gap) MUST be
    caught and translated into a typed `RouterError`, never left to
    escape `route_task()` unwrapped.

## Non-functional

- Payload limits (`limits.py`) bound requirement-set size, material-
  atom count, registry size, metadata depth/keys/string length, and
  canonical-JSON serialized size -- all enforced via typed
  `PayloadLimitExceeded`.
- `errors.py` is self-contained (does not import `epistemic.errors` or
  `integrity.errors` directly for validation), preserving this
  package's own exception-type boundary -- the exact lesson learned
  during Phase 19's initial build.
- Public exports (`__init__.py`) are a narrow, curated `__all__`.

## Traceability

See `PHASE20_THREAT_MODEL.md` for the enumerated threats each
requirement above closes, and `PHASE20_EVIDENCE.md` for the live
reproduction and test evidence for each.
