# Memory Consolidation (Phase 5)

`orca/memory/consolidation.py`. Episodes → `SemanticMemoryRecord`,
**without deleting the source episodes** — they remain independently
retrievable via `orca/memory/episodic.py` forever, until a separate,
explicit deletion (spec §38-39).

## A real criterion is required (spec §25)

`assess_criteria()` checks for:

- **recurrence** — 2+ corroborating episodes
- **verified_evidence** — non-empty `evidence_refs` (e.g. Truth Fabric lineage)
- **explicit_confirmation** — a human/caller explicitly confirmed the claim

**Several model-generated summaries merely agreeing with each other is
NOT, on its own, one of these criteria** (spec §25's explicit warning).
A single episode with no evidence and no explicit confirmation is
rejected outright:
`tests/test_memory_retrieval_consolidation_firewall.py::
test_consolidation_requires_a_real_criterion`.

## Source episodes always survive

```python
result = consolidate("X is a recurring fact.", [ep1, ep2])
# result.derived_from == [ep1.memory_id, ep2.memory_id]
episodic.list_episodes(scope, scope_id)  # still returns ep1 AND ep2
```

Proven directly:
`test_consolidation_preserves_source_episodes`.

## Deduplication on consolidation

Before creating a new `SemanticMemoryRecord`, `consolidate()` runs the
same `MemoryArbiter.find_duplicate()` check any other promotion uses. An
`IDENTICAL` match doesn't create a redundant record — it merges the new
episodes into the *existing* record's `source_refs` instead, so
re-consolidating the same fact from additional corroborating episodes
strengthens one record's provenance rather than fragmenting it across
several near-identical ones.
