# Temporal Memory (Phase 5)

## Design choice: a property of Semantic Memory, not a separate store

Spec §1 lists TEMPORAL MEMORY among the categories Memory Continuum
must distinguish. This phase implements it as **structural fields on
`SemanticMemoryRecord`** (`valid_from`, `valid_to`, `supersedes`,
`superseded_by`) rather than a separate storage class, because temporal
validity is a property *of* a fact, not an independent kind of content —
there is no "temporal memory" that doesn't also have a claim, entities,
and evidence. This mirrors how `orca/truth/contracts.py::Evidence`
carries `freshness`/`published_at` as fields rather than a parallel
"FreshnessMemory" type. Documented here explicitly as a deliberate
choice, not an omission.

## Never overwrite — always supersede

`MemoryArbiter.supersede(old, new)` (`orca/memory/arbiter.py`):

```python
old.superseded_by = new.memory_id
old.valid_to = new.valid_from or now()
new.supersedes = old.memory_id
# both records are saved -- old is NEVER deleted
```

The spec's own example is directly testable and tested
(`tests/test_memory_contracts_arbiter.py::test_supersede_never_deletes_the_old_record`):

```
January:  "System uses Model A."  valid_from=2026-01-01
August:   "System uses Model B."  valid_from=2026-08-01, supersedes=<Model A's id>
```

"What did we use before August?" is answered by filtering
`store.list_records(...)` for `valid_from < "2026-08-01"` — both records
stay in the same on-disk directory, retrievable by any `MemoryQuery`
with a `time_range`.

## Interaction with contradiction resolution

`MemoryArbiter.resolve_contradiction()` checks temporal ordering as one
of its deterministic signals (spec §17): if the conflicting existing
record has no `valid_to` (still open-ended) and the new candidate's
`valid_from` is later than the existing record's `created_at`, the
resolution is `TEMPORAL_CHANGE` — a real update, not a standing
contradiction. This is checked *after* an already-present Truth Fabric
relationship (highest fidelity) and scope difference, and *before*
falling back to `UNRESOLVED` (coexistence) — see
[MEMORY_EVIDENCE_LEDGER.md](MEMORY_EVIDENCE_LEDGER.md) and
`orca/memory/arbiter.py::resolve_contradiction()`.

## Staleness is a different mechanism from supersession

Supersession is explicit (a new record consciously created to replace
an old one). Staleness (`orca/memory/salience.py::is_stale()`) is
implicit — a record nobody has explicitly superseded yet, but whose
`last_verified_at` has aged past a class-specific TTL. See
[FORGETTING.md](FORGETTING.md) for the staleness/decay policy and
[ARCHITECTURE.md](ARCHITECTURE.md)'s recall flow for how a stale memory
triggers a Truth Fabric refresh rather than being silently treated as
current.
