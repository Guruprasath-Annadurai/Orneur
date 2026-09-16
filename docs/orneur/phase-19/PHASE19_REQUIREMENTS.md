# Phase 19 Requirements Registry

Status values: `VERIFIED` (implemented + cited test evidence),
`IMPLEMENTED`, `DEFERRED_TO_FUTURE_PHASE`, `BLOCKED`, `UNIMPLEMENTED`.
Nothing here is marked `VERIFIED` without a cited test.

## EPI-INTEGRITY-BOUNDARY

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-BOUNDARY-001 | Overlay must pass `verify_overlay_binding()` (artifact identity/content); failure raises `OverlayBindingInvalid` | `evaluator.py::assess_integrity` | `test_trust_boundary.py` (7 tests), `test_canonical_cases.py::test_case_j_*` | VERIFIED |
| EPI-INTEGRITY-BOUNDARY-002 | An overlay whose `source_artifact_digest` FIELD is fabricated (does not match the artifact's real digest) is rejected | `verify_overlay_binding` (digest comparison) | `test_trust_boundary.py::test_fabricated_overlay_source_artifact_digest_field_still_rejected` | VERIFIED (renamed/narrowed this closure -- see EPI-INTEGRITY-PROVENANCE-* below for the stronger, previously-missing check that a forged ASSESSMENT with an UNCHANGED, correct artifact binding is also rejected; the original wording of this row implied that stronger guarantee already existed, which it did not) |
| EPI-INTEGRITY-BOUNDARY-003 | Unknown atom reference (assertion or scope) fails closed | `evaluator.py` (`NonAssessedAtomReference`) | `test_trust_boundary.py::test_unknown_atom_reference_in_assertion_rejected`, `::test_unknown_atom_reference_in_scope_rejected` | VERIFIED |
| EPI-INTEGRITY-BOUNDARY-004 | Malformed overlay/artifact/proposal/policy type rejected | `typecheck.py::require_instance` | `test_trust_boundary.py`, `test_type_boundary.py` | VERIFIED |

## EPI-INTEGRITY-STATE

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-STATE-001 | Every Phase-18 state has an explicit, centralized permitted-treatment set | `floor.py::HARD_FLOOR_PERMITTED_TREATMENTS` | `test_hard_state_matrix.py::test_full_state_by_treatment_matrix` (42 combinations) | VERIFIED |
| EPI-INTEGRITY-STATE-002 | KNOWN may be ESTABLISHED (polarity-matched) or more cautious | `floor.py` | `test_canonical_cases.py::test_case_a_*` | VERIFIED |
| EPI-INTEGRITY-STATE-003 | INFERRED may never be ESTABLISHED | `floor.py`, `evaluator.py::_classify_violation_reason` | `test_state_preservation.py::test_inferred_to_established_fails` | VERIFIED |
| EPI-INTEGRITY-STATE-004 | UNCERTAIN may never be ESTABLISHED/INFERENCE | `floor.py` | `test_canonical_cases.py::test_case_c_*` | VERIFIED |
| EPI-INTEGRITY-STATE-005 | DISPUTED may never collapse to one-sided ESTABLISHED/INFERENCE | `floor.py` | `test_state_preservation.py::test_disputed_cannot_be_output_as_one_sided_affirmed`, `::test_disputed_cannot_be_output_as_one_sided_refuted` | VERIFIED |
| EPI-INTEGRITY-STATE-006 | UNKNOWN may never be presented as substantive knowledge | `floor.py` | `test_state_preservation.py::test_unknown_cannot_be_established`, `::test_unknown_cannot_be_presented_as_supported_inference` | VERIFIED |
| EPI-INTEGRITY-STATE-007 | UNVERIFIABLE may never be called verified, and may not be silently rewritten as UNKNOWN | `floor.py` | `test_state_preservation.py::test_unverifiable_cannot_be_called_verified`, `::test_unverifiable_cannot_be_silently_rewritten_as_unknown` | VERIFIED |
| EPI-INTEGRITY-STATE-008 | ABSTAIN always permitted for every state | `floor.py` | `test_hard_state_matrix.py::test_abstain_is_always_permitted_for_every_state` | VERIFIED |

## EPI-INTEGRITY-POLARITY

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-POLARITY-001 | KNOWN/AFFIRMED cannot be presented as REFUTED | `evaluator.py::_assess_one_assertion` | `test_hard_state_matrix.py::test_known_affirmed_cannot_be_presented_as_refuted` | VERIFIED |
| EPI-INTEGRITY-POLARITY-002 | Missing asserted_polarity when required is a violation | `evaluator.py` | `test_hard_state_matrix.py::test_polarity_none_when_required_is_a_mismatch` | VERIFIED |
| EPI-INTEGRITY-POLARITY-003 | Reuses `epistemic.EpistemicPolarity` directly, never redefined | `contracts.py` imports | code inspection; `test_no_authority.py` architecture tests confirm no parallel enum defined | VERIFIED |

## EPI-INTEGRITY-CONSERVATION

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-CONSERVATION-001 | Omitted material UNCERTAIN/DISPUTED/UNKNOWN/UNVERIFIABLE scope atom blocks | `evaluator.py`, `floor.MATERIAL_CONSERVATION_STATES` | `test_cognitive_conservation.py` (5 tests) | VERIFIED |
| EPI-INTEGRITY-CONSERVATION-002 | Omitted KNOWN/INFERRED scope atom recorded but not blocking (documented scope limit) | `evaluator.py` | `test_cognitive_conservation.py::test_omitted_material_known_atom_recorded_but_not_blocking` | VERIFIED |
| EPI-INTEGRITY-CONSERVATION-003 | Scope is explicit caller input, never inferred from prose | `contracts.py::IntegrityProposal.required_scope_atom_ids` | design (no NLP anywhere in package, see EPI-INTEGRITY-AUTHORITY-003) | VERIFIED |

## EPI-INTEGRITY-DISPUTE

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-DISPUTE-001 | Dispute cannot be output as one-sided AFFIRMED or REFUTED | `floor.py` | `test_state_preservation.py` (2 tests) | VERIFIED |
| EPI-INTEGRITY-DISPUTE-002 | Dispute can use dispute-preserving treatment | `floor.py` | `test_canonical_cases.py::test_case_e_*` | VERIFIED |
| EPI-INTEGRITY-DISPUTE-003 | Dispute conflict cannot disappear via scope omission | `evaluator.py` | `test_state_preservation.py::test_disputed_conflict_cannot_silently_disappear_through_scope_omission` | VERIFIED |
| EPI-INTEGRITY-DISPUTE-004 | Stricter policy may demand abstention for disputes | `floor.py::effective_permitted_treatments` | `test_state_preservation.py::test_stricter_policy_may_demand_abstention_for_disputed` | VERIFIED |
| EPI-INTEGRITY-DISPUTE-005 | Weaker policy cannot permit one-sided fact presentation | `floor.py::validate_policy` | `test_state_preservation.py::test_weaker_policy_cannot_permit_one_sided_fact_presentation_for_disputed` | VERIFIED |

## EPI-INTEGRITY-POLICY

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-POLICY-001 | Policy composition is HARD_FLOOR ∩ POLICY, never POLICY alone | `floor.py::effective_permitted_treatments` | `test_policy_monotonicity.py` (6 tests) | VERIFIED |
| EPI-INTEGRITY-POLICY-002 | Policy declaring a treatment outside the hard floor is rejected outright | `floor.py::validate_policy` (`PolicyAttemptedToWeakenHardFloor`) | `test_canonical_cases.py::test_case_k_*`, `test_policy_monotonicity.py::test_attempted_weakening_for_multiple_states_at_once_rejected` | VERIFIED |
| EPI-INTEGRITY-POLICY-003 | Malformed policy (wrong key/value type) rejected | `floor.py::validate_policy` | `test_policy_monotonicity.py::test_policy_with_wrong_key_type_rejected`, `::test_policy_with_wrong_value_type_rejected` | VERIFIED |
| EPI-INTEGRITY-POLICY-004 | No policy at all uses the pure hard floor | `evaluator.py` (`policy=None` default) | `test_policy_monotonicity.py::test_no_policy_at_all_uses_pure_hard_floor` | VERIFIED |

## EPI-INTEGRITY-FRESHNESS

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-FRESHNESS-001 | No freshness policy means not evaluated, never implicitly "fresh" | `evaluator.py` (staleness check only runs if `policy.max_overlay_age_seconds` set) | `test_staleness.py::test_no_freshness_policy_means_not_evaluated_not_fresh` | VERIFIED |
| EPI-INTEGRITY-FRESHNESS-002 | Configured stale overlay blocks | `floor.py::is_overlay_stale` | `test_staleness.py::test_configured_stale_overlay_is_blocked` | VERIFIED |
| EPI-INTEGRITY-FRESHNESS-003 | max_overlay_age_seconds without evaluated_at fails closed | `floor.py::validate_policy` | `test_staleness.py::test_max_age_without_evaluated_at_fails_closed` | VERIFIED |
| EPI-INTEGRITY-FRESHNESS-004 | No wall-clock read anywhere in staleness comparison | `floor.py::is_overlay_stale` (two explicit ISO-8601 args only) | `test_staleness.py::test_determinism_with_explicit_evaluation_time_no_clock_dependency`; grep sweep (section 50) found zero `datetime.now`/`time.time` | VERIFIED |
| EPI-INTEGRITY-FRESHNESS-005 | Malformed freshness config (negative/bool age) rejected | `floor.py::validate_policy` | `test_staleness.py::test_negative_max_overlay_age_seconds_rejected`, `::test_bool_max_overlay_age_seconds_rejected` | VERIFIED |

## EPI-INTEGRITY-DETERMINISM

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-DETERMINISM-001 | Default receipt_id is a pure SHA-256 function of canonical inputs, never uuid4() | `evaluator.py::_default_receipt_id` | `test_determinism.py` (2 tests); grep sweep found zero `uuid`/`random` usage | VERIFIED |
| EPI-INTEGRITY-DETERMINISM-002 | Assertion/scope order permutation yields identical digest | `canonical.py::canonicalize` (sorted collections) | `test_determinism.py::test_assertion_order_permutation_yields_identical_digest`, `::test_scope_order_permutation_yields_identical_digest` | VERIFIED |
| EPI-INTEGRITY-DETERMINISM-003 | Duplicate assertion IDs / scope atoms rejected, never last-wins | `evaluator.py::_reject_duplicate_assertion_ids`, `_reject_duplicate_scope_atoms` | `test_determinism.py` (2 tests) | VERIFIED |
| EPI-INTEGRITY-DETERMINISM-004 | Repeated calls with identical input produce identical receipt_id/digest | N/A (property) | `test_determinism.py::test_no_random_or_time_dependency_across_many_default_calls` (5 repeated calls) | VERIFIED |

## EPI-INTEGRITY-IMMUTABILITY

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-IMMUTABILITY-001 | Receipt/assertion metadata deeply frozen (nested dict/list) | `freeze.py::validate_and_freeze` | `test_deep_immutability.py::test_receipt_metadata_deeply_frozen` | VERIFIED |
| EPI-INTEGRITY-IMMUTABILITY-002 | Caller mutation after construction does not change digest | `freeze.py` (never aliases input) | `test_deep_immutability.py` (2 mutation tests) | VERIFIED |
| EPI-INTEGRITY-IMMUTABILITY-003 | NaN/Infinity/unsupported types rejected in metadata | `freeze.py::validate_and_freeze` | `test_deep_immutability.py` (2 tests) | VERIFIED |
| EPI-INTEGRITY-IMMUTABILITY-004 | Contract *field type annotations* use only immutable types (tuple/MappingProxyType/scalar) -- but this describes annotations, not a runtime guarantee: `IntegrityPolicy`/`ProposedAssertion`/`IntegrityProposal` are RAW/UNTRUSTED input contracts a caller may construct with a plain mutable `dict`/`set`/`list` (the annotation does not enforce it at construction). The actual immutability guarantee applies to the NORMALIZED canonical state the evaluator builds internally (`floor.normalize_policy()` for policy; `evaluator._validate_and_normalize_assertion()` + `freeze.validate_and_freeze()` for proposal/assertion metadata) and to the returned `IntegrityReceipt` (deep-frozen on output). See PHASE19_EPISTEMIC_INTEGRITY_SPEC.md's "Policy normalization" section for the corrected raw-vs-normalized-vs-canonical distinction. | `contracts.py` (annotations), `floor.py::normalize_policy`, `evaluator.py` (assertion/proposal normalization), `canonical.py` (receipt freeze) | `test_policy_normalization_closure.py` (8 tests, including a direct mutation-isolation test), `test_deep_immutability.py` (6 tests, receipt-level) | VERIFIED (corrected this closure -- the original wording overstated a compile-time annotation as a runtime guarantee for raw input contracts) |

## EPI-INTEGRITY-AUDIT

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-AUDIT-001 | Closed, typed violation reason codes (no free-form failure text as the only explanation) | `enums.py::IntegrityViolationReason` | all violation-producing tests assert on `.reason`, not string content | VERIFIED |
| EPI-INTEGRITY-AUDIT-002 | Every violation references its assertion_id/source_atom_id for provenance | `contracts.py::IntegrityViolation` | `test_canonical_cases.py`, `test_hard_state_matrix.py` (violations carry both fields) | VERIFIED |
| EPI-INTEGRITY-AUDIT-003 | `AssertionAssessment.permitted_maximum_treatment` gives an explicit correction hint | `floor.py::HARD_FLOOR_MAXIMUM_TREATMENT` | exercised implicitly by every case in `test_hard_state_matrix.py`; `AssertionAssessment` always populated | VERIFIED |
| EPI-INTEGRITY-AUDIT-004 | No raw AttributeError/TypeError/KeyError/ValueError escapes malformed input | typed `errors.py` hierarchy throughout | `test_type_boundary.py` (26 tests, including explicit no-raw-exception test) | VERIFIED |

## EPI-INTEGRITY-AUTHORITY

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-AUTHORITY-001 | Package imports no Court/policy/authority module, and no `orca.*` at all | architectural constraint | `test_no_authority.py` (2 AST-based import-scan tests) | VERIFIED |
| EPI-INTEGRITY-AUTHORITY-002 | No model/tool/network call anywhere in the package | architectural constraint | `test_no_authority.py::test_no_integrity_source_file_calls_a_model_tool_or_router` | VERIFIED |
| EPI-INTEGRITY-AUTHORITY-003 | No natural-language/keyword/regex heuristic "integrity" check | architectural constraint (structured contracts only) | `test_no_authority.py` (no NLP code present); PHASE19_EPISTEMIC_INTEGRITY_SPEC.md's explicit non-goal statement | VERIFIED |
| EPI-INTEGRITY-AUTHORITY-004 | `IntegrityReceipt` has no authority-sounding field names | `contracts.py::IntegrityReceipt` | `test_no_authority.py::test_integrity_receipt_has_no_authority_bearing_field_names` | VERIFIED |
| EPI-INTEGRITY-AUTHORITY-005 | `IntegrityStatus` never reuses Cognitive Court's 5-state verdict vocabulary | `enums.py::IntegrityStatus` | `test_no_authority.py::test_integrity_status_does_not_reuse_court_verdict_vocabulary`, `::test_integrity_status_never_produces_human_approval_required` | VERIFIED |

## Phase 17/18 compatibility

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-COMPAT-001 | Zero OCL/Phase-18 source file modified | N/A | `git diff` scope (this closure touches only `orneur/intelligence/integrity/`, `tests/integrity/`, `tests/test_packaging_invariant.py`, `docs/orneur/phase-19/`) | VERIFIED |
| EPI-INTEGRITY-COMPAT-002 | All 138 Phase-18 tests remain green | N/A | `tests/epistemic/` — 138 passed | VERIFIED |
| EPI-INTEGRITY-COMPAT-003 | All 348 OCL tests remain green | N/A | `tests/ocl/` — 348 passed | VERIFIED |
| EPI-INTEGRITY-COMPAT-004 | Phase 19 package present in built wheel, importable from isolated install | `pyproject.toml` (`packages = ["orca", "orneur"]`, unchanged, already recursive) | `test_packaging_invariant.py` (extended `REQUIRED_WHEEL_PATHS` + isolated-venv import check) | VERIFIED |
| EPI-INTEGRITY-COMPAT-005 | Phase 19 package present in built **sdist**, importable from an sdist-based isolated install | N/A | `test_packaging_invariant.py::test_sdist_contains_all_three_intelligence_packages`, `::test_isolated_install_from_sdist_can_import_integrity_and_run_cli` (added this closure) | VERIFIED |

## Strict-boundary closure (this session)

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-BOUNDARY-005 | Explicit `receipt_id` of the wrong type rejected, never silently stored | `evaluator.py::assess_integrity` (`require_string`) | `test_input_boundary_closure.py` (5 tests) | VERIFIED |
| EPI-INTEGRITY-BOUNDARY-006 | Root metadata (receipt/proposal/assertion) must be a mapping, not a scalar | `evaluator.py::_require_mapping_root` | `test_input_boundary_closure.py` (14 tests across all three metadata roots) | VERIFIED |
| EPI-INTEGRITY-BOUNDARY-007 | `proposal.metadata` validated and deep-frozen (was previously unvalidated and unused) | `evaluator.py::assess_integrity` | `test_input_boundary_closure.py::test_proposal_metadata_nested_unsupported_value_rejected` | VERIFIED |
| EPI-INTEGRITY-DIGEST-001 | `proposal_digest` binds the complete normalized proposal, including `proposal.metadata` and every `assertion.metadata` | `evaluator.py::_proposal_digest` | `test_proposal_binding_closure.py` (4 tests) | VERIFIED |
| EPI-INTEGRITY-DIGEST-002 | Metadata key-order permutation yields identical digest | `evaluator.py::_metadata_to_json_safe` + canonical JSON sorting | `test_proposal_binding_closure.py::test_metadata_key_order_permutation_yields_same_digest` | VERIFIED |
| EPI-INTEGRITY-POLICY-005 | Policy `stricter_permitted_treatments` deep-frozen before any validation/evaluation/digesting reads it | `floor.py::normalize_policy` | `test_policy_normalization_closure.py` (8 tests) | VERIFIED |
| EPI-INTEGRITY-POLICY-006 | Caller mutation of the original policy dict after a call does not retroactively change that call's already-issued receipt | `floor.py::normalize_policy` (snapshot at call time) | `test_policy_normalization_closure.py::test_caller_mutating_original_dict_after_the_call_does_not_change_a_prior_receipt` | VERIFIED |
| EPI-INTEGRITY-POLICY-007 | Empty policy override (would make a state permanently unsatisfiable) rejected | `floor.py::normalize_policy` | `test_policy_normalization_closure.py::test_empty_override_set_rejected_as_invalid_policy` | VERIFIED |
| EPI-INTEGRITY-POLICY-008 | `permitted_maximum_treatment` reflects the ACTIVE policy, not just the unmodified hard floor | `floor.py::effective_maximum_treatment`, `TREATMENT_STRENGTH_ORDER` | `test_policy_normalization_closure.py` (3 maximum-treatment tests) | VERIFIED |
| EPI-INTEGRITY-FRESHNESS-006 | Offset-naive timestamps in a freshness comparison rejected, never a raw TypeError | `floor.py::parse_aware_iso8601` | `test_freshness_timezone_closure.py` (8 tests) | VERIFIED |
| EPI-INTEGRITY-FRESHNESS-007 | Equivalent-instant timestamps at different UTC offsets compare correctly | `floor.py::is_overlay_stale` (aware-datetime subtraction) | `test_freshness_timezone_closure.py::test_two_aware_timestamps_different_offsets_same_instant_compare_correctly`, `::test_equivalent_offset_timestamps_produce_deterministic_staleness_result` | VERIFIED |
| EPI-INTEGRITY-DETERMINISM-005 | The RETURNED `IntegrityReceipt` object (not just its canonical digest) is permutation-deterministic | `evaluator.py::assess_integrity` (sorts `required_disclosures`/`violations` at construction) | `test_receipt_object_determinism_closure.py` (4 tests) | VERIFIED |

## Trusted overlay provenance closure (this session)

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-PROVENANCE-001 | `assess_integrity()` requires an explicit `overlay_trust_context: IntegrityOverlayTrustContext`, isinstance-checked, never a bare string | `overlay_trust.py::is_valid_overlay_trust_context`, `evaluator.py::assess_integrity` | `test_overlay_provenance_closure.py::test_bare_string_trust_context_rejected` | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-002 | Default/explicit `UNTRUSTED` overlay context always fails closed -- cannot be used as epistemic authority | `evaluator.py::assess_integrity` (`UntrustedOverlayRejected`) | `test_overlay_provenance_closure.py::test_untrusted_default_is_rejected_outright`, `::test_untrusted_explicit_is_rejected_outright` | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-003 | `TRUSTED_PHASE18_RUNTIME` requires a caller-supplied `expected_overlay_digest`, never derived from the overlay object being evaluated | `evaluator.py::assess_integrity` | `test_overlay_provenance_closure.py` (13 tests) | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-004 | A forged `EpistemicAssessment` (state/polarity content replaced) with UNCHANGED, correct `source_artifact_id`/`source_artifact_digest` is rejected -- the exact reproduced defect this closure fixes | `evaluator.py::assess_integrity` (`OverlayProvenanceInvalid`) | `test_overlay_provenance_closure.py::test_forged_assessment_with_correct_artifact_binding_is_now_rejected`, `::test_mutating_assessment_after_computing_trusted_digest_is_caught` | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-005 | `verify_overlay_binding()` ALONE (no provenance check) genuinely does not detect this forgery, proving the defect was real | N/A (documents the pre-fix code path directly) | `test_overlay_provenance_closure.py::test_forged_assessment_would_have_been_satisfied_under_the_old_binding_only_check` | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-006 | A real Phase-18 overlay with a correct trusted digest passes through to normal evaluation | `evaluator.py::assess_integrity` | `test_overlay_provenance_closure.py::test_real_phase18_overlay_with_correct_trusted_digest_passes_through_normally` | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-007 | `overlay.metadata`/`proposal.metadata` self-claims of trust ("trusted", "verified_overlay", "overlay_trust") have no effect | evaluator never reads either metadata field to decide trust | `test_overlay_provenance_closure.py` (2 self-elevation tests) | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-008 | Malformed overlay structure (duplicate assessments) is rejected via the trust/digest boundary, not by Phase 19 recomputing epistemic truth | `evaluator.py::assess_integrity` | `test_overlay_provenance_closure.py::test_untrusted_malformed_overlay_rejected_at_trust_boundary_first`, `::test_trusted_context_wrong_expected_digest_rejects_malformed_overlay_too` | VERIFIED |
| EPI-INTEGRITY-PROVENANCE-009 | No raw exception leakage from any forged/malformed overlay path | typed `errors.py` hierarchy | `test_overlay_provenance_closure.py::test_no_raw_exception_leakage_from_forged_or_malformed_overlay_paths` | VERIFIED |
| EPI-INTEGRITY-POLICY-009 | `normalize_policy()` validates every collection member's TYPE before ever calling `frozenset()` on it -- no raw `TypeError` for unhashable members (dict/list) | `floor.py::normalize_policy` | `test_policy_type_boundary_closure.py` (13 tests) | VERIFIED |

## Deferred / out of scope this phase

- Behavioral enforcement of a BLOCKED receipt (answer repair, forced
  abstention execution) — Phase 19 computes the receipt; a future
  consumer decides what to do with it.
- Router/escalation consumption (Phase 20).
- Compound/multi-atom assertions.
- Cryptographic overlay-provenance authentication.
