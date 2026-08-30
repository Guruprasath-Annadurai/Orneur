# Intent Compiler

`orca/cognitive/intent.py::compile_intent(message) -> IntentPlan`.

## Honest scope

Deterministic, rules-first, regex pattern-matching over surface language — the same honesty standard `orca/serve/routing.py`'s existing `classify_query()` already applies to itself (see `docs/orneur/phase-3/CURRENT_COGNITIVE_ORCHESTRATION.md`). This is **not** claimed to be intelligent enough to solve intent routing permanently: it will have real false negatives on phrasing it doesn't recognize, exactly like `orca/lens/intent.py`'s generation-intent detector already discloses about itself.

The architecture is what matters for extensibility: `compile_intent()` is the single entry point every caller uses (`kernel.py`, tests). A future Genesis-powered intent compiler can replace this function's body entirely — deterministic pattern matching swapped for a model call — without any caller changing, because the `IntentPlan` contract stays the same.

## How it works

1. Match the message against per-category regex pattern lists (`_PATTERNS`). Multi-label: every category with a match is a hit.
2. The first hit (by category dict order, most-specific-first: CODING → RESEARCH → REASONING → PLANNING → TOOL_USE → MEMORY_RECALL → DOCUMENT_ANALYSIS → AGENTIC → FACTUAL → CONVERSATIONAL) becomes `primary_intent`; the rest become `secondary_intents`.
3. No match at all → `UNKNOWN` — never silently defaults to `CONVERSATIONAL` (that would misrepresent "we don't know" as "this is small talk," a real classification with real downstream consequences for evidence/complexity).
4. Derived boolean fields (`requires_retrieval`, `requires_search`, `requires_memory`, `requires_tools`, `requires_reasoning`, `requires_agents`, `citation_requirement`) are each computed from a fixed intent-category set (e.g. `_TOOL_INTENTS = {TOOL_USE, CODING, AGENTIC}`), not from each other — no hidden boolean-interaction logic.
5. `freshness_requirement` is delegated to `orca/cognitive/freshness.py` (kept as its own bounded module, not inlined, so a future retrieval-planning component has one clear place to call).

## Multi-label example

`"Research the topic and explain why it matters, step by step."` → primary `RESEARCH`, secondary `[REASONING]`, `requires_search=True`, `requires_reasoning=True`, `citation_requirement=True`.

## What it deliberately does NOT do

- Does not call any model.
- Does not read conversation history (stateless — one message in, one `IntentPlan` out; multi-turn continuity is the existing `AgentLoop`'s job, untouched).
- Does not decide tool routing details (which specific tool, what arguments) — that remains `AgentLoop._plan`'s job for any request whose plan requires `USE_TOOL` (see `CUTOVER.md`).
