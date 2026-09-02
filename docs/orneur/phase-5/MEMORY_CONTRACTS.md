# Memory Contracts (Phase 5)

All in `orca/memory/contracts.py`, following the pattern already
established by `orca/truth/contracts.py`: pure dataclasses, no behavior.

## Identity (spec §5)

Every persisted memory carries `MemoryRecord`'s base fields:
`memory_id` (stable, assigned at creation — **never** a vector-store row
position), `memory_type`, `scope`/`scope_id`, `created_at`/`updated_at`,
`valid_from`/`valid_to`, `epistemic_state`, `confidence` (supplements,
never replaces, `epistemic_state`), `source_refs`, `evidence_refs`,
`privacy`, `lifecycle_state`, `content_hash`.

## Enums

| Enum | Values | Used for |
|---|---|---|
| `MemoryScope` | GLOBAL/TENANT/WORKSPACE/PROJECT/USER/SESSION/AGENT | Spec §6. Only SESSION and AGENT are actually enforceable end-to-end today (this codebase has no tenant/workspace/project concept) — the rest are reserved contract surface, not fully wired. |
| `MemoryType` | WORKING/EPISODIC/SEMANTIC/ENTITY/PROCEDURAL/FAILURE/AGENT | See [ARCHITECTURE.md](ARCHITECTURE.md) for why TEMPORAL and EVIDENCE aren't separate values. |
| `EpistemicState` | KNOWN/SUPPORTED/PROBABLE/CONTESTED/STALE/UNVERIFIED/UNKNOWN/DISPROVEN | Spec §13 — trust is never a single float. |
| `MemoryLifecycleState` | ACTIVE/DORMANT/ARCHIVED/PURGED | Spec §29. |
| `MemoryRelationshipType` | SUPERSEDES/SUPERSEDED_BY/VALID_DURING/CONTRADICTS/DERIVED_FROM | Spec §16. |
| `ContradictionResolution` | TEMPORAL_CHANGE/SCOPE_DIFFERENCE/VERSION_DIFFERENCE/CONTESTED/DISPROVEN/UNRESOLVED | Spec §17. |
| `DuplicateClassification` | IDENTICAL/NEAR_DUPLICATE/SAME_FACT_DIFFERENT_WORDING/POTENTIAL_CONFLICT/DISTINCT | Spec §26. |
| `PromotionDecision` | PROMOTED/REJECTED/DEFERRED | Spec §10. |
| `FailureVerificationState` | VERIFIED_ROOT_CAUSE/PROBABLE/UNVERIFIED | Spec §22. |

Privacy reuses `orca.cognitive.contracts.PrivacyClass`
(STANDARD/SENSITIVE/RESTRICTED) rather than a parallel scheme (spec §37).

## Record types

`MemoryEpisode`, `SemanticMemoryRecord`, `EntityMemoryRecord`,
`ProceduralMemoryRecord`, `FailureMemoryRecord` all extend `MemoryRecord`.
`WorkingMemory` and `MemoryCandidate` are deliberately NOT `MemoryRecord`
subtypes — working memory is ephemeral by default (spec §7) and a
candidate is explicitly not-yet-trusted (spec §10), so neither carries
the "this is a persisted, identity-stable fact" contract the base class
implies.

## Query / result / decision types

`MemoryQuery` (typed, never an arbitrary query string — spec §33, §35),
`MemoryRecallResult`, `MemoryConsolidationResult`, `MemoryDecision`,
`MemoryTrace` (labels only, never raw memory text — spec §45).

## `MemoryEvidence` — the lineage primitive

```python
episode_id: str | None
truth_request_id: str | None       # orca.truth.contracts.TruthResult.request_id
truth_evidence_id: str | None      # orca.truth.contracts.Evidence.evidence_id
truth_claim_id: str | None         # orca.truth.contracts.AtomicClaim.claim_id
citation_verdict_state: str | None
document_ref: str | None
note: str                          # short, structured -- e.g. "truth_relationship:TEMPORALLY_RECONCILABLE"
```

One `MemoryEvidence` points at either a Memory Continuum episode or a
Truth Fabric result, ideally not neither. See
[MEMORY_EVIDENCE_LEDGER.md](MEMORY_EVIDENCE_LEDGER.md).
