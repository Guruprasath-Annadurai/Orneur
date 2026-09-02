# Contradiction Engine (Phase 4.1)

Phase 4's `orca/truth/contradiction.py::detect_contradictions()` only
ever compared claims **within the generated answer** — a real, previously
undocumented scope gap surfaced by Phase 4's own evaluation harness (see
[EVALUATION.md](EVALUATION.md) finding #1): two conflicting *evidence
sources* were never flagged unless the model's answer happened to repeat
both conflicting values. Phase 4.1 adds
`detect_evidence_contradictions()`, which compares retrieved **evidence
passages directly**, independent of what the model ends up saying.

## Contradiction contract (spec §13)

```python
@dataclass
class Contradiction:
    claim_a_id: str          # an AtomicClaim id (answer-vs-answer) OR an Evidence id (evidence-vs-evidence)
    claim_b_id: str
    relationship: ContradictionRelationship
    temporal_context: str = ""
    subject: str = ""              # evidence-vs-evidence only: the specific fact/entity being compared
    source_a_id: str = ""          # evidence-vs-evidence only
    source_b_id: str = ""          # evidence-vs-evidence only
    resolution_state: str = "UNRESOLVED"   # this phase never writes anything else
```

`subject`/`source_a_id`/`source_b_id` are populated only by
`detect_evidence_contradictions()` — the original answer-claim-vs-answer-
claim path has no single source to name, so they stay empty there.

## Relationship states

`ContradictionRelationship` gained two values this phase:

| Value | Meaning |
|---|---|
| `DIRECT_CONTRADICTION` | Opposite assertions about the same specific fact. |
| `TEMPORALLY_RECONCILABLE` | Was true, no longer is (or vice versa) — not a standing contradiction. |
| `SCOPE_DIFFERENCE` *(new)* | Different jurisdiction/product tier/version — not a real contradiction. |
| `LIKELY_CONFLICT` *(new)* | The judge suspects a conflict but can't confirm both passages are about the exact same subject with confidence — deliberately weaker than `DIRECT_CONTRADICTION`, never silently promoted to it. |
| `UNRELATED` | Two true claims about different topics — filtered out, never returned to the caller. |

## Temporal reconciliation (spec §14) — deterministic, not judge-trusted

Small/nano models are unreliable at date arithmetic. Rather than asking
the judge to reason about `published_at`/`updated_at` itself,
`_likely_temporal(ev_a, ev_b)` is a deterministic pre-check: if both
pieces of evidence carry a determinable publication time and the times
differ, a judge-flagged `DIRECT_CONTRADICTION` is **reclassified** to
`TEMPORALLY_RECONCILABLE` — the judge's verdict on relationship type is
overridden, but the underlying evidence pair is still recorded (never
silently dropped). `tests/test_truth_corrective_contradiction_counter_evidence.py::
test_detect_evidence_contradictions_reclassifies_as_temporal` pins this
down with two evidence items dated five months apart.

## Source authority never auto-resolves a contradiction (spec §15)

`resolution_state` is hardcoded to `"UNRESOLVED"` for every contradiction
this phase produces — there is no code path where a higher-`SourceQuality`
source silently "wins" and the conflicting evidence disappears. Both
sides of a contradiction remain visible in `TruthResult.contradictions`
regardless of authority; a future phase's dedicated resolution step (not
built here) would be the place authority might inform confidence, not
this detector.

## Bounded, not O(n²) (spec §31)

`_evidence_candidate_pairs()` reuses the same lexical topic-overlap
pre-filter as the answer-claim path (`_TOPIC_OVERLAP_THRESHOLD=0.25`),
capped at `MAX_EVIDENCE_PAIRS_CHECKED=10` — an evidence set at
`RAG_5_RESEARCH`'s 24-document cap never triggers an unbounded pairwise
judge-call explosion.

## Where it runs

`TruthFabric.assess_evidence()` calls `detect_evidence_contradictions()`
once, after the corrective retrieval loop settles, and folds the result
into the preliminary `EvidenceState` (a `DIRECT_CONTRADICTION` here can
already produce `CONFLICTED` before generation even happens).
`TruthFabric.verify_answer()` keeps these evidence-level contradictions
visible in its own returned `TruthResult.contradictions` (merged with the
newly-detected answer-claim contradictions) — verification never drops a
known source conflict just because the model's answer didn't happen to
repeat it.
