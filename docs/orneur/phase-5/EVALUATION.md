# Memory Continuum Evaluation (Phase 5)

## Harness

`orca/memory/eval_harness.py` — run directly with
`.venv/bin/python -m orca.memory.eval_harness`. Every scenario exercises
real Memory Continuum code (significance filter, candidate extraction,
`MemoryArbiter`, retrieval, firewall, deletion cascade) end-to-end; no
score is invented or hand-picked. 14 scenarios, deterministic — no
Ollama dependency, so this harness runs in well under a second and is
safe to run in CI.

## Real result (2026-08-25 run)

**13 / 14 passed (0.929 pass rate).**

| Scenario | Result |
|---|---|
| remember_explicit_fact | PASS |
| do_not_remember_trivial_chatter | PASS |
| update_fact_over_time_and_retrieve_historical_value | PASS |
| contradictory_memories_coexist | PASS |
| same_fact_phrased_differently_is_deduplicated | **FAIL** |
| delete_source_episode_and_reevaluate | PASS |
| stale_api_fact_detected | PASS |
| procedural_recall | PASS |
| failure_recall | PASS |
| cross_user_isolation | PASS |
| cross_project_isolation | PASS |
| prompt_injected_memory_blocked | PASS |
| agent_scoped_isolation | PASS |
| evidence_lineage_completeness | PASS |

## The one honest failure

`same_fact_phrased_differently_is_deduplicated`: "The rate limit is 100
requests per minute." vs. "Requests are limited to one hundred per
minute." — `MemoryArbiter.find_duplicate()`'s deterministic, lexical
duplicate detector (`orca/memory/arbiter.py`) does not recognize
numeral-word equivalence ("100" vs. "one hundred") or synonym-level
paraphrase ("rate limit is X" vs. "requests are limited to X"). Token
overlap between the two claims falls below the
`SAME_FACT_DIFFERENT_WORDING` threshold, so the pair is (correctly, by
the detector's own logic, but not by the scenario's intent) classified
`DISTINCT` rather than a duplicate.

**Not tuned to force a pass** (per this project's established
discipline — see Phase 4.1's claim-verifier false-positive finding for
the same posture). This is a real, disclosed limitation of a
deterministic, no-Gateway-call duplicate detector: it trades semantic
recall for speed and zero LLM dependency (spec §48's "don't add a
multi-second path to every recall" pressure applies to writes too). A
future phase could add a Gateway-routed semantic-duplicate check
(mirroring `orca/memory/candidates.py::extract_candidates_via_gateway`'s
existing tiered-cost pattern: cheap deterministic path by default, an
opt-in Gateway-routed path for callers that can afford the latency)
without changing `find_duplicate()`'s contract.

## Required scenarios not covered by this harness (and why)

- **Truth Fabric refresh** (`orca/memory/refresh.py`) needs live Ollama
  — covered instead by the same `tests/test_truth_fabric_integration.py`-style
  live suite discipline (see `tests/test_memory_*` files marked for live
  runs where applicable), not duplicated here to avoid this harness
  silently depending on Ollama being reachable.
- **Recall precision/relevance against a labeled corpus** at meaningful
  scale: this phase's fixture set is small by design (same rationale as
  Phase 4's Truth Fabric eval corpus — a correctness harness for a first
  production version, not a benchmark claim).

## Baseline comparison: legacy `orca/brain/memory.py` vs Memory Continuum (spec §55)

| Dimension | Legacy engine | Memory Continuum |
|---|---|---|
| Recall relevance | Chroma/BM25 keyword search over raw `Q:/A:` text blobs, no significance filter | Salience-ranked (`orca/memory/salience.py`), scope/entity/epistemic-state filterable |
| Temporal correctness | None — a fact update is a NEW vector row alongside the old one, with no `valid_from`/`valid_to` and no query support for "what did we use before X" | `valid_from`/`valid_to`/`supersedes` — proven answerable (`test_supersede_never_deletes_the_old_record`) |
| Scope correctness | Session-id string keying only, no cross-check at recall time | Enforced by `orca/memory/firewall.py` on every recall — 10 dedicated security tests, all pass |
| Deletion correctness | `EpisodicMemory` file + `DocStore` + `KnowledgeGraph` covered by `account_delete.py`; `SemanticMemory`'s diskcache was **entirely missing** from the cascade (a real, confirmed gap — see [CURRENT_MEMORY_ARCHITECTURE.md](CURRENT_MEMORY_ARCHITECTURE.md)) | Fixed this phase (`SemanticMemory.delete_session_facts()`) + new Memory Continuum stores added to the same cascade |
| Latency (recall path) | One ChromaDB/keyword query per turn, unconditionally | Significance filter adds a regex check (sub-millisecond) before ANY durable write; recall adds one `MemoryQuery` scan bounded by scope, gated by `IntentPlan.requires_memory` so it doesn't run on every request at all |

No claim of a measured latency number for the legacy path is made here
— it was never instrumented to compare against, and adding that
instrumentation retroactively to unify the comparison was judged out of
scope for this phase (spec §55: "do not claim improvement without
measured evidence" cuts both ways — an unmeasured legacy baseline is
reported as unmeasured, not backfilled with an estimate).
