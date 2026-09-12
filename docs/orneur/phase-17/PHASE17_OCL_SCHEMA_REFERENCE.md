# PHASE 17 — OCL Schema Reference (V1.0.0)

Field-level reference for `orneur/intelligence/ocl/`. See the master spec for normative behavior.

## Enums (`enums.py`)

- `AtomKind`: ASSERTION, OBSERVATION_REFERENCE, HYPOTHESIS, ASSUMPTION, UNKNOWN, CONFLICT,
  QUESTION, PREDICTION, ALTERNATIVE, COUNTEREXAMPLE, CAUSAL_HYPOTHESIS, TEST_PROPOSAL,
  ACTION_PROPOSAL, VERIFICATION_REQUEST, ESCALATION_REQUEST, LIMITATION, CONSTRAINT,
  DECISION_PROPOSAL.
- `RelationKind`: SUPPORTS, CONTRADICTS, DEPENDS_ON, DERIVED_FROM, REFINES, SUPERSEDES, TESTS,
  FALSIFIES, PREDICTS, EXPLAINS, CAUSES, CORRELATES_WITH, ALTERNATIVE_TO, RESOLVES,
  INTRODUCES_UNCERTAINTY, REQUIRES_EVIDENCE, MOTIVATES_ACTION, MOTIVATES_ESCALATION.
  `ACYCLIC_RELATION_KINDS = {DEPENDS_ON, DERIVED_FROM, SUPERSEDES}`.
- `SourceClass`: MODEL_ASSERTION, MEASURED_EVIDENCE_REFERENCE, EXTERNAL_EVIDENCE_REFERENCE,
  DETERMINISTIC_POLICY_REFERENCE, HUMAN_INPUT, UNKNOWN, DERIVED_COGNITIVE_PROPOSAL.
- `ProducerKind`: NATIVE_MODEL, EXTERNAL_PROVIDER, DETERMINISTIC_SYSTEM, TOOL, HUMAN,
  TRANSFORMATION.
- `EvidenceKind`: MEASURED_SYSTEM_DATA, TOOL_OUTPUT, SOURCE_DOCUMENT, CODE_TEST_EVIDENCE,
  DETERMINISTIC_POLICY_FACT, VERIFICATION_RECORD, PRODUCTION_PROOF, COURT_DECISION,
  EXTERNAL_RETRIEVAL_RESULT, HUMAN_SUPPLIED_ARTIFACT.
- `TransformationOperation`: CHALLENGE, TEST_GENERATED, EVIDENCE_ADDED, SUPERSEDE, FALSIFY, ABANDON,
  INTRODUCE_ALTERNATIVE, REMOVE_WITH_REASON, MERGE, REFINE.
- `ObserverView`: MODEL_VIEW, VERIFIER_VIEW, COURT_VIEW, HUMAN_SUMMARY_VIEW, AUDIT_VIEW,
  LEARNING_REFERENCE_VIEW.

## Types

- `CognitiveAtom(atom_id, kind, source_class, content, namespace="core", evidence_refs=(), metadata={})`
- `CognitiveRelation(relation_id, kind, source_atom_id, target_atom_id, namespace="core", metadata={})`
- `EvidenceAnchor(evidence_id, evidence_kind, issuer, reference, digest=None, observed_at=None, locator=None, metadata={})`
- `ModelIdentityRef(family=None, generation=None, checkpoint_id=None, artifact_digest=None, lifecycle_state=None, provider_id=None)`
- `Provenance(producer_kind, producer_id, model_identity=None, invocation_ref=None, schema_version=None)`
- `ActionIntent(intent_id, proposed_capability, target_reference=None, arguments_summary={}, rationale_atom_refs=(), expected_effect="", preconditions=(), verification_requirement_refs=(), risk_hints=())`
- `VerificationContract(contract_id, target_atom_ref, required_evidence_kinds=(), proposed_test="", pass_conditions=(), fail_conditions=(), verification_scope_ref=None, status="UNRESOLVED")`
- `EscalationRequest(escalation_id, triggering_atom_refs=(), reason_categories=(), unresolved_conflict_refs=(), requested_capability_type="", evidence_deficit="", requested_cognitive_role=None)`
- `CausalHypothesis(hypothesis_id, cause_atom_ref, mechanism, predicted_consequence_atom_ref, observable_test_ref=None, observed_evidence_refs=())`
- `CounterfactualBranch(branch_id, causal_hypothesis_ref, condition_atom_ref, predicted_atom_ref)`
- `CognitiveArtifact(artifact_id, schema_version, request_id, provenance, created_at, atoms=(), relations=(), evidence=(), action_intents=(), verification_contracts=(), escalation_requests=(), causal_hypotheses=(), counterfactual_branches=(), limitation_atom_refs=(), metadata={}, parent_artifact_id=None, transformation_id=None)`
- `TransformationRecord(transformation_id, parent_artifact_id, child_artifact_id, producer, operation, timestamp, schema_version, affected_atom_ids=(), created_atom_ids=(), superseded_atom_ids=(), removed_atom_ids=(), justification_refs=())`

## Error codes (`errors.py`)

`UNSUPPORTED_SCHEMA_VERSION`, `INVALID_ARTIFACT_ID`, `DUPLICATE_ATOM_ID`, `DANGLING_RELATION`,
`INVALID_RELATION_SHAPE`, `INVALID_PROVENANCE`, `FORBIDDEN_AUTHORITY_CONSTRUCT`,
`EVIDENCE_IMPERSONATION`, `INVALID_NAMESPACE`, `PAYLOAD_LIMIT_EXCEEDED`, `GRAPH_LIMIT_EXCEEDED`,
`INVALID_TRANSFORMATION`, `CONSERVATION_VIOLATION`, `INVALID_CANONICAL_FORM`,
`SECRET_CONTENT_REJECTED`.

## Limits (`limits.py`)

`MAX_ATOMS_PER_ARTIFACT=2000`, `MAX_RELATIONS_PER_ARTIFACT=4000`, `MAX_METADATA_KEYS=64`,
`MAX_METADATA_DEPTH=4`, `MAX_STRING_FIELD_LENGTH=20000`, `MAX_ARTIFACT_SERIALIZED_BYTES=8MiB`
(enforced inside `compile_artifact()` itself, after canonicalization, against the artifact's actual
canonical JSON size).
