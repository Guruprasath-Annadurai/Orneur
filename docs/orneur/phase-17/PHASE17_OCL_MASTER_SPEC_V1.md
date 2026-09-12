# ORNEUR Cognitive Language (OCL) — Master Specification V1

Status: Phase 17 implementation, schema version `1.0.0`. Normative terms (MUST/MUST NOT/SHOULD/
SHOULD NOT/MAY) follow RFC 2119 usage.

## 1. Purpose

OCL is a typed, evidence-bearing, model-independent Cognitive Intermediate Representation. It lets
ORNEUR's native intelligences (Genesis, Novus, Aeternum) and external/deterministic systems
exchange structured cognition — claims, evidence references, hypotheses, causal structure,
proposed actions — as an inspectable artifact, without exposing private chain-of-thought and
without transferring execution authority.

## 2. Non-goals (this phase)

OCL V1 does NOT implement: epistemic-state semantics (Phase 18), confidence calibration, the
Intelligence Escalation Reflex algorithm, the Genesis/Novus/Aeternum router (Phase 20), model
training of any kind, Twin Distillation, Failure Genome, Outcome Memory, Capability Delta learning,
self-improvement, model-society orchestration, production model promotion, or public OCL release.
Every one of these is a real future phase's job, not something OCL V1 approximates or fakes.

## 3. Terminology

- **Artifact**: one `CognitiveArtifact` instance — a versioned, compiled cognitive graph.
- **Atom**: the smallest typed cognitive unit (`CognitiveAtom`).
- **Relation**: a typed directed edge between atoms (`CognitiveRelation`).
- **Compile**: the act of validating a draft artifact and producing a canonical, immutable one
  (`compiler.compile_artifact`).
- **Canonicalize**: deterministic reordering of an artifact's collections with no content change.
- **Proposal**: `ActionIntent`, `VerificationContract`, or `EscalationRequest` — a request, never a
  grant.

## 4. Private reasoning vs. cognitive contract

A model MAY reason internally however its architecture requires. OCL MUST NOT require raw hidden
chain-of-thought, private scratchpad disclosure, token-by-token reasoning logs, hidden activation
serialization, or model-specific CoT formatting. `CognitiveArtifact` and every type it is built from
(`graph.py`, `proposals.py`, `causal.py`) has no field for any of this — confirmed by
`tests/ocl/test_checkpoint.py::test_cognitive_artifact_has_no_hidden_chain_of_thought_field`, a
structural test over the dataclass's own field names.

The doctrine: private reasoning → OCL cognitive contract → deterministic validation (this
document's compiler) → governance/verification/routing (Phase 15/16/20 systems, unchanged) →
authorized execution only if separately granted. OCL never sits directly between "model" and
"authority."

## 5. OCL is untrusted data

Every model-produced OCL object MUST be treated as untrusted data by every consumer. A model
writing `authority_granted`, `verified`, `policy_allows`, `human_approved`, `production_ready`, or
equivalent MUST NOT create the corresponding real-world fact. The compiler's single recursive
`validate_structured_value()` (`compiler.py`) enforces this across EVERY structured-data surface —
artifact/atom/relation/evidence metadata and `ActionIntent.arguments_summary` — recursing through
nested dicts, lists, AND tuples, so a forbidden key wrapped inside a list cannot bypass the check.
See §17 for the one documented residual risk this does not close (the same claim phrased as free
`content` text, not a structured key).

`ActionIntent`, `VerificationContract`, and `EscalationRequest` MUST NOT carry any field capable of
holding a grant, lease, decision, or approval — verified structurally by
`tests/ocl/test_authority.py::test_action_intent_has_no_authority_field`. `VerificationContract`'s
`status` MUST equal exactly `"UNRESOLVED"` for the artifact to compile — the compiler rejects any
other value (PASS/ACCEPT/SUCCESS/etc.), not merely defaulting away from it.

**Evidence must not self-authenticate** (closure-hardened): an atom may only claim an authoritative
`SourceClass` (`MEASURED_EVIDENCE_REFERENCE`/`EXTERNAL_EVIDENCE_REFERENCE`/
`DETERMINISTIC_POLICY_REFERENCE`) when the ARTIFACT's own `provenance.producer_kind` is NOT
`NATIVE_MODEL` or `EXTERNAL_PROVIDER`. A model or external provider cannot cause its own claimed
evidence to become authoritative merely by constructing the wire payload — only an artifact
produced by a trusted system (`DETERMINISTIC_SYSTEM`, `TOOL`, `TRANSFORMATION`, or `HUMAN`) may
carry such a claim, and even then the referenced evidence's actual resolution remains a consumer
concern, not something OCL itself authenticates.

## 6. Core type system

See `docs/orneur/phase-17/PHASE17_OCL_SCHEMA_REFERENCE.md` for the field-level reference. Summary:

- `CognitiveArtifact` (`artifact.py`): the top-level object. No authority field exists anywhere in
  its shape.
- `CognitiveAtom` (`graph.py`): `atom_id`, `kind` (`AtomKind`), `source_class` (`SourceClass`),
  `content`, `namespace`, `evidence_refs`, `metadata`.
- `CognitiveRelation` (`graph.py`): `relation_id`, `kind` (`RelationKind`), `source_atom_id`,
  `target_atom_id`, `namespace`, `metadata`.
- `EvidenceAnchor` (`evidence.py`): a reference to evidence, never a copy of it.
- `ActionIntent`, `VerificationContract`, `EscalationRequest` (`proposals.py`): proposal-only types.
- `CausalHypothesis`, `CounterfactualBranch` (`causal.py`).
- `Provenance`, `ModelIdentityRef` (`provenance.py`).
- `TransformationRecord` (`transformations.py`).

`AtomKind` deliberately has NO `FACT` member. An authoritative fact MUST be represented as an
`EvidenceAnchor` reference from an `OBSERVATION_REFERENCE` atom, never as free atom text.

## 7. Trust/source classification (§10 of the Phase 17 prompt)

Every atom carries a `SourceClass`: `MODEL_ASSERTION`, `MEASURED_EVIDENCE_REFERENCE`,
`EXTERNAL_EVIDENCE_REFERENCE`, `DETERMINISTIC_POLICY_REFERENCE`, `HUMAN_INPUT`, `UNKNOWN`,
`DERIVED_COGNITIVE_PROPOSAL`. **`SourceClass` is a provenance/reference classification, NOT an
epistemic-truth judgment** — `HUMAN_INPUT` is not automatically authoritative truth or approval,
`EXTERNAL_EVIDENCE_REFERENCE` is not automatically verified, `MEASURED_EVIDENCE_REFERENCE` means a
claimed/referenced measurement exists (not that every conclusion drawn from it is correct), and
`DETERMINISTIC_POLICY_REFERENCE` may refer to a real policy fact only once an out-of-band trusted
resolver establishes it. Phase 18 owns actual epistemic states (KNOWN/INFERRED/UNCERTAIN/DISPUTED/
UNKNOWN/UNVERIFIABLE); no `SourceClass` value here is, or should ever be treated as, one of those.

`enums.PRIVILEGED_REFERENCE_SOURCE_CLASSES` (three values: `MEASURED_EVIDENCE_REFERENCE`,
`EXTERNAL_EVIDENCE_REFERENCE`, `DETERMINISTIC_POLICY_REFERENCE` — renamed from an earlier draft's
overclaiming `AUTHORITATIVE_SOURCE_CLASSES`, and deliberately excluding `HUMAN_INPUT`) MUST only be
claimed by an `OBSERVATION_REFERENCE` atom that also cites at least one real `EvidenceAnchor`, AND
ONLY when the compile call's `trust.CompilationTrustContext` is one of the TRUSTED values (see §10)
— never merely by parsing the artifact's own `provenance.producer_kind`. `HUMAN_INPUT` is not in
this set at all: a human may honestly label any atom kind (assertion, hypothesis, question, ...) as
`HUMAN_INPUT` without it needing to look like an evidence reference, and `HUMAN_INPUT`/
`ProducerKind.HUMAN` can NEVER satisfy `HUMAN_APPROVAL_REQUIRED`, Court approval, policy
authorization, or Production Proof through OCL alone — those remain exclusively Phase 15's
deterministic artifacts and paths.

## 8. Graph semantics

`CognitiveAtom`/`CognitiveRelation` form a graph, not a linear transcript. Atom IDs MUST be unique
within an artifact (`DuplicateAtomId`). Relations MUST reference existing atoms (`DanglingRelation`).
`ACYCLIC_RELATION_KINDS` (`DEPENDS_ON`, `DERIVED_FROM`, `SUPERSEDES`) MUST NOT form a cycle
(`InvalidRelationShape`, detected via DFS in `compiler._detect_cycle`); all other relation kinds MAY
cycle (e.g. two atoms may mutually `CONTRADICT` each other). The graph MUST NOT exceed
`limits.MAX_ATOMS_PER_ARTIFACT` / `MAX_RELATIONS_PER_ARTIFACT`.

## 9. Evidence semantics

An `EvidenceAnchor` references evidence; it never creates it. Anchors MUST NOT carry secret/raw
credential content — they carry an opaque `reference`/`locator`, not the underlying sensitive
payload. `EvidenceKind` distinguishes measured system data, tool output, source documents,
code/test evidence, deterministic policy facts, `VerificationRecord`, Production Proof,
`CourtDecision`, external retrieval results, and human-supplied artifacts.

## 10. Provenance and the out-of-band trust boundary

`Provenance.producer_kind` is one of `NATIVE_MODEL`, `EXTERNAL_PROVIDER`, `DETERMINISTIC_SYSTEM`,
`TOOL`, `HUMAN`, `TRANSFORMATION`. **`producer_kind` (and every other `Provenance` field) is a CLAIM
ABOUT ORIGIN made BY the artifact — it is NOT authentication, authorization, trust, verification, or
human approval.** An untrusted wire payload can freely set `producer_kind="DETERMINISTIC_SYSTEM"`;
that claim alone unlocks nothing.

Trust is decided EXCLUSIVELY by `trust.CompilationTrustContext`, a value the CALLER of
`compiler.compile_artifact()` supplies out-of-band — never parsed from the artifact. `compile_artifact(draft,
*, trust_context=...)` defaults to `UNTRUSTED_MODEL_OR_WIRE`; the public untrusted-wire entry point
`canonical.compile_ocl_json()` hardcodes this default with no way for any field inside the parsed
JSON to elevate it. Only a caller who has independently, out-of-band, established that a draft
genuinely came from a deterministic system/tool adapter/human may pass a stronger
`CompilationTrustContext` (`TRUSTED_DETERMINISTIC_SYSTEM`, `TRUSTED_TOOL_ADAPTER`,
`TRUSTED_HUMAN_INPUT`) directly to `compile_artifact()`. This is the root fix for a real,
independently-audited bypass: the previous closure derived trust from `provenance.producer_kind`
itself, which is exactly the in-band data an attacker/model controls.

`ModelIdentityRef.family`/`lifecycle_state` MUST resolve against the real
`orca.registry.model_spec.MODEL_SPECS`/`LifecycleState` vocabulary — OCL introduces no second
model-lifecycle vocabulary. `EXTERNAL_PROVIDER` MUST NOT claim a native `family`
(`InvalidProvenance`) — an external frontier response can never be relabeled native. `NATIVE_MODEL`
MUST supply a `model_identity` with a `family` set.

## 11. Causal semantics

A `CausalHypothesis` is always a hypothesis — OCL has no mechanism to promote one to established
causality; only a future phase's evidence-threshold policy (Phase 18+) could do that, and even then
the promotion decision is external to OCL. `CAUSES` and `CORRELATES_WITH` remain structurally
distinct `RelationKind` values (§8); a model choosing `CAUSES` never thereby proves causation.
`CounterfactualBranch` expresses "IF condition differed THEN prediction should differ BECAUSE
hypothesis" without implementing Novus/Aeternum's own counterfactual reasoning algorithms.

## 12. Action intents

`ActionIntent` represents proposed work only (§5). Execution remains entirely owned by the existing
deterministic Mission/Policy/Authority path (`orca.agent.policy`, `orca.mission`) — OCL objects are
inputs those systems MAY choose to consult, never a bypass.

## 13. Verification contracts

`VerificationContract` is a request/contract — what would establish or falsify a claim — never a
`orca.mission.verification.VerificationRecord` itself. Its `status` field defaults to, and OCL never
sets it away from, `"UNRESOLVED"` (`test_authority.py::test_verification_contract_status_field_cannot_be_preset_to_a_pass_state`).

## 14. Escalation requests

`EscalationRequest` is a cognitive request for deeper intelligence. Phase 17 does NOT decide
routing; the Phase 20 router MAY later consume this. `requested_cognitive_role` is advisory text,
never a router command, and there is no field for the model to set its own cost budget or
authority.

## 15. Transformation / conservation model

A `TransformationRecord` documents one artifact-to-artifact transform. Cognitive Conservation (§13
of the Phase 17 prompt): an atom whose `kind` is in the documented `IMPORTANT_ATOM_KINDS` set
(`transformations.py`) MUST either persist into the child artifact or be explicitly recorded as
superseded/removed in the transformation — an unrecorded disappearance raises
`ConservationViolation`. Procedural/scaffolding kinds (QUESTION, UNKNOWN, LIMITATION, CONSTRAINT,
OBSERVATION_REFERENCE, TEST_PROPOSAL, VERIFICATION_REQUEST, ESCALATION_REQUEST) are explicitly
excluded from this V1 tracking scope — documented as a conservative first definition, not a final
one.

## 16. Cognitive Diff

`diff(a, b)` (`diff.py`) computes a deterministic structural diff: atoms/relations/evidence/action
intents/limitations added or removed, and whether provenance changed. It never infers semantic
truth beyond artifact presence — "hypothesis promoted" is not a concept this diff invents.

## 17. Compiler

`compiler.compile_artifact()` is the only module allowed to accept or reject an artifact. It is
deterministic and model-independent: it never decides whether a claim is true, never executes
anything, never issues authority, never calls a model, never trains a model. It performs: schema
version check, ID/reference validation, provenance validation, atom/relation/graph-size validation,
forbidden-metadata-key rejection, evidence-impersonation rejection, namespace validation, then
canonicalization.

**Documented residual risk**: the forbidden-authority-construct check operates on structured
`metadata` keys, not on free-form `content` text. A model that writes the sentence "human approval
has been granted" inside an atom's `content` string is not structurally blocked by this compiler —
that is a downstream consumer's responsibility (the observer views and any human-facing renderer
must not treat atom `content` as authoritative regardless of its wording). See
`PHASE17_THREAT_MODEL.md` threats #22/#25.

## 18. Serialization / versioning

`canonical.py` provides `to_canonical_json()` (deterministic key-sorted JSON, `allow_nan=False`),
`digest()` (SHA-256 over the canonical JSON, stdlib-only, no custom cryptography, no claim of
cryptographic authentication), and `artifact_from_dict()`/`artifact_from_canonical_json()` for safe
parsing (plain dict/list traversal only — no `pickle`, `eval`, or `exec` anywhere in the
serialization path, verified by `test_serialization.py::test_no_pickle_used_anywhere_in_serialization_module`).

`schema_version` MUST be present. An unsupported version fails closed
(`version.is_supported_schema_version`, `UnsupportedSchemaVersion`) — this build recognizes only
`1.0.0`. Migration policy for V1→V(N+1) is deferred; no speculative V2 fields exist in this
implementation.

## 19. Extension mechanism

`extensions.py` maintains a namespace registry. `core` is always registered. An atom/relation using
an unregistered `namespace` is rejected (`InvalidNamespace`). One test extension namespace
(`test_ext`, registered only inside `tests/ocl/test_extensions.py`) proves the mechanism; no
medical/legal/software taxonomy is built in Phase 17.

## 20. Observer views

`observer.project(artifact, view)` returns a deterministic, read-only projection for one of six
`ObserverView` values: `MODEL_VIEW`, `VERIFIER_VIEW`, `COURT_VIEW`, `HUMAN_SUMMARY_VIEW`,
`AUDIT_VIEW`, `LEARNING_REFERENCE_VIEW`. A view is a data projection, never a permission — Court
remains authoritative only through the existing Phase 15 deterministic logic regardless of what
`COURT_VIEW` shows it.

## 21. Checkpoint model

A checkpoint is a compiled, canonical `CognitiveArtifact` serialized via `to_canonical_json`.
Because OCL structurally carries no CoT/credential field (§4), the one real residual risk is
secret-SHAPED content inside `content`/`reference`/`locator` strings — `checkpoint.py` reuses
`orca.learning.sanitize.sanitize_for_candidate` (no second secrets mechanism) and REJECTS (does not
silently redact-and-store) any checkpoint attempt containing one.

## 22. Authority separation (recap)

See §5, §12-14. The compiler's forbidden-metadata check plus the complete absence of any
authority-shaped field in `ActionIntent`/`VerificationContract`/`EscalationRequest`/
`CognitiveArtifact` are the two structural controls. `PHASE17_AUTHORITY_CALL_PATH.md` traces the
real Mission/Court call paths this relies on.

## 23. Corporate security / privacy / multi-tenancy

Security: see `PHASE17_THREAT_MODEL.md` for the full 40-item table. Privacy: no secret values are
persisted (checkpoint rejection); evidence anchors reference rather than copy sensitive content.
Multi-tenancy: OCL IDs are plain strings scoped by whatever system stores/indexes artifacts — OCL
itself asserts no global trusted namespace and performs no cross-artifact ID resolution; access
control remains entirely outside OCL, matching Phase 16's "Court ACCEPT is not access control"
discipline extended to this layer.

## 24. Backwards compatibility

Only one schema version exists (`1.0.0`); backwards-compatibility policy will be exercised for real
starting with the first V1.x/V2 revision, not designed speculatively here.

## 25. Future research hooks

`SourceClass`/`AtomKind`/the extension mechanism are deliberately neutral enough for Phase 18's
epistemic states (`KNOWN`/`INFERRED`/`UNCERTAIN`/`DISPUTED`/`UNKNOWN`/`UNVERIFIABLE`) to attach as a
new field or a registered extension namespace later, without OCL V1 claiming it can assign those
states today.

## 26. Phase 18 handoff

Phase 18 (Epistemic State) consumes: `CognitiveArtifact`'s atom/relation graph, `SourceClass`
(already distinguishes model assertion from measured/external/policy/human evidence), and
`CausalHypothesis` (already distinguishes hypothesis from established fact). Phase 18 MUST NOT be
implemented by reusing `SourceClass` as if it already were an epistemic-state enum — it is a
provenance/trust classification, not a confidence/certainty judgment, and the two must remain
separate concepts.
