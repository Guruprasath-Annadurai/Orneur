# Procedural Memory (Phase 5)

`orca/memory/procedural.py` — first production version. "HOW TO PERFORM
A TASK", explicitly a retrieval/reference system (spec §59), never an
autonomous self-modifying procedure: nothing in this module rewrites its
own steps without an explicit caller-provided new step list.

## Contract

```python
ProceduralMemoryRecord:
  procedure_id, name, steps: list[str], preconditions, postconditions,
  version: int, successful_executions: int, failed_executions: int,
  last_verified_at
```

## One execution is never universally valid (spec §20)

`record_execution()` increments `successful_executions`/
`failed_executions` and updates `last_verified_at` — it does **not**
touch `epistemic_state`. Escalating trust from execution history is left
to the caller's own policy (e.g., "N consecutive successes → SUPPORTED"),
never automatic here — proven by
`tests/test_memory_contracts_arbiter.py::test_procedural_memory_execution_never_treated_as_universal`
(one success, `epistemic_state` stays `UNVERIFIED`).

## Versioning, not silent rewriting

`new_version(old, steps)` creates a **new** `ProceduralMemoryRecord`
with `version = old.version + 1` and `source_refs=[old.memory_id]` — the
old version's earned `successful_executions`/`failed_executions` stay
attached to the steps that actually earned them, rather than being
silently inherited by a changed procedure that hasn't been executed at
all yet.

## Retrieval

`find_by_name()` is a direct name lookup within a scope; general recall
goes through `orca/memory/retrieval.py::recall()` like any other memory
type, ranked by the same salience function
(`orca/memory/salience.py::compute_salience()` weighs a procedure's
success ratio into its `consequence` term).
