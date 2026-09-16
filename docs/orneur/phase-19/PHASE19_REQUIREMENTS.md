# Phase 19 Requirements Registry

Status values: `VERIFIED` (implemented + cited test evidence),
`IMPLEMENTED`, `DEFERRED_TO_FUTURE_PHASE`, `BLOCKED`, `UNIMPLEMENTED`.
Nothing here is marked `VERIFIED` without a cited test.

## EPI-INTEGRITY-BOUNDARY

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-INTEGRITY-BOUNDARY-001 | Overlay must pass `verify_overlay_binding()`; failure raises `OverlayBindingInvalid` | `evaluator.py::assess_integrity` | `test_trust_boundary.py` (7 tests), `test_canonical_cases.py::test_case_j_*` | VERIFIED |
| EPI-INTEGRITY-BOUNDARY-002 | Fabricated overlay with valid-looking fields still rejected | `verify_overlay_binding` (digest comparison) | `test_trust_boundary.py::test_fabricated_overlay_with_valid_looking_fields_still_rejected` | VERIFIED |
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
| EPI-INTEGRITY-IMMUTABILITY-004 | All contract dataclass fields are immutable types (tuple/MappingProxyType/scalar), never bare dict/list | `contracts.py` | code inspection (section 50 self-review); no `: dict`/`: list` field annotations found | VERIFIED |

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

## Deferred / out of scope this phase

- Behavioral enforcement of a BLOCKED receipt (answer repair, forced
  abstention execution) — Phase 19 computes the receipt; a future
  consumer decides what to do with it.
- Router/escalation consumption (Phase 20).
- Compound/multi-atom assertions.
- Cryptographic overlay-provenance authentication.
