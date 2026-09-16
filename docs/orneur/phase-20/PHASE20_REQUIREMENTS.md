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
