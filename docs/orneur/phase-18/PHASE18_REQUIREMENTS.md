# Phase 18 Requirements Registry

Status values: `VERIFIED` (implemented + test evidence exists),
`IMPLEMENTED` (built, evidence indirect), `DEFERRED_TO_FUTURE_PHASE`,
`BLOCKED`, `UNIMPLEMENTED`. Nothing here is marked `VERIFIED` without a
cited test.

## EPI-STATE — closed vocabulary and semantics

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-STATE-001 | Exactly 6 closed `EpistemicState` members, no aliases/OTHER/MAYBE | `enums.py::EpistemicState` | `test_epistemic_enums.py::test_epistemic_state_has_exactly_the_six_required_members`, `::test_epistemic_state_unknown_string_fails_closed` | VERIFIED |
| EPI-STATE-002 | 4-member `EpistemicPolarity`, orthogonal to state | `enums.py::EpistemicPolarity` | `test_epistemic_enums.py::test_epistemic_polarity_has_exactly_four_members`, `test_epistemic_diff.py::test_known_affirmed_to_known_refuted_transition` | VERIFIED |
| EPI-STATE-003 | `KNOWN` requires direct qualified basis, one-sided | `resolver.py::_assess_one_atom` | `test_direct_assessment.py::test_direct_verified_support_yields_known_affirmed`, `::test_direct_verified_refutation_yields_known_refuted` | VERIFIED |
| EPI-STATE-004 | `INFERRED` requires evidence-rooted derivation, no direct basis | `resolver.py`, `graph.py` | `test_inference_graph.py::test_supports_chain_from_verified_root_yields_inferred` | VERIFIED |
| EPI-STATE-005 | `DISPUTED` requires qualified support AND qualified refutation | `resolver.py::_assess_one_atom` | `test_disputes.py::test_direct_support_and_direct_refutation_on_same_atom_yields_disputed` | VERIFIED |
| EPI-STATE-006 | `UNKNOWN` != false; no basis at all | `resolver.py` | `test_unknown_uncertain.py::test_bare_model_assertion_no_evidence_is_unknown_not_uncertain` | VERIFIED |
| EPI-STATE-007 | `UNVERIFIABLE` requires trusted structural feasibility record, high bar | `resolver.py`, `trust.py::can_mint_structurally_unverifiable` | `test_unverifiable.py` (4 tests) | VERIFIED |
| EPI-STATE-008 | `UNCERTAIN` vs `UNKNOWN` distinct decision paths | `resolver.py::_assess_one_atom` | `test_unknown_uncertain.py` (3 tests) | VERIFIED |

## EPI-EVIDENCE — resolution contract

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-EVIDENCE-001 | `EvidenceResolutionStatus`/`EvidenceStance` closed, separate enums | `enums.py` | `test_epistemic_enums.py::test_evidence_resolution_status_and_stance_closed_vocabularies` | VERIFIED |
| EPI-EVIDENCE-002 | `VERIFIED`+`SUPPORTS`/`REFUTES` establishes direct basis; `INCONCLUSIVE` never does | `resolver.py::_unresolved_reason`, `_assess_one_atom` | `test_direct_assessment.py::test_verified_inconclusive_does_not_establish_direction` | VERIFIED |
| EPI-EVIDENCE-003 | `UNVERIFIED`/`STALE`/`UNAVAILABLE` never create `KNOWN` | `resolver.py` | `test_direct_assessment.py` (3 tests) | VERIFIED |
| EPI-EVIDENCE-004 | `INVALID` invalidates the evidence basis, does not itself refute | `resolver.py::_assess_one_atom` | `test_direct_assessment.py::test_invalid_evidence_does_not_refute_only_invalidates_basis` | VERIFIED |
| EPI-EVIDENCE-005 | Resolution must target a real evidence_id referenced by that atom | `resolver.py::_validate_resolution_targets` | `test_overlay_binding.py::test_resolver_rejects_evidence_targeting_atom_not_associated_with_it`, `::test_resolver_rejects_unknown_evidence_id` | VERIFIED |
| EPI-EVIDENCE-006 | Duplicate/conflicting resolution records fail closed, no silent pick | `resolver.py::_reject_conflicting_resolutions` | `test_disputes.py::test_duplicate_evidence_reference_does_not_create_extra_certainty`, `::test_conflicting_resolution_records_fail_closed_not_silently_picked` | VERIFIED |

## EPI-TRUST — trust boundary

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-TRUST-001 | Trust context supplied out-of-band by caller, never parsed from payload | `resolver.py::assess_artifact` signature | `test_epistemic_trust.py` (5 tests) | VERIFIED |
| EPI-TRUST-002 | Bare string equal to enum value is NOT a valid trust context | `trust.py::is_valid_resolution_trust_context` (isinstance, not membership) | `test_epistemic_trust.py::test_bare_string_equal_to_member_value_is_not_a_valid_trust_context`, `test_self_elevation_attacks.py::test_fake_verified_string_with_bare_string_trust_context_is_rejected` | VERIFIED |
| EPI-TRUST-003 | `UNTRUSTED` resolution batch cannot create `KNOWN` regardless of record content | `resolver.py::assess_artifact` (`qualified` gate) | `test_direct_assessment.py::test_untrusted_resolution_context_cannot_create_known_even_with_verified_status` | VERIFIED |
| EPI-TRUST-004 | Only `TRUSTED_DETERMINISTIC_VERIFIER` may mint `UNVERIFIABLE` | `trust.py::can_mint_structurally_unverifiable` | `test_unverifiable.py::test_trusted_tool_resolver_tier_cannot_mint_unverifiable` | VERIFIED |
| EPI-TRUST-005 | `HUMAN_INPUT` SourceClass does not auto-become `KNOWN` | resolver never reads `source_class` | `test_self_elevation_attacks.py::test_human_input_source_class_does_not_become_known_without_evidence` | VERIFIED |
| EPI-TRUST-006 | Model metadata (`epistemic_state`, `confidence`, `verified`) never read by resolver | resolver never reads `atom.metadata`/`artifact.metadata` | `test_self_elevation_attacks.py` (3 metadata tests) | VERIFIED |

## EPI-GRAPH — derivation and relation semantics

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-GRAPH-001 | Only `SUPPORTS`/`DERIVED_FROM`/`FALSIFIES`/`CONTRADICTS` have defined epistemic effect; all else `NONE` | `enums.py::RELATION_EPISTEMIC_SEMANTICS`, `get_relation_semantics` | `test_epistemic_enums.py::test_unspecified_relation_kinds_default_to_none_effect`, `::test_causes_and_correlates_with_are_explicitly_none` | VERIFIED |
| EPI-GRAPH-002 | Evidence-rooted reachability, O(V+E), monotonic worklist BFS | `graph.py::compute_evidence_rooted_reachability` | `test_epistemic_performance.py` (1000-atom chain, 0.05s) | VERIFIED |
| EPI-GRAPH-003 | Circular `SUPPORTS` with no root cannot self-bootstrap into `INFERRED`/`KNOWN` | `graph.py` (root-seeded BFS) | `test_inference_graph.py::test_circular_support_with_no_evidence_root_stays_not_inferred`, `test_self_elevation_attacks.py::test_circular_support_cannot_create_known` | VERIFIED |
| EPI-GRAPH-004 | Circular `DERIVED_FROM` rejected at OCL compile time (defense in depth) | N/A (OCL `ACYCLIC_RELATION_KINDS`) | `test_inference_graph.py::test_circular_derived_from_is_already_rejected_by_ocl_before_phase_18_sees_it` | VERIFIED |
| EPI-GRAPH-005 | `EPISTEMICALLY_ASSESSABLE_ATOM_KINDS` explicit allowlist, non-assessable kinds fail closed | `enums.py`, `resolver.py::assess_artifact` | `test_overlay_binding.py::test_requesting_assessment_of_non_assessable_atom_kind_fails_closed`, `::test_non_assessable_atoms_are_silently_excluded_from_whole_artifact_assessment` | VERIFIED |

## EPI-CANON — canonicalization

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-CANON-001 | Deterministic canonical JSON, sorted collections | `canonical.py::to_canonical_json` | `test_canonicalization.py::test_permuted_atom_order_yields_same_digest` | VERIFIED |
| EPI-CANON-002 | SHA-256 digest, same input → same digest | `canonical.py::digest` | `test_canonicalization.py::test_same_input_same_output_digest` | VERIFIED |
| EPI-CANON-003 | No NaN/Infinity in canonical output | `canonical.py::to_canonical_json` (`allow_nan=False`) | `test_canonicalization.py::test_no_nan_or_infinity_in_canonical_json` | VERIFIED |
| EPI-CANON-004 | Overlay bound to exact source artifact (id + digest) | `resolver.py::verify_overlay_binding` | `test_overlay_binding.py` (3 tests), `test_self_elevation_attacks.py::test_overlay_replay_across_different_artifact_is_rejected` | VERIFIED |

## EPI-DIFF — transitions

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-DIFF-001 | Deterministic per-atom diff between two overlays | `diff.py::diff` | `test_epistemic_diff.py` (7 tests) | VERIFIED |
| EPI-DIFF-002 | All 6 required transitions exercised (UNKNOWN→UNCERTAIN, UNCERTAIN→KNOWN, KNOWN→DISPUTED, DISPUTED→KNOWN, KNOWN/AFFIRMED→KNOWN/REFUTED, UNKNOWN→UNVERIFIABLE) | `diff.py` | `test_epistemic_diff.py` (one test per transition) | VERIFIED |
| EPI-DIFF-003 | State is not monotonically increasing (new evidence can downgrade) | `diff.py` (no enforcement, pure representation) | `test_epistemic_diff.py::test_known_to_disputed_transition_new_evidence_reduces_certainty` | VERIFIED |

## EPI-SECURITY — adversarial matrix

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-SECURITY-001 | Model self-elevation via metadata has zero effect | resolver never reads metadata | `test_self_elevation_attacks.py` (11 tests) | VERIFIED |
| EPI-SECURITY-002 | Confidence value never changes result | no confidence parameter exists anywhere | `test_inference_graph.py::test_confidence_number_never_changes_result_because_no_such_input_exists` | VERIFIED |
| EPI-SECURITY-003 | Malformed containers (None/dict/str/generator) fail closed, never crash | `typecheck.py::require_sequence_container` | `test_self_elevation_attacks.py::test_malformed_types_none_dict_string_generator_are_rejected_not_crashed` | VERIFIED |
| EPI-SECURITY-004 | Wrong dataclass type in a resolution sequence rejected | `typecheck.py::require_instance` | `test_self_elevation_attacks.py::test_wrong_dataclass_type_in_resolved_evidence_sequence_is_rejected` | VERIFIED |
| EPI-SECURITY-005 | No raw AttributeError/TypeError/KeyError escapes the public boundary | typed `errors.py` hierarchy throughout | all `tests/epistemic/` files use typed `pytest.raises(errors.*)` | VERIFIED |
| EPI-SECURITY-006 | Package imports no privilege-bearing module (Court/policy/authority) | architectural constraint | `test_epistemic_architecture.py` (2 AST-based import-scan tests) | VERIFIED |

## EPI-PERF — performance

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-PERF-001 | No accidental quadratic/exponential blowup, 1000-atom synthetic graph | `graph.py` worklist BFS | `test_epistemic_performance.py` (0.048s measured) | VERIFIED |

## EPI-COMPAT — Phase 17/16 compatibility

| ID | Requirement | Implementation | Test/Evidence | Status |
|---|---|---|---|---|
| EPI-COMPAT-001 | Zero OCL schema/canonical-digest changes | no edits to `orneur/intelligence/ocl/*` | `git diff` scope; `tests/ocl/` 348 passed unchanged | VERIFIED |
| EPI-COMPAT-002 | Phase 17 OCL suite remains 0 failures | N/A | `tests/ocl/` — 348 passed | VERIFIED |
| EPI-COMPAT-003 | Phase 16 regression suite remains 0 failures | N/A | `test_phase16_*` — 30 passed | VERIFIED |
| EPI-COMPAT-004 | Phase 18 package present in built wheel, importable from isolated install | `pyproject.toml` `packages = ["orca", "orneur"]` (unchanged, already recursive) | `test_packaging_invariant.py` (extended `REQUIRED_WHEEL_PATHS` + isolated-venv import check) | VERIFIED |

## Deferred / out of scope this phase

- EPI-ENFORCEMENT-* (abstention, integrity gates, staleness enforcement) — `DEFERRED_TO_FUTURE_PHASE` (Phase 19).
- EPI-ROUTER-* (router/escalation consumption of epistemic signals) — `DEFERRED_TO_FUTURE_PHASE` (Phase 20).
- EPI-NLI-001 (claim-level natural-language entailment verifier) — `DEFERRED_TO_FUTURE_PHASE`.
- EPI-WIRE-001 (untrusted JSON wire parser for epistemic objects) — `UNIMPLEMENTED`, not built this phase; `assess_artifact()` takes typed Python objects only, matching section 42's conditional instruction.
