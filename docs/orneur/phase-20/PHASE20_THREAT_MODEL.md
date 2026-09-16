# PHASE 20 -- THREAT MODEL

Each threat lists the attack, the mitigation, and the test(s) proving
the mitigation holds.

1. **Forged overlay content changes the routing outcome.**
   Mitigation: reused `overlay_trust.verify_trusted_overlay()` --
   `expected_overlay_digest` is caller-supplied, out-of-band, never
   derived from the overlay under evaluation.
   Test: `test_routing_behavior.py::test_forged_overlay_content_cannot_influence_routing`.

2. **Router internally computes `expected = digest(incoming_overlay)`,
   silently reintroducing the forged-overlay defect.**
   Mitigation: source-text and behavioral regression.
   Test: `test_no_authority.py::test_no_router_source_file_reimplements_digest_of_incoming_overlay`.

3. **A bare string equal to a trust-context enum value is accepted as
   if it were the genuine enum member.**
   Mitigation: `isinstance()`-only checks throughout (reused from
   Phase 19's `is_valid_overlay_trust_context`).
   Test: `test_adversarial_inputs.py::test_requirements_member_value_alike_string_rejected`
   (same isinstance discipline applied to `CognitiveRequirementKind`).

4. **`overlay_trust_context` omitted/defaulted to UNTRUSTED silently
   routes anyway.**
   Mitigation: `verify_trusted_overlay` raises `UntrustedOverlayRejected`
   for the `UNTRUSTED` default -- routing never proceeds.
   Verified live during implementation (see PHASE20_EVIDENCE.md).

5. **A supplied `IntegrityReceipt` with a failing status is ignored,
   letting a flagged proposal route as if clean.**
   Mitigation: explicit short-circuit to `BLOCKED_BY_INTEGRITY` before
   any candidate evaluation.
   Test: `test_routing_behavior.py::test_integrity_blocked_input_never_routes_as_clean`.

6. **`task.preferred_family` self-elevates an ineligible family into
   the primary route.**
   Mitigation: preference honored only after independent eligibility
   check; ignored preferences are recorded, not silently dropped.
   Test: `test_routing_behavior.py::test_preferred_family_cannot_self_elevate_ineligible_candidate`.

7. **`task.metadata` carries authority-sounding keys (`trusted`,
   `approved`, `execution_grant`, `lifecycle_state`) hoping some code
   path reads them.**
   Mitigation: metadata is validated/frozen structured data only,
   never consulted for eligibility or authority decisions.
   Test: `test_routing_behavior.py::test_task_metadata_field_named_like_authority_grants_nothing`.

8. **A caller-supplied `capability_registry` includes a duplicate
   family, letting one family's eligibility be evaluated twice /
   inconsistently.**
   Mitigation: `validate_registry()` rejects duplicate families.
   Test: `test_routing_behavior.py::test_duplicate_registry_family_is_rejected`.

9. **A caller-supplied registry entry has a non-`CognitiveRequirementKind`
   member in `supported_requirements`, causing an unhashable-type
   `TypeError` (the exact Phase 19 `normalize_policy()` bug class).**
   Mitigation: `validate_registry()` validates member types before
   any `frozenset()`-dependent operation.
   Test: `test_adversarial_inputs.py::test_capability_registry_entry_wrong_type_rejected`.

10. **A material epistemic atom id referencing a non-assessed atom is
    silently treated as absent/irrelevant, hiding uncertainty from the
    decision.**
    Mitigation: explicit `UnknownEpistemicAtomReference`.
    Test: `test_routing_behavior.py::test_unreferenced_material_atom_id_is_rejected`.

11. **UNCERTAIN/UNKNOWN/DISPUTED material states are silently dropped
    from the routing rationale (Cognitive Conservation violation).**
    Mitigation: `material_epistemic_factors` always populated from the
    task's declared material scope; corresponding reason codes always
    added.
    Tests: `test_routing_behavior.py::test_unknown_material_atom_forces_investigation_and_is_conserved`,
    `::test_disputed_material_atom_surfaces_contradiction_resolution`.

12. **An unavailable Aeternum reviewer is silently treated as "review
    satisfied", letting adversarial-review-required work through
    unreviewed.**
    Mitigation: explicit `ADVERSARIAL_REVIEWER_UNAVAILABLE` reason code,
    `mandatory_review_family` stays `None`.
    Test: `test_routing_behavior.py::test_adversarial_review_requirement_with_unavailable_reviewer_is_honest`.

13. **No eligible candidate exists; router picks an arbitrary/default
    family rather than failing closed.**
    Mitigation: explicit `NO_ELIGIBLE_ROUTE` + `primary_family=None`.
    Test: `test_routing_behavior.py::test_no_eligible_candidate_fails_closed`.

14. **Registry iteration/insertion order affects which family is
    selected among equally-eligible candidates (non-determinism).**
    Mitigation: registry validated into a canonically sorted tuple;
    role-priority tie-break is a fixed, order-independent sequence.
    Test: `test_routing_behavior.py::test_registry_entry_order_does_not_affect_decision`.

15. **`decision_id` uses `uuid4()`/wall-clock, making two identical
    inputs produce different decisions and breaking auditability.**
    Mitigation: SHA-256 of the four constituent digests.
    Test: `test_routing_behavior.py::test_same_input_produces_byte_identical_canonical_decision`.

16. **Router reuses Cognitive Court's verdict vocabulary, letting a
    routing status be mistaken for a Court verdict downstream.**
    Mitigation: `RoutingStatus` values disjoint from Court's five.
    Test: `test_no_authority.py::test_routing_status_does_not_reuse_court_verdict_vocabulary`.

17. **`RoutingDecision` grows an authority-sounding field
    (`approved`, `authorized`, `trusted`, ...) over time via careless
    extension.**
    Mitigation: explicit field-name denylist test.
    Test: `test_no_authority.py::test_routing_decision_has_no_authority_bearing_field_names`.

18. **The package imports `orca.*` (including the unrelated legacy
    `orca.society.router`), leaking legacy authority/state coupling
    into Phase 20.**
    Mitigation: AST-based import scan.
    Test: `test_no_authority.py::test_no_router_source_file_imports_orca_at_all`.

19. **A malformed/adversarial field of any typed input (task,
    registry, metadata) raises a raw, uninformative Python exception
    instead of a typed `RouterError`.**
    Mitigation: exhaustive per-field adversarial matrix.
    Tests: `test_adversarial_inputs.py` (18 cases).

20. **`RoutingDecision` is mutated post-construction by a downstream
    consumer, silently invalidating its own digest/audit trail.**
    Mitigation: frozen dataclass.
    Test: `test_routing_behavior.py::test_routing_decision_is_frozen_plain_data`.

## FINAL closure (trusted registry, receipt binding, route identity)

21. **A caller-supplied `capability_registry` passes only structural
    validation (`validate_registry()`) and is treated as trusted
    configuration, letting a caller claim any family is
    EXPERIMENTAL/AVAILABLE.** Reproduced live: a structurally-valid
    registry claiming Genesis is EXPERIMENTAL/AVAILABLE was accepted
    and selected Genesis with zero out-of-band trust check.
    Mitigation: `registry.verify_trusted_registry()` requires a
    genuine `CapabilityRegistryTrustContext` (never a bare string) and
    an out-of-band `expected_registry_digest`.
    Test: `test_trust_closure.py::test_caller_supplied_available_genesis_without_trust_is_rejected`.

22. **The router internally computes `expected = registry_digest(entries)`
    from the very registry being evaluated, reintroducing the forged-
    overlay anti-pattern one artifact type over.**
    Mitigation: source-text regression.
    Test: `test_no_authority.py::test_no_router_source_file_reimplements_digest_of_incoming_registry_or_receipt`.

23. **A registry entry's `supported_requirements` is passed as a
    mutable `set()`; the caller mutates it after validation, silently
    changing what an already-computed `registry_digest` describes.**
    Mitigation: every accepted entry is normalized via
    `dataclasses.replace(entry, supported_requirements=frozenset(...))`.
    Test: `test_trust_closure.py::test_mutable_supported_requirements_set_is_normalized_to_frozenset`.

24. **An `IntegrityReceipt` referring to a completely unrelated
    artifact/overlay is accepted merely because `isinstance(receipt,
    IntegrityReceipt)` holds, incorrectly blocking (or incorrectly
    clearing) an unrelated route.** Reproduced live: a `BLOCKED`
    receipt for `"totally-unrelated-artifact-id"` incorrectly blocked
    a genuinely clean route, and a fabricated `SATISFIED` receipt for
    the same unrelated artifact was accepted as if the CURRENT route's
    integrity had been checked.
    Mitigation: `receipt_trust.verify_trusted_receipt()` (provenance)
    + `evaluator._validate_receipt_binding()` (binding to the CURRENT
    artifact/overlay), both strictly before `integrity_status` is read.
    Tests: `test_trust_closure.py::test_mismatched_artifact_receipt_is_rejected_without_trust`,
    `::test_mismatched_artifact_receipt_is_rejected_even_with_trust_and_correct_digest`,
    `::test_fabricated_satisfied_receipt_bound_to_unrelated_artifact_is_rejected`.

25. **A structurally malformed receipt (e.g. `integrity_status` as a
    bare string) whose provenance digest happens to match is consumed
    without complaint, relying on accidental Python `is not` fail-
    closed behavior rather than an explicit, auditable rejection.**
    Mitigation: explicit `_validate_receipt_structure()`.
    Test: `test_trust_closure.py::test_malformed_receipt_field_type_is_rejected_after_trust_passes`.

26. **Two decisions computed from the same artifact/overlay/task/
    registry but different integrity receipts (or receipt vs. no
    receipt) produce the same `decision_id`, breaking audit
    distinguishability.**
    Mitigation: `source_integrity_receipt_digest` field + its inclusion
    in the default `decision_id` derivation.
    Tests: `test_trust_closure.py::test_blocked_vs_satisfied_receipt_yield_different_decision_ids`,
    `::test_receipt_present_vs_absent_yield_different_decision_ids`.

27. **A fully-unspecified task (no explicit or derived requirement)
    silently selects whichever family happens to be alphabetically
    first and available, dressing up an arbitrary choice as a
    capability match.**
    Mitigation: explicit `NO_ELIGIBLE_ROUTE` / `NO_COGNITIVE_REQUIREMENT`
    fail-closed path.
    Test: `test_routing_behavior.py::test_empty_effective_requirements_fails_closed_as_no_cognitive_requirement`.

28. **A task requiring only adversarial review, with an all-eligible
    registry, selects Aeternum as both `primary_family` and
    `mandatory_review_family` -- ambiguously implying it reviewed its
    own primary work.**
    Mitigation: explicit primary/reviewer equality guard.
    Test: `test_trust_closure.py::test_mandatory_reviewer_never_equals_primary_family`.

## ROLE-DRIVEN closure (role, not family name, drives selection)

29. **Primary/reviewer selection is actually a hardcoded family-name
    priority list dressed up as "role priority" -- it happens to agree
    with today's canonical registry (each role held by exactly one
    family) but breaks the moment role and family diverge.** Reproduced
    live with a synthetic registry swapping roles: Genesis holding
    `REASONER_INVESTIGATOR` and Novus holding `BUILDER_EXECUTOR` still
    routed investigative work to Novus and implementation work to
    Genesis, by literal family name.
    Mitigation: `evaluator._derive_preferred_role()` +
    `evaluator._select_primary()`, genuinely role-driven with a
    family-value tie-break.
    Tests: `test_role_driven_routing.py::test_investigation_swapped_roles_selects_genesis_by_role`,
    `::test_implementation_swapped_roles_selects_novus_by_role`.

30. **Reviewer selection literally searches `family is
    CognitiveFamily.AETERNUM` instead of the `CRITIC_ARBITER_DISCOVERER`
    role, breaking the moment a different family holds that role.**
    Mitigation: reviewer search filters by role.
    Test: `test_role_driven_routing.py::test_reviewer_selection_follows_role_not_family_name`.

31. **A capability-eligible candidate with the WRONG role is silently
    treated as a role match because it's the only eligible candidate.**
    Mitigation: `NO_ELIGIBLE_ROUTE` + `ROLE_ADEQUACY_NOT_SATISFIED`
    when eligible candidates exist but none holds the preferred role.
    Test: `test_role_driven_routing.py::test_role_adequacy_not_satisfied_when_no_eligible_candidate_has_required_role`.

32. **`preferred_family` bypasses role adequacy: a capability-eligible
    candidate with the wrong role is honored merely because the caller
    asked for it by name.**
    Mitigation: preference honored only when role also matches.
    Test: `test_role_driven_routing.py::test_preferred_family_with_wrong_role_cannot_bypass_role_adequacy`.

33. **A review-only task (its entire effective work is review/
    adversarial requirement kinds) is treated as a primary task with no
    core requirements, letting an arbitrary available family (e.g.
    Novus) be selected as primary while review goes unaddressed, or
    conversely produces an artificial primary/reviewer collision that
    doesn't reflect the task's real shape (the task itself IS review).**
    Mitigation: `review_only_task` detection drives primary role
    directly to `CRITIC_ARBITER_DISCOVERER`, skips the separate
    reviewer-slot search entirely, and fails closed with
    `ADVERSARIAL_REVIEWER_UNAVAILABLE` when no eligible critic exists.
    Tests: `test_routing_behavior.py::test_review_only_task_with_no_eligible_critic_fails_closed_honestly`,
    `::test_review_only_task_with_eligible_critic_routes_critic_as_primary`.

34. **A malformed nested `IntegrityReceipt` record (a raw `object()`
    where an `AssertionAssessment`/`DisclosureRequirement`/
    `IntegrityViolation` is expected, or a bare string standing in for
    one of their enum fields) reaches `integrity_canonical.digest()`
    before Phase 20 validates it, raising a raw `AttributeError` that
    escapes `route_task()` entirely.** Reproduced live for all three
    top-level nested-record tuples (`assertion_assessments`,
    `required_disclosures`, `violations`).
    Mitigation: comprehensive `receipt_trust._validate_receipt_structure()`,
    run BEFORE any digest computation, covering every top-level field
    and every nested record's every field via genuine Phase-19 enum/
    type checks (never a bare string standing in for an enum member).
    Tests: `test_receipt_structure.py` (19 cases).

35. **Even after Phase-20 structural pre-validation, Phase-19's own
    canonicalization could still raise an exception Phase 20 doesn't
    anticipate, leaking a Phase-19-internal exception type across the
    Phase-20 public boundary.**
    Mitigation: `receipt_trust.verify_trusted_receipt()` wraps the
    `integrity_canonical.digest()` call in a narrow
    `except integrity_errors.IntegrityError` translator (never a broad
    `except Exception`), raising the typed
    `IntegrityReceiptCanonicalizationFailed` instead.
    Verified via the hostile self-review sweep (no `except Exception`
    anywhere in the package) plus the structural-validation tests
    passing without ever reaching this defense-in-depth path.
