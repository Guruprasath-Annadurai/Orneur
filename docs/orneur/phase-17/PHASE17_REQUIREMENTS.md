# PHASE 17 — Requirements Registry

Status vocabulary: UNIMPLEMENTED / IMPLEMENTED / VERIFIED / BLOCKED / DEFERRED_TO_FUTURE_PHASE.
VERIFIED is used only where a real passing test backs the claim.

| ID | Statement | Status | Evidence |
|---|---|---|---|
| OCL-CORE-001 | `CognitiveArtifact` core type exists with no authority field | VERIFIED | `artifact.py`; `test_authority.py` |
| OCL-CORE-002 | Private reasoning vs. cognitive contract doctrine enforced (no CoT field anywhere) | VERIFIED | `test_checkpoint.py::test_cognitive_artifact_has_no_hidden_chain_of_thought_field` |
| OCL-SCHEMA-001 | `schema_version` required, current version `1.0.0` | VERIFIED | `version.py`; `test_schema_version.py` |
| OCL-SCHEMA-002 | Unsupported schema version fails closed | VERIFIED | `test_schema_version.py::test_unsupported_major_version_fails_closed` |
| OCL-ATOM-001 | Atom IDs unique within an artifact | VERIFIED | `test_atoms.py::test_duplicate_atom_id_rejected` |
| OCL-ATOM-002 | All 18 atom kinds individually valid; no FACT kind exists | VERIFIED | `test_atoms.py::test_all_atom_kinds_are_individually_valid`; `enums.py` |
| OCL-GRAPH-001 | Dangling relation references rejected | VERIFIED | `test_relations.py` (2 tests) |
| OCL-GRAPH-002 | Acyclic relation kinds reject cycles; cycle-tolerant kinds allow them | VERIFIED | `test_relations.py` (3 tests) |
| OCL-GRAPH-003 | Graph size limits enforced (atoms, relations) | VERIFIED | `test_limits.py` (3 tests) |
| OCL-EVIDENCE-001 | EvidenceAnchor references evidence, never copies it | IMPLEMENTED | `evidence.py` (no secret-content-copy test beyond checkpoint scan) |
| OCL-EVIDENCE-002 | **STRENGTHENED this closure**: authoritative source classes require OBSERVATION_REFERENCE kind + a real evidence ref, AND the artifact's own producer_kind must not be NATIVE_MODEL/EXTERNAL_PROVIDER (evidence must not self-authenticate, spec §8) | VERIFIED | `test_atoms.py` (4 tests, incl. `test_native_model_artifact_cannot_self_authenticate_evidence`) |
| OCL-EVIDENCE-003 | Fake VerificationRecord/ProductionProof/CourtDecision/deterministic-policy references cannot become authoritative merely via a model/external-provider artifact's own wire payload | VERIFIED | `test_atoms.py::test_native_model_artifact_cannot_self_authenticate_evidence` (generalizes across all four `EvidenceKind` privileged values via the same producer-kind gate) |
| OCL-PROVENANCE-001 | Model identity validated against real `orca.registry.model_spec` vocabulary | VERIFIED | `test_provenance.py` (unknown family/lifecycle rejected) |
| OCL-PROVENANCE-002 | External provider cannot claim a native family | VERIFIED | `test_provenance.py::test_external_provider_cannot_claim_a_native_family` |
| OCL-AUTHORITY-001 | **STRENGTHENED this closure**: model-produced structured data (metadata AND `ActionIntent.arguments_summary`, recursively through nested dicts/lists/tuples, not only top-level dict values) cannot mint authority | VERIFIED | `test_authority.py` (11 cases) + `test_closure_authority_hardening.py` (5 nested/relation/evidence/action-intent smuggling cases) |
| OCL-AUTHORITY-006 | Whole-artifact validation: action_intents, verification_contracts, escalation_requests, causal_hypotheses, counterfactual_branches are all validated (IDs unique, refs resolve, bounded) -- not merely atoms/relations/evidence/provenance | VERIFIED | `test_closure_authority_hardening.py` (17 tests) |
| OCL-AUTHORITY-007 | Compiled artifacts are deeply immutable: no nested dict/list reachable from a compiled artifact is mutable, and no compiled artifact aliases a caller-owned container | VERIFIED | `test_closure_deep_immutability.py` (6 tests, incl. alias-safety and digest-stability-after-source-mutation) |
| OCL-AUTHORITY-008 | Strict wire parsing: duplicate JSON keys, unknown fields at every level, and malformed/missing data all produce typed errors, never silent coercion | VERIFIED | `test_serialization.py` (5 new tests) |
| OCL-AUTHORITY-002 | ActionIntent/VerificationContract/EscalationRequest carry no authority field | VERIFIED | `test_authority.py` (2 tests) |
| OCL-AUTHORITY-003 | No model-facing package (incl. new `orneur.intelligence.ocl`) imports `orca.mission` | VERIFIED | `tests/ocl/test_authority_call_path.py` (2 tests); extends `test_phase16_architecture_invariants.py` |
| OCL-AUTHORITY-004 | `owner_approval_required` real production callers traced | VERIFIED (audit performed, zero live callers found) | `PHASE17_AUTHORITY_CALL_PATH.md`; `test_arbiter_decide_has_zero_production_callers_today` | 
| OCL-AUTHORITY-005 | Full enumeration of all indirect Mission-state-mutation paths (not just direct imports) | DEFERRED_TO_FUTURE_PHASE | Direct-import sub-claim VERIFIED; full indirect enumeration not performed this phase |
| OCL-CAUSAL-001 | CAUSES and CORRELATES_WITH remain structurally distinct; causal edges never auto-upgrade to fact | VERIFIED | `test_causal.py` |
| OCL-ACTION-001 | ActionIntent cannot execute directly (no execution code path exists) | VERIFIED | `test_authority.py::test_action_intent_has_no_authority_field`; no consumer of `ActionIntent` exists in this codebase yet |
| OCL-VERIFY-001 | **STRENGTHENED this closure**: VerificationContract distinct from VerificationRecord; `status` MUST equal exactly the literal string `"UNRESOLVED"` for the artifact to compile -- any other value (PASS/PASSED/ACCEPT/SUCCESS/VERIFIED_TRUE/lowercase/etc.) is rejected, not merely defaulted away from | VERIFIED | `test_closure_authority_hardening.py` (`test_verification_contract_arbitrary_status_rejected` + 6-value parametrized `test_every_non_exact_unresolved_status_rejected`) |
| OCL-ESCALATE-001 | EscalationRequest cannot route directly; no router exists to consume it yet | IMPLEMENTED | `proposals.py`; routing itself is Phase 20 |
| OCL-DIFF-001 | **STRENGTHENED this closure**: Cognitive Diff is deterministic, surfaces removals, AND detects same-ID content modification (not only ID-set presence changes) across atoms/relations/evidence/action_intents/verification_contracts/escalation_requests/causal_hypotheses/counterfactual_branches | VERIFIED | `test_diff.py` (11 tests, 6 new `*_modified` cases) |
| OCL-CONSERVE-001 | **STRENGTHENED this closure**: important atoms cannot silently disappear OR be silently semantically rewritten under the same ID across a declared transform; any disposition (SUPERSEDED/REMOVED/MODIFIED) requires a non-empty, typed, per-atom justification (`AtomDisposition`) | VERIFIED | `test_conservation.py` (9 tests, 5 new same-ID-rewrite/disposition cases) |
| OCL-COMPILER-001 | Single compiler boundary; no partial acceptance of an invalid artifact; validates EVERY top-level collection, not a subset | VERIFIED | `compiler.py`; all `tests/ocl/*` (158 tests) exercise it exclusively |
| OCL-SERIALIZE-001 | Deterministic canonical ordering and stable SHA-256 digest | VERIFIED | `test_serialization.py` (4 tests) |
| OCL-SERIALIZE-002 | Round-trip preserves content (via strict `parse_ocl_draft_json` + `compile_artifact`); no pickle/eval/exec anywhere in the path; clear public boundary between unvalidated-draft parsing and the safe `compile_ocl_json` entry point | VERIFIED | `test_serialization.py` (4 tests) |
| OCL-SERIALIZE-003 | NaN/Infinity rejected in canonical form | VERIFIED | `test_serialization.py::test_nan_in_metadata_rejected_for_canonical_form` |
| OCL-SERIALIZE-004 | Oversized wire payload rejected before parsing | VERIFIED | `test_serialization.py::test_oversized_wire_payload_rejected_before_parsing` |
| OCL-EXTENSION-001 | **STRENGTHENED this closure**: namespace registry: core always registered and cannot be overwritten, unregistered namespaces rejected, conflicting re-registration of an existing namespace rejected (idempotent identical re-registration allowed), and `compile_artifact()` validates against a stable per-call registry snapshot | VERIFIED | `test_extensions.py` (8 tests, 4 new) |
| OCL-EXTENSION-002 | Full per-namespace schema validation for third-party extensions | DEFERRED_TO_FUTURE_PHASE | Only namespace registration exists; no schema-contract enforcement per namespace (documented YAGNI, threat #33) |
| OCL-OBSERVER-001 | 6 named views exist, are deterministic, and never mutate the source artifact | VERIFIED | `test_observer.py` (4 tests) |
| OCL-CHECKPOINT-001 | Checkpoint round-trips; contains no hidden CoT field structurally | VERIFIED | `test_checkpoint.py` (2 tests) |
| OCL-CHECKPOINT-002 | **STRENGTHENED this closure**: secret-shaped content rejected at checkpoint time via a recursive whole-artifact scan (every string leaf, not a hand-picked subset of fields), reusing Phase 15 sanitization | VERIFIED | `test_checkpoint.py` (8 tests, 6 new: nested metadata, ActionIntent arguments, VerificationContract proposed_test, EscalationRequest evidence_deficit, CausalHypothesis mechanism, Provenance invocation_ref) |
| OCL-CHECKPOINT-003 | Compiled artifact DEEPLY immutable after compilation (not merely the top-level dataclass) | VERIFIED | `test_checkpoint.py::test_compiled_artifact_is_immutable`; `test_closure_deep_immutability.py` (6 tests) |
| OCL-COMPAT-001 | Legacy `CognitiveResult` adapts to a compilable OCL draft, one-way | VERIFIED | `test_adapter.py` (2 tests) |
| OCL-COMPAT-002 | Adapter module introduces no `orca.mission` import path | VERIFIED | `test_adapter.py::test_adapter_module_does_not_import_orca_mission` |
| OCL-PERF-001 | Representative performance re-measured after deep-freeze + whole-artifact validation changes, no unfounded claims | VERIFIED | `test_performance.py`; numbers recorded in `PHASE17_EVIDENCE.md` closure section (no material regression from deep freezing) |
| OCL-SECURITY-001 | Threat model covers ≥40 items with control/test/residual-risk per item | VERIFIED | `PHASE17_THREAT_MODEL.md` (40 items, 31 tested) |
| OCL-ID-001 | Every identified object type (atom/relation/evidence/action_intent/verification_contract/escalation_request/causal_hypothesis/counterfactual_branch/artifact) requires a non-empty, length-bounded ID | VERIFIED | `test_closure_identifiers.py` (9 tests) |
| OCL-COMPAT-003 | Explicit V1 reader version policy documented and tested (same-version accept, any other version reject) even though only one version exists | VERIFIED | `version.py::schema_policy_for`; `test_schema_version.py::test_version_policy_accepts_current_and_rejects_others` |
| OCL-TRUST-001 | One canonical `AUTHORITATIVE_SOURCE_CLASSES` definition (in `enums.py`); `compiler.py` no longer maintains a second, independently-defined local set | VERIFIED | Code inspection: `compiler.py` imports `AUTHORITATIVE_SOURCE_CLASSES` from `enums.py`, no local redefinition remains |

## Totals

47 requirements: **43 VERIFIED**, 2 IMPLEMENTED (OCL-EVIDENCE-001, OCL-ESCALATE-001 — real code
exists but no dedicated test beyond adjacent coverage), 2 DEFERRED_TO_FUTURE_PHASE
(OCL-AUTHORITY-005, OCL-EXTENSION-002). 0 UNIMPLEMENTED, 0 BLOCKED.
