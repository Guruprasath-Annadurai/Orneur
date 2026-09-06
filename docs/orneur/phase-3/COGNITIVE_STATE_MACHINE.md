# Cognitive State Machine

`orca/cognitive/state_machine.py::CognitiveStateMachine`.

## States

`RECEIVED → CLASSIFYING → PLANNED → EXECUTING → {WAITING ⇄ EXECUTING, VERIFYING} → COMPLETED`, with `ABSTAINED`/`FAILED`/`CANCELLED` reachable from most non-terminal states. `COMPLETED`, `ABSTAINED`, `FAILED`, `CANCELLED` are terminal — no transition out of any of them is allowed.

## Validated transitions

```
RECEIVED    -> CLASSIFYING, CANCELLED, FAILED
CLASSIFYING -> PLANNED, ABSTAINED, FAILED, CANCELLED
PLANNED     -> EXECUTING, ABSTAINED, FAILED, CANCELLED
EXECUTING   -> WAITING, VERIFYING, COMPLETED, ABSTAINED, FAILED, CANCELLED
WAITING     -> EXECUTING, ABSTAINED, FAILED, CANCELLED
VERIFYING   -> COMPLETED, ABSTAINED, FAILED, CANCELLED
COMPLETED / ABSTAINED / FAILED / CANCELLED -> (none; terminal)
```

An attempted transition not in this table raises `InvalidStateTransitionError` (`orca/cognitive/errors.py`) — it never silently succeeds or silently no-ops. `tests/test_cognitive_state_machine.py` verifies both the valid happy path and that invalid transitions (e.g. `RECEIVED -> COMPLETED` directly, or any transition attempted from a terminal state) are rejected and leave the machine's state unchanged.

## Why `WAITING` can return to `EXECUTING`

`WAITING` exists for a future case (e.g. a queued retrieval/tool call, or a paused agent delegation) where execution needs to pause and later resume without the whole cognitive request restarting from `PLANNED`. Nothing in Phase 3 actually drives a request into `WAITING` yet — `CognitiveKernel.execute()`'s real Phase 3 implementation goes `EXECUTING -> COMPLETED` (or an abstention/failure state) directly — but the transition is validated and tested now so a future phase that needs it doesn't have to touch this module.

## No raw chain-of-thought

Every transition is recorded as a `StateTransition(from_state, to_state, at_monotonic)` — a timestamp and two enum values, nothing else. `CognitiveTrace.state_transitions` (see `COGNITIVE_CONTRACTS.md`) is built entirely from these. This is deliberate: the Cognitive Flight Recorder (Phase 3 spec §25) must be safe to log and audit, which raw model reasoning text is not.
