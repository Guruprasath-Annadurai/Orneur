# Retrieval Modes (Phase 4)

`orca/truth/planner.py::build_retrieval_plan()` is pure and deterministic
— no I/O, no model calls. It selects one `RetrievalMode` from evidence
requirement, complexity, and intent, then attaches hard bounds.

| Mode | Selected when | Sources | Max docs | Notes |
|---|---|---|---|---|
| `RAG_0_NONE` | `evidence_requirement == NONE`, or LIGHT with no retrieval/search signal | none | 0 | No retrieval at all — not "retrieval with zero results," genuinely skipped. |
| `RAG_1_SEMANTIC` | LIGHT or SUPPORTED with explicit retrieval/search intent but not hybrid-worthy | DENSE (+WEB if search intent) | 6 | Single-query dense lookup. |
| `RAG_2_HYBRID` | SUPPORTED with explicit retrieval **and** search intent | DENSE + SPARSE (+WEB) | 10 | Runs DocStore and SearchProvider queries in the same pass; evidence from both sources is merged into one result set. |
| `RAG_3_MULTI_HOP` | STRICT with HIGH/DEEP complexity and agentic/secondary intents | DENSE + SPARSE (+WEB) | 16 | Original query is decomposed (`orca/truth/decomposition.py`) into up to `MAX_SUBQUERIES=4` bounded sub-queries; each issues its own DocStore lookup. |
| `RAG_4_CORRECTIVE` | STRICT, otherwise (not multi-hop-worthy) | DENSE + SPARSE (+WEB) | 12 | Plans `corrective_rounds > 0`, but see the honest scope note below. |
| `RAG_5_RESEARCH` | AUDIT_GRADE, always | DENSE + SPARSE + WEB (+MEMORY if applicable) | 24 | Widest mode: every source type in play. |

Hard caps (`orca/truth/planner.py`):

```
MAX_SUBQUERIES = 4
MAX_MULTI_HOP_DEPTH = 3
MAX_CORRECTIVE_ROUNDS = 2
MAX_DOCUMENTS_BY_MODE = {RAG_0: 0, RAG_1: 6, RAG_2: 10, RAG_3: 16, RAG_4: 12, RAG_5: 24}
MAX_PASSAGES_BY_MODE  = max(1, docs // 2) per mode
```

No mode can retrieve an unbounded number of documents, issue an unbounded
number of sub-queries, or loop indefinitely — every numeric field on
`RetrievalPlan` is capped independently of what any downstream stage
decides to actually use (spec §7–8).

## Honest execution scope

`TruthFabric._retrieve()` (`orca/truth/truth_fabric.py`) executes:

- **Dense retrieval** — one `DocStore.retrieve()` call per query. For
  `RAG_3_MULTI_HOP`/`RAG_5_RESEARCH`, the query list comes from
  `decompose_query()` (bounded, real). For every other mode, it's the
  single original query.
- **Web retrieval** — one `SearchProvider.search()` call, when `WEB` is
  in the plan's sources.

**Not yet executed**: `RetrievalPlan.corrective_rounds` is real, bounded
*planning* metadata (`RAG_4_CORRECTIVE` always plans `corrective_rounds
>= 1`), but `_retrieve()` does not currently re-query based on a
corrective round when the first pass's evidence turns out thin. That
retry loop — "corrective retrieval" in the fuller sense (assess
sufficiency, decide whether to retry with a reformulated query, bounded
by `MAX_CORRECTIVE_ROUNDS`) — is scoped as **foundation only** in this
phase, consistent with the Phase 4 spec's explicit exclusion of a large
autonomous research swarm. `tests/test_truth_fabric_retrieval_modes.py`
pins this down with a regression test
(`test_corrective_rounds_are_planned_but_not_yet_a_retry_loop`) so a
future implementation of the loop is a deliberate change, not something
that silently already looked implemented.

Every retrieval pass (dense or web) consumes one unit of
`BudgetDimension.RETRIEVAL_CALLS` — a budget with `max_retrieval_calls=0`
raises `TruthBudgetExhaustedError` before ever calling out
(`tests/test_truth_fabric_retrieval_modes.py::test_retrieval_calls_are_budget_metered`).

## Deep Search provider abstraction

`SearchProvider` (`orca/truth/search_provider.py`) is a `Protocol`:
`search(query, n, domain_filter=None) -> list[SearchResultMetadata]`.
`DuckDuckGoProvider` is the one production implementation, wrapping the
existing `orca/tools/web.py::search` rather than reimplementing search
(see [SEARCH_PROVIDERS.md](SEARCH_PROVIDERS.md)). `TruthFabric` accepts
any `SearchProvider` via its constructor, so tests substitute a fake
provider without touching retrieval-mode logic
(`tests/test_truth_fabric_retrieval_modes.py`).
