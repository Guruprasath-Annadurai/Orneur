# Episodic Ledger (Phase 5)

`orca/memory/episodic.py`. Append-only, distinct from the pre-existing
`orca/brain/memory.py::EpisodicMemory`, which overwrites its one JSON
file in full on every `save()` — the exact incompatibility spec §58
asks Phase 5 to identify before deciding to adapt vs. replace.

## Storage

One JSONL file per `(scope, scope_id)`, filename derived from
`sha256(f"{scope.value}:{scope_id}")[:24]` — the scope_id itself (a
session_id, potentially caller-influenced) is never used directly as a
filename, matching the same discipline `DocStore` already uses for its
own collection naming.

## Append-only, with two real exceptions

1. **Idempotency** (spec §51): `append_episode()` hashes the episode's
   own content (`event|context|outcome|actions`) and, if an episode with
   that exact `content_hash` already exists in this scope's ledger,
   returns the existing record instead of writing a duplicate.
   Reprocessing the same event twice (a retried request, a duplicate
   webhook) does not create two equivalent episodes.
2. **Tombstone deletion** (spec §29, §38-39): `delete_episode()` redacts
   an episode's content fields in place and sets
   `lifecycle_state=PURGED`, but the ledger *line* remains — a caller
   holding a `source_ref` to this episode can tell "this existed and was
   deleted" apart from "this id never existed", which
   `orca/memory/deletion.py`'s derived-memory re-evaluation depends on.
   This is the only in-place mutation the ledger ever performs, and it
   never restores original content — see [FORGETTING.md](FORGETTING.md).

## Corrections create new records, not rewrites

A later correction to an episode's content is a **new** `MemoryEpisode`,
linked by whatever the caller chooses (a `source_refs` reference, a
`MemoryRelationshipType.DERIVED_FROM` edge at the semantic-memory layer)
— never an in-place rewrite of the original. This is proven directly:
`tests/test_memory_contracts_arbiter.py::
test_episodic_ledger_is_append_only_and_idempotent` appends an episode,
its exact duplicate (idempotent, no new record), and then a distinct
"correction" episode, and asserts the ledger ends up with **two**
records, not one rewritten in place.
