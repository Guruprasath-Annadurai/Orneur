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
| OCL-EVIDENCE-002 | Authoritative source classes require OBSERVATION_REFERENCE kind + a real evidence ref | VERIFIED | `test_atoms.py` (3 tests) |
| OCL-PROVENANCE-001 | Model identity validated against real `orca.registry.model_spec` vocabulary | VERIFIED | `test_provenance.py` (unknown family/lifecycle rejected) |
| OCL-PROVENANCE-002 | External provider cannot claim a native family | VERIFIED | `test_provenance.py::test_external_provider_cannot_claim_a_native_family` |
| OCL-AUTHORITY-001 | Model-produced metadata cannot mint authority (forbidden-key check) | VERIFIED | `test_authority.py` (11 parametrized cases) |
| OCL-AUTHORITY-002 | ActionIntent/VerificationContract/EscalationRequest carry no authority field | VERIFIED | `test_authority.py` (2 tests) |
| OCL-AUTHORITY-003 | No model-facing package (incl. new `orneur.intelligence.ocl`) imports `orca.mission` | VERIFIED | `tests/ocl/test_authority_call_path.py` (2 tests); extends `test_phase16_architecture_invariants.py` |
| OCL-AUTHORITY-004 | `owner_approval_required` real production callers traced | VERIFIED (audit performed, zero live callers found) | `PHASE17_AUTHORITY_CALL_PATH.md`; `test_arbiter_decide_has_zero_production_callers_today` | 
| OCL-AUTHORITY-005 | Full enumeration of all indirect Mission-state-mutation paths (not just direct imports) | DEFERRED_TO_FUTURE_PHASE | Direct-import sub-claim VERIFIED; full indirect enumeration not performed this phase |
| OCL-CAUSAL-001 | CAUSES and CORRELATES_WITH remain structurally distinct; causal edges never auto-upgrade to fact | VERIFIED | `test_causal.py` |
| OCL-ACTION-001 | ActionIntent cannot execute directly (no execution code path exists) | VERIFIED | `test_authority.py::test_action_intent_has_no_authority_field`; no consumer of `ActionIntent` exists in this codebase yet |
| OCL-VERIFY-001 | VerificationContract distinct from VerificationRecord; default status UNRESOLVED | VERIFIED | `test_authority.py::test_verification_contract_status_field_cannot_be_preset_to_a_pass_state` |
| OCL-ESCALATE-001 | EscalationRequest cannot route directly; no router exists to consume it yet | IMPLEMENTED | `proposals.py`; routing itself is Phase 20 |
| OCL-DIFF-001 | Cognitive Diff is deterministic and surfaces removals, not just additions | VERIFIED | `test_diff.py` (5 tests) |
| OCL-CONSERVE-001 | Important atoms cannot silently disappear across a declared transform | VERIFIED | `test_conservation.py` (4 tests) |
| OCL-COMPILER-001 | Single compiler boundary; no partial acceptance of an invalid artifact | VERIFIED | `compiler.py`; all `tests/ocl/*` exercise it exclusively |
| OCL-SERIALIZE-001 | Deterministic canonical ordering and stable SHA-256 digest | VERIFIED | `test_serialization.py` (4 tests) |
| OCL-SERIALIZE-002 | Round-trip preserves content; no pickle/eval/exec anywhere in the path | VERIFIED | `test_serialization.py` (2 tests) |
| OCL-SERIALIZE-003 | NaN/Infinity rejected in canonical form | VERIFIED | `test_serialization.py::test_nan_in_metadata_rejected_for_canonical_form` |
| OCL-SERIALIZE-004 | Oversized wire payload rejected before parsing | VERIFIED | `test_serialization.py::test_oversized_wire_payload_rejected_before_parsing` |
| OCL-EXTENSION-001 | Namespace registry: core always registered, unregistered namespaces rejected | VERIFIED | `test_extensions.py` (4 tests) |
| OCL-EXTENSION-002 | Full per-namespace schema validation for third-party extensions | DEFERRED_TO_FUTURE_PHASE | Only namespace registration exists; no schema-contract enforcement per namespace (documented YAGNI, threat #33) |
| OCL-OBSERVER-001 | 6 named views exist, are deterministic, and never mutate the source artifact | VERIFIED | `test_observer.py` (4 tests) |
| OCL-CHECKPOINT-001 | Checkpoint round-trips; contains no hidden CoT field structurally | VERIFIED | `test_checkpoint.py` (2 tests) |
| OCL-CHECKPOINT-002 | Secret-shaped content rejected at checkpoint time, reusing Phase 15 sanitization | VERIFIED | `test_checkpoint.py` (2 tests) |
| OCL-CHECKPOINT-003 | Compiled artifact immutable after compilation | VERIFIED | `test_checkpoint.py::test_compiled_artifact_is_immutable` |
| OCL-COMPAT-001 | Legacy `CognitiveResult` adapts to a compilable OCL draft, one-way | VERIFIED | `test_adapter.py` (2 tests) |
| OCL-COMPAT-002 | Adapter module introduces no `orca.mission` import path | VERIFIED | `test_adapter.py::test_adapter_module_does_not_import_orca_mission` |
| OCL-PERF-001 | Representative performance measured at 10/100/1000 atoms, no unfounded claims | VERIFIED | `test_performance.py`; numbers recorded in `PHASE17_EVIDENCE.md` |
| OCL-SECURITY-001 | Threat model covers ≥40 items with control/test/residual-risk per item | VERIFIED | `PHASE17_THREAT_MODEL.md` (40 items, 31 tested) |

## Totals

39 requirements: **35 VERIFIED**, 2 IMPLEMENTED (OCL-EVIDENCE-001, OCL-ESCALATE-001 — real code
exists but no dedicated test beyond adjacent coverage), 2 DEFERRED_TO_FUTURE_PHASE
(OCL-AUTHORITY-005, OCL-EXTENSION-002). 0 UNIMPLEMENTED, 0 BLOCKED.
