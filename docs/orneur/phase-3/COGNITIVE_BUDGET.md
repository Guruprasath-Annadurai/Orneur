# Cognitive Budget

`orca/cognitive/contracts.py::CognitiveBudget` (pure data) + `orca/cognitive/budget.py` (validation/consumption/enforcement).

## Scope: representation, not a market allocator

Phase 3 builds exactly what the spec asks for and no more: budget representation, validation, consumption accounting, and hard-stop enforcement hooks. Dynamic reallocation across concurrent requests, priority-weighted budget markets, or cost-based auctioning are explicitly future work.

## Dimensions

`TOKENS`, `LATENCY_MS`, `MODEL_CALLS`, `RETRIEVAL_CALLS`, `TOOL_CALLS`, `AGENT_CALLS`, `COST_USD`, `REASONING_ROUNDS` — each independently capped (`max_*`, `None` = uncapped) and tracked (`consumed_*`).

`DEFAULT_BUDGET` (`budget.py`) is the sane, explicit default every `CognitiveRequest` gets when the caller doesn't supply `budget_constraints`: 8000 tokens, 60s latency, 6 model calls, 4 retrieval calls, 6 tool calls, 1 agent call, no cost cap, 3 reasoning rounds. Never "unlimited by omission."

## Safety invariants (all enforced, all tested)

- **Negative limits/consumed values rejected at construction** (`validate_budget`) — a budget can never be built in an already-invalid state.
- **`consume()` never allows silent overflow.** If consuming `amount` would push `consumed_X` past `max_X`, it raises `CognitiveBudgetExhaustedError` and does **not** mutate the ledger — a rejected consumption leaves the budget exactly as it was.
- **Remaining budget is always observable** (`remaining()`) — returns `None` for an uncapped dimension (an explicit, documented "no cap tracked" state, never confused with "0 remaining").
- **`has_any_capacity()`** is a non-mutating pre-check — callers can ask "would this fit?" without committing to spending it.

## Enforcement in practice (`kernel.py`)

`MODEL_CALLS` is a **pre-flight hard stop**: `consume(budget, MODEL_CALLS, 1)` runs *before* the Gateway call — if it raises, the Kernel abstains with `AbstentionReason.BUDGET_EXHAUSTED` and no model call happens at all.

`TOKENS` can only be known *after* the model call completes (actual token usage isn't predictable in advance). Consumption is still recorded for observability, but a token-budget overrun on an already-completed, already-useful response is **not** retroactively treated as a failure — it's recorded and surfaced as a `warnings` entry on the `CognitiveResult` instead. This is a deliberate distinction: "no cognitive operation may assume infinite budget" (spec §14) means bounding what CAN be checked in advance; a dimension that's fundamentally only knowable in arrears is honestly handled differently, not force-fit into the same enforcement shape.

## `COGNITIVE_BUDGET_EXHAUSTED`

Both a structured `CognitiveErrorCode` (`orca/cognitive/errors.py`) and an `AbstentionReason` — the Kernel never silently continues past an exhausted budget; every exhaustion path ends in an explicit `ABSTAINED` result or a raised `CognitiveBudgetExhaustedError`, never a degraded-but-unlabeled answer.
