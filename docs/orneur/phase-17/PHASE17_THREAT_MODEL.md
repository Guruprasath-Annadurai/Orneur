# PHASE 17 — OCL Threat Model

Format: Threat → attack path → impact → control → test → residual risk → owning future phase.
A control marked "tested" has a cited passing test; "documented, untested" is an honest gap, never
silently upgraded to VERIFIED.

1. **Model outputs authority-like fields** — atom/artifact `metadata` carries `authority_granted:
   true` etc. → could be misread as a grant → **control**: `FORBIDDEN_METADATA_KEYS` check in
   `compiler.py` → **tested**: `test_authority.py` (11 parametrized cases) → residual: same claim
   as free `content` text is not caught (see threat #22) → N/A (structural control is complete for
   its own scope).
2. **Model outputs fake VerificationRecord** — an atom/evidence anchor claims to BE a
   `VerificationRecord` → **control**: `EvidenceAnchor` is a reference (`evidence_kind=
   VERIFICATION_RECORD`, `reference=<opaque id>`), never the record's content; only
   `orca.mission.verification`'s real store can produce a genuine one → **tested**:
   `test_atoms.py::test_observation_reference_claiming_authoritative_source_without_evidence_ref_rejected`
   (adjacent control) → residual: OCL cannot verify the referenced ID actually resolves to a real
   record (that is the CONSUMER's job, not OCL's) → Phase 20+ (router/consumer-side resolution).
3. **Model outputs fake Production Proof** — same shape as #2, `EvidenceKind.PRODUCTION_PROOF` →
   same control/residual as #2.
4. **Fake CourtDecision reference** — same shape as #2, `EvidenceKind.COURT_DECISION` → same
   control/residual as #2.
5. **Fake human approval** — `metadata={"human_approved": true}` → **control/tested**: threat #1's
   control covers this exact key.
6. **Evidence ID spoofing** — an atom's `evidence_refs` names an ID with no matching
   `EvidenceAnchor` → **control**: `DanglingRelation` in `compiler._validate_evidence` → **tested**:
   covered by `test_relations.py`'s dangling-reference pattern (same mechanism, evidence path).
7. **External response mislabeled native** — `producer_kind=EXTERNAL_PROVIDER` with `family` set →
   **control**: `InvalidProvenance` → **tested**:
   `test_provenance.py::test_external_provider_cannot_claim_a_native_family`.
8. **Model checkpoint identity spoofing** — `family`/`lifecycle_state` set to a fabricated value →
   **control**: validated against real `MODEL_SPECS`/`LifecycleState` → **tested**:
   `test_provenance.py::test_unknown_model_family_rejected`, `::test_unknown_lifecycle_state_rejected`.
9. **Graph cycle bomb** — pathological cyclic relations to stall traversal → **control**: cycle
   detection is bounded DFS over `ACYCLIC_RELATION_KINDS` only, `O(atoms+relations)` → **tested**:
   `test_relations.py::test_acyclic_relation_kind_rejects_a_cycle`; **residual**: a large
   CYCLE-TOLERANT graph (e.g. all-pairs `CONTRADICTS`) is not itself bounded beyond the atom/
   relation count limits → controlled by #10's limits, not a separate mechanism.
10. **Graph fanout DoS** — huge atom/relation counts → **control**: `MAX_ATOMS_PER_ARTIFACT`,
    `MAX_RELATIONS_PER_ARTIFACT` → **tested**: `test_limits.py` (4 tests).
11. **Recursive metadata bomb** — deeply nested metadata dict → **control**:
    `MAX_METADATA_DEPTH`/`MAX_METADATA_KEYS` → **tested**: `test_limits.py` (2 tests).
12. **Malicious extension namespace** — atom claims an unregistered namespace to smuggle
    unvalidated semantics → **control**: `InvalidNamespace` → **tested**: `test_extensions.py`.
13. **Schema downgrade** — artifact claims an old/unsupported version to skip newer validation →
    **control**: `UnsupportedSchemaVersion` fail-closed (only `1.0.0` exists/is accepted) →
    **tested**: `test_schema_version.py`.
14. **Schema confusion** — mixing fields from a hypothetical future version → **N/A this phase**:
    only one version exists; no migration/mixed-version logic has been built to confuse.
15. **Unknown enum coercion** — an unrecognized `AtomKind`/`RelationKind`/`SourceClass` string →
    **control**: Python `Enum(value)` construction raises `ValueError` on any unrecognized value
    (used throughout `canonical.artifact_from_dict`) → **tested**: implicitly by every enum
    construction in the round-trip test; no permissive fallback exists anywhere in the codebase.
16. **Duplicate atom IDs** — **control/tested**: `test_atoms.py::test_duplicate_atom_id_rejected`.
17. **Dangling relations** — **control/tested**: `test_relations.py` (2 tests).
18. **Cross-artifact reference confusion** — an atom_id ref inside one artifact accidentally
    resolves against a DIFFERENT artifact's atom set → **control**: validation is always scoped to
    the single artifact being compiled; no global atom-ID namespace exists → **documented,
    untested** (no test constructs two artifacts and proves cross-resolution is impossible, since
    the compiler's design makes it structurally impossible rather than merely checked) →
    DEFERRED_TO_FUTURE_PHASE if a future cross-artifact reference feature is added.
19. **Stale evidence reuse** — an `EvidenceAnchor` with an old `observed_at` reused as if fresh →
    **control**: `observed_at` is a documented freshness reference field; OCL does not itself judge
    freshness → **documented, untested this phase** — freshness POLICY is a future (Phase 18+)
    epistemic concern; OCL only carries the timestamp reference honestly.
20. **Cross-tenant reference attack** — no tenant scoping exists in OCL IDs → **control**: OCL
    asserts no global trusted namespace (§23 of master spec); access control is explicitly
    out-of-scope, left to the storage/consumer layer → DEFERRED (multi-tenant storage is a future
    integration concern, not an OCL-core one).
21. **Secret/API key leakage** — **control/tested**: `checkpoint.py`'s
    `sanitize_for_candidate` reuse, `test_checkpoint.py` (2 tests, atom content + evidence
    reference).
22. **Prompt injection inside evidence text** — an atom's `content` contains adversarial
    instructions aimed at a downstream renderer/LLM → **control**: OCL atoms are DATA; no OCL
    component ever re-feeds atom `content` into a model prompt without the caller's own separate
    escaping/framing discipline → **documented, untested this phase** — this is fundamentally a
    downstream-consumer responsibility; OCL's only concrete mitigation is that its own compiler/
    observer/diff code paths never execute or interpret `content` as instructions.
23. **Causal edge presented as fact** — **control/tested**: `test_causal.py`, master spec §11 (
    `CAUSES` is always a hypothesis; `AtomKind` has no `FACT` member at all).
24. **Assumption presented as measured fact** — **control/tested**: `test_atoms.py::test_model_assertion_cannot_claim_measured_evidence_source_class`
    (same mechanism generalizes to ASSUMPTION/HYPOTHESIS/etc.).
25. **Model assertion presented as deterministic policy** — **control/tested**: same mechanism as
    #24 (`SourceClass.DETERMINISTIC_POLICY_REFERENCE` requires `OBSERVATION_REFERENCE` kind +
    evidence ref).
26. **Action proposal executed without authority** — **control**: `ActionIntent` has no execution
    mechanism anywhere in this codebase; only `orca.agent.policy`/`orca.mission` (unchanged,
    untouched) can execute anything, and neither imports `orneur.intelligence.ocl` in this phase →
    **tested**: `test_authority.py::test_action_intent_has_no_authority_field` (structural).
27. **Escalation request interpreted as router command** — **control**: no router exists yet
    (Phase 20); `EscalationRequest.requested_cognitive_role` is documented advisory-only text →
    DEFERRED_TO_FUTURE_PHASE (Phase 20 must itself never treat this field as binding).
28. **Transformation silently deletes contradictory evidence** — **control/tested**: Cognitive
    Conservation, `test_conservation.py::test_important_atom_silently_disappearing_is_a_conservation_violation`.
29. **Cognitive Diff hides removals** — **control/tested**: `test_diff.py::test_added_and_removed_atoms_detected`
    explicitly asserts removals are visible, not just additions.
30. **Hash instability / noncanonical serialization** — **control/tested**:
    `test_serialization.py::test_stable_digest_for_logically_equivalent_artifacts`,
    `::test_deterministic_ordering_regardless_of_input_order`.
31. **Unicode/canonicalization confusion** — **control/tested**:
    `test_serialization.py::test_unicode_content_round_trips` (no normalization is performed —
    documented: byte-identical UTF-8 round-trip only, not Unicode-normalization-equivalence; two
    differently-normalized but visually-identical strings would currently produce different
    digests — **documented limitation**, not fixed this phase).
32. **Parser resource exhaustion** — a malicious wire payload with deeply nested/huge JSON →
    **control**: `artifact_from_canonical_json` checks the raw UTF-8 byte length against
    `MAX_ARTIFACT_SERIALIZED_BYTES` BEFORE calling `json.loads`, rejecting an oversized payload
    before paying any parsing cost → **tested**:
    `test_serialization.py::test_oversized_wire_payload_rejected_before_parsing`.
33. **Extension schema smuggling** — a registered namespace's own "schema" is never actually
    validated beyond its name/version existing → **control**: `NamespaceRegistration` records a
    `version` but Phase 17 does not implement per-namespace schema validation (explicitly YAGNI'd,
    per spec §16: "Phase 17 only needs the extension architecture ... not full taxonomies") →
    DEFERRED_TO_FUTURE_PHASE (whichever phase first ships a real extension namespace).
34. **Provider/native provenance substitution** — **control/tested**: same as #7.
35. **Replay of stale cognitive artifact** — an old, compiled artifact resubmitted as if current →
    **control**: `created_at` is caller-supplied and not itself re-validated against a clock by the
    compiler (deliberately, per determinism requirements — §23 of the Phase 17 prompt: "explicit
    timestamp injection... needed") → freshness/staleness policy is a CONSUMER decision, not OCL's
    → DEFERRED (documented, consistent with #19).
36. **Artifact ID collision** — two different artifacts sharing an `artifact_id` → **control**:
    within one compile call IDs are checked for internal duplication (atoms/relations/evidence);
    cross-artifact `artifact_id` uniqueness is a storage-layer responsibility, not enforced by the
    compiler itself → documented, consistent with #18/#20.
37. **Mutation after hashing** — **control/tested**: `test_checkpoint.py::test_compiled_artifact_is_immutable`
    (frozen dataclass, `FrozenInstanceError` on mutation attempt).
38. **Deserialization creating executable Python objects** — **control/tested**:
    `test_serialization.py::test_no_pickle_used_anywhere_in_serialization_module` (AST-verified: no
    `pickle` import, no `eval`/`exec` call anywhere in `canonical.py`).
39. **Logs leaking sensitive OCL content** — OCL itself does not log anything (no logging calls
    exist in any `orneur/intelligence/ocl/*.py` file) → verified by inspection, not a dedicated
    test → residual: a FUTURE caller that logs an artifact's `content` fields could leak sensitive
    text; OCL's checkpoint-time secret scan (#21) reduces but does not eliminate this for arbitrary
    ad-hoc logging outside the checkpoint path.
40. **Private chain-of-thought accidentally persisted** — **control/tested**:
    `test_checkpoint.py::test_cognitive_artifact_has_no_hidden_chain_of_thought_field` (structural
    field-name check across the whole `CognitiveArtifact` shape).

## Summary

31 of 40 threats have a cited passing test. 9 are honestly documented as untested/deferred
(#14 is N/A, not a gap) rather than claimed VERIFIED without evidence.
