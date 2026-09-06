# Corrective Retrieval (Phase 4.1)

Phase 4 planned `RetrievalPlan.corrective_rounds` as metadata (RAG_4/RAG_5
modes get `MAX_CORRECTIVE_ROUNDS=2`) but never executed a retry. Phase
4.1's `orca/truth/corrective.py` + `TruthFabric.assess_evidence()`'s loop
is the real implementation, reusing the reform-query pattern already
proven in `orca/docs/sufficiency.py::check_sufficiency()`'s
`_REFORM_PROMPT` (now Gateway-routed, operating on typed `Evidence`).

## The loop (`TruthFabric.assess_evidence`)

```
initial retrieval -> preliminary EvidenceState
while corrective_rounds remain
      AND state in (INSUFFICIENT, LOW_AUTHORITY, STALE)
      AND shared query budget remains
      AND overall deadline not reached:
    reform_query(objective, gap_reason) -> Gateway call
    if no reformed query, or it repeats a prior query: STOP
    retrieve again (dense-only, single query, no re-fan-out)
    merge + dedupe new evidence by content_hash
    reassess EvidenceState
    if no new evidence found, or state became SUFFICIENT: STOP
```

Never "loops until an LLM says it's satisfied" (spec §8) — every
continuation condition above is structural, checked by Python before the
next Gateway call, not decided by the judge itself.

## Stop reasons (`TruthResult.retrieval_stop_reason`)

Always set to exactly one of:

| Reason | Meaning |
|---|---|
| `initial_retrieval_sufficient` | No corrective round was needed at all. |
| `evidence_became_sufficient` | A corrective round succeeded. |
| `no_new_evidence_discovered` | A round's reformed query found nothing new — retrying further wouldn't help. |
| `repeated_query` | The reform call rewrote the query to something already tried (spec §9). |
| `reform_query_unavailable` | The Gateway call for reforming the query timed out or returned nothing usable. |
| `budget_exhausted` | A `CognitiveBudget` dimension ran out mid-loop. |
| `corrective_retrieval_timeout` | A single round's retrieval call itself timed out. |
| `max_corrective_rounds_reached` | The mode's `MAX_CORRECTIVE_ROUNDS` cap was hit. |
| `no_corrective_rounds_planned` | The selected retrieval mode (RAG_0/1/2/3) doesn't plan any corrective rounds at all. |
| `shared_query_budget_exhausted` | See below. |
| `deadline_reached` | `OVERALL_DEADLINE_S` was hit. |

## Query rewrite provenance (spec §10)

Each executed round is recorded as a `CorrectiveRound`:
`round_index`, `original_query`, `rewritten_query`, `reason`,
`evidence_gap`, `evidence_state_before`, `new_evidence_count`. `reason`/
`evidence_gap` are short, structured strings the reform-query judge call
itself returns — never a full reasoning trace or raw chain-of-thought.

## Multi-hop + corrective shared budget (spec §11)

`orca/truth/planner.py::MAX_TOTAL_RETRIEVAL_QUERIES = 6` bounds the
**total** number of distinct dense retrieval queries issued across one
`assess_evidence()` call — the initial query, every multi-hop subquery
(`decompose_query()`, itself capped at `MAX_SUBQUERIES=4`), and every
corrective round's single rewritten query, combined. Without this,
`RAG_5_RESEARCH` (multi-hop depth 3 × corrective rounds 2) could imply
far more retrieval passes than any single request needs. The corrective
loop checks `queries_issued < MAX_TOTAL_RETRIEVAL_QUERIES` before every
round; `tests/test_truth_corrective_contradiction_counter_evidence.py::
test_multi_hop_and_corrective_share_one_query_budget` proves the combined
total never exceeds the cap even when every corrective round is forced
to execute (nothing found, ever).

## Evidence merge/dedupe

`orca/truth/truth_fabric.py::_merge_evidence()` deduplicates by
`content_hash` — a corrective round that re-surfaces the same chunk
already in the running evidence set doesn't inflate `new_evidence_count`
or the final evidence list. `new_evidence_count == 0` is itself a stop
condition (see above), so a round that only rediscovers known evidence
correctly ends the loop rather than retrying with the same effective
result.
