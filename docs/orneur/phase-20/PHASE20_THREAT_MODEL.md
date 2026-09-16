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
