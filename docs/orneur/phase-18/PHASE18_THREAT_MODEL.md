# Phase 18 Threat Model

Each threat maps to the implementation mechanism that closes it and the
test that exercises the closure. Where a threat is closed by OCL itself
(defense in depth, one layer earlier than Phase 18's own resolver), that
is stated explicitly rather than claimed as a Phase 18 mechanism.

| # | Threat | Mechanism | Test |
|---|---|---|---|
| 1 | Self-authenticated model certainty (`metadata={"epistemic_state": "KNOWN"}`) | Resolver never reads `atom.metadata`/`artifact.metadata` at all — evidence arrives only via the explicit `resolved_evidence` parameter | `test_self_elevation_attacks.py::test_model_self_elevation_metadata_epistemic_state_known_is_ignored` |
| 2 | Model confidence attack (`metadata={"confidence": 1.0}`) | No confidence parameter exists anywhere in the signature; same input at any confidence value resolves identically | `test_self_elevation_attacks.py::test_model_confidence_attack_metadata_confidence_one_is_ignored`, `test_inference_graph.py::test_confidence_number_never_changes_result_because_no_such_input_exists` |
| 3 | Fake `verified=True` metadata | Closed one layer earlier: `"verified"` is one of OCL's own `FORBIDDEN_METADATA_KEYS` — the artifact fails to compile at all | `test_self_elevation_attacks.py::test_metadata_verified_true_is_rejected_by_ocl_before_phase_18_sees_it` |
| 4 | Fake trusted-string context (`trust_context="TRUSTED_DETERMINISTIC_VERIFIER"` as a bare `str`) | `trust.is_valid_resolution_trust_context()` uses `isinstance()`, rejecting any value that is not a genuine `EpistemicResolutionTrustContext` member | `test_epistemic_trust.py::test_bare_string_equal_to_member_value_is_not_a_valid_trust_context`, `test_self_elevation_attacks.py::test_fake_verified_string_with_bare_string_trust_context_is_rejected` |
| 5 | Fake privileged SourceClass (model claims `MEASURED_EVIDENCE_REFERENCE`) | Closed by OCL's own `SOURCE_CLASS_CAPABILITY_MATRIX` under an `UNTRUSTED_MODEL_OR_WIRE` compilation context; even if it compiled, Phase 18 never reads `source_class` | `test_self_elevation_attacks.py::test_fake_privileged_sourceclass_model_writes_measured_evidence_reference` |
| 6 | Human-authority confusion (`HUMAN_INPUT` → automatic `KNOWN`) | Resolver never reads `source_class`; a `HUMAN_INPUT` atom with no evidence resolves `UNKNOWN` like any other | `test_self_elevation_attacks.py::test_human_input_source_class_does_not_become_known_without_evidence` |
| 7 | Circular `SUPPORTS` (`A supports B; B supports A`, no root) | Evidence-rooted worklist BFS seeded only from direct qualified roots; a cycle with no external root gets no member added | `test_inference_graph.py::test_circular_support_with_no_evidence_root_stays_not_inferred`, `test_self_elevation_attacks.py::test_circular_support_cannot_create_known` |
| 8 | Circular `DERIVED_FROM` | Closed one layer earlier: `DERIVED_FROM` is in OCL's `ACYCLIC_RELATION_KINDS`; the artifact fails OCL compilation | `test_inference_graph.py::test_circular_derived_from_is_already_rejected_by_ocl_before_phase_18_sees_it` |
| 9 | Evidence stuffing (same `evidence_id` duplicated many times) | `resolver._reject_conflicting_resolutions` treats any repeated `(target_atom_id, evidence_id)` key as an error, fails closed rather than vote-counting | `test_disputes.py::test_duplicate_evidence_reference_does_not_create_extra_certainty` |
| 10 | Conflict hiding (qualified support + qualified refutation coexist, expecting one to silently win) | Precedence rule: both present → `DISPUTED`, never silently resolved to one side | `test_disputes.py::test_direct_support_and_direct_refutation_on_same_atom_yields_disputed` |
| 11 | Fake `UNVERIFIABLE` (model limitation text claims impossibility) | No code path reads `atom.content`/`metadata` to build a `VerificationFeasibilityRecord`; only an explicit, separately-typed, trusted-tier record can | `test_unverifiable.py::test_model_limitation_text_alone_cannot_create_unverifiable` |
| 12 | Overlay replay (an overlay for artifact A reused against artifact B) | `verify_overlay_binding()` checks both `source_artifact_id` and `source_artifact_digest`; mismatch raises `SourceArtifactMismatch` | `test_overlay_binding.py` (3 tests), `test_self_elevation_attacks.py::test_overlay_replay_across_different_artifact_is_rejected` |
| 13 | Artifact/overlay mismatch after mutation | Same mechanism as #12 — digest changes whenever content changes | `test_overlay_binding.py::test_overlay_rejects_binding_to_mutated_artifact_content` |
| 14 | Malformed serialized/wire data (`None`, `dict`, `str`, generator passed where a sequence is expected) | `typecheck.require_sequence_container`/`require_instance` raise typed `errors.EpistemicError` subclasses, never a raw `TypeError`/`AttributeError` | `test_self_elevation_attacks.py::test_malformed_types_none_dict_string_generator_are_rejected_not_crashed`, `::test_wrong_dataclass_type_in_resolved_evidence_sequence_is_rejected` |
| 15 | Authority escalation through epistemic labels (`if state == KNOWN: allow_execution()`) | No such code path exists anywhere in this repository's execution/policy/Court modules — enforced structurally by an import-scan test on the package itself | `test_epistemic_architecture.py` (2 tests) |
| 16 | Chain-of-thought exposure | OCL never stores raw CoT; `explain_assessment()` only formats already-structured `EpistemicAssessment` fields | `explain.py` (no free-text model-supplied field is ever surfaced) |
| 17 | Non-deterministic assessment (same input, different output across runs/orderings) | Canonical sort + worklist BFS with no dict-iteration-order dependence; `assessed_at`/`overlay_id` are explicit inputs, never `datetime.now()`/`uuid4()` reads inside canonicalization | `test_canonicalization.py::test_same_input_same_output_digest`, `::test_permuted_atom_order_yields_same_digest` |
| 18 | Stale evidence treated as current | `EvidenceResolutionStatus.STALE` is an explicit status a trusted resolver must report; the canonical resolver applies no universal wall-clock freshness heuristic | `test_direct_assessment.py::test_stale_evidence_yields_uncertain` |
| 19 | Conflicting resolution injection (same key, `VERIFIED SUPPORTS` and `VERIFIED REFUTES`) | Fails closed with `ConflictingEvidenceResolution` rather than silently picking one | `test_disputes.py::test_conflicting_resolution_records_fail_closed_not_silently_picked` |
| 20 | `CAUSES`/`CORRELATES_WITH` treated as truth-propagating | Explicitly mapped to `RelationEffect.NONE`; only 4 relation kinds carry effect, everything else fails closed | `test_inference_graph.py::test_causes_relation_does_not_propagate_truth`, `::test_correlates_with_relation_does_not_propagate_truth`, `test_epistemic_enums.py::test_causes_and_correlates_with_are_explicitly_none` |
| 21 | Non-propositional atom kinds (QUESTION, ACTION_PROPOSAL, etc.) silently assigned truth polarity | `EPISTEMICALLY_ASSESSABLE_ATOM_KINDS` explicit allowlist; requesting assessment of an excluded kind raises `NonAssessableAtomKind`, whole-artifact assessment silently skips them | `test_overlay_binding.py::test_requesting_assessment_of_non_assessable_atom_kind_fails_closed`, `::test_non_assessable_atoms_are_silently_excluded_from_whole_artifact_assessment` |
| 22 | Untrusted `TRUSTED_TOOL_RESOLVER`-tier record minting `UNVERIFIABLE` | Only `TRUSTED_DETERMINISTIC_VERIFIER` is in `STRUCTURALLY_UNVERIFIABLE_CAPABLE_CONTEXTS` | `test_unverifiable.py::test_trusted_tool_resolver_tier_cannot_mint_unverifiable` |
| 23 | Resolution record targets an evidence anchor not actually referenced by that atom | `_validate_resolution_targets` cross-checks `atom.evidence_refs` | `test_overlay_binding.py::test_resolver_rejects_evidence_targeting_atom_not_associated_with_it` |

## Residual / known-open (documented, not silently claimed solved)

- No cryptographic proof that the runtime caller genuinely deserved the
  `EpistemicResolutionTrustContext` it supplied — this is an
  invocation-boundary concern, structurally identical to OCL's own
  `CompilationTrustContext` doctrine (the caller of `compile_artifact()`
  is trusted to pass the right context; OCL doesn't authenticate it
  either).
- Prompt-injection-shaped content inside an atom's `content` free-text
  field is not scanned by Phase 18 (same residual OCL already documents
  for its own `content` field — a downstream-consumer responsibility,
  not a compiler/resolver guarantee).
- No claim-level natural-language entailment check — "qualified"
  evidence is qualified by trust tier and status/stance, not by an
  automated judgment that the evidence text actually supports the
  atom's content.
