# Budget Dimension Audit (Phase 7.2 spec §2)

## `CognitiveBudget`'s real dimensions (`orca/cognitive/contracts.py::BudgetDimension`)

| Dimension | Unit | Default cap (`DEFAULT_BUDGET`) |
|---|---|---|
| `TOKENS` | generated tokens | 8000 |
| `LATENCY_MS` | milliseconds | 60,000.0 |
| `MODEL_CALLS` | count of LLM inference calls | 6 |
| `RETRIEVAL_CALLS` | count of retrieval/search operations | 4 |
| `TOOL_CALLS` | count of tool invocations | 6 |
| `AGENT_CALLS` | count of delegated-agent invocations | 1 |
| `COST_USD` | dollars | None (untracked by default) |
| `REASONING_ROUNDS` | count of deliberation rounds | 3 |
| `MEMORY_OPERATIONS` | count of memory queries/comparisons/consolidations | 10 |

## What each Society/Court/Truth Fabric/replanning operation ACTUALLY consumes, by reading the code (not assumed)

| Operation | Real dimension consumed | Where |
|---|---|---|
| Court Constructor (1 model call) | `MODEL_CALLS` | `orca/deliberation/court.py` via `SocietyBudgetLedger` |
| Court Falsifier (1 model call) | `MODEL_CALLS` | same |
| Truth Fabric claim extraction | `MODEL_CALLS` | `orca/truth/truth_fabric.py::verify_answer` |
| Truth Fabric per-claim verification | `MODEL_CALLS` | same |
| Truth Fabric contradiction judging | **unmetered** (pre-existing, not a Phase 7.1/7.2 change — never separately budget-consumed in this codebase, before or after Model Society) | same |
| `reform_query` (query rewrite, corrective loop) | `MODEL_CALLS` | `orca/truth/truth_fabric.py::assess_evidence`'s corrective loop, `_consume_or_raise(..., MODEL_CALLS, 1)` immediately before calling `reform_query` |
| Initial retrieval query | `RETRIEVAL_CALLS` | `orca/truth/truth_fabric.py::_retrieve()` |
| Multi-hop retrieval sub-queries | `RETRIEVAL_CALLS` | same `_retrieve()` call, same dimension, same shared counter (`queries_issued`) -- multi-hop does NOT get an independent allocation (spec §9) |
| Corrective retrieval round | `RETRIEVAL_CALLS` | same |
| Counter-evidence search | `RETRIEVAL_CALLS` | `orca/truth/counter_evidence.py::find_counter_evidence` -- **pure retrieval, no model/judge call exists in this function at all** (verified by reading the function body: one `search_provider.search()` call, nothing else) |
| Kernel replanning (re-running Court) | `MODEL_CALLS` (2, via Court's own reservation on the re-run) | `orca/cognitive/kernel.py`'s replan loop reserves a `"replanning"` unit as a GATE before allowing the re-run to start; the re-run itself then separately reserves `constructor`/`falsifier` |
| Direct answer generation | `MODEL_CALLS` (+`TOKENS`) | `orca/cognitive/kernel.py` |
| Memory recall | `MEMORY_OPERATIONS` | `orca/cognitive/kernel.py` |

## The corrected finding vs. Phase 7.1's assumption

Phase 7.1 assumed "counter-evidence" needed a MODEL_CALLS reservation for
"its verifier/model step" (spec §10 anticipates this). Reading the actual
`find_counter_evidence()` implementation shows **no such step exists** --
it is retrieval-only. There is therefore no MODEL_CALLS component to wire
for counter-evidence at all; only `RETRIEVAL_CALLS`. This audit corrects
that assumption with the real code behavior, per spec §2's explicit
instruction to "follow actual code behavior."

## No interchangeable treatment

`RETRIEVAL_CALLS` and `MODEL_CALLS` are DIFFERENT resources with different
real-world costs (a retrieval/search call vs. an LLM inference call) and
different existing caps (4 vs. 6 in `DEFAULT_BUDGET`). Phase 7.1's
`SocietyBudgetLedger` computed ALL purpose caps (including a
never-actually-wired `retrieval`/`counter_evidence` purpose) as a
percentage of `budget.max_model_calls` alone -- a latent mismatch that
was caught before it caused a real bug only because those two purposes
were never actually connected to real reservations in Phase 7.1. Phase
7.2 fixes this structurally (see `BUDGET_EXECUTION.md`): every purpose
now declares which `BudgetDimension` it draws from, and its cap is
computed as a percentage of THAT dimension's own capacity.
