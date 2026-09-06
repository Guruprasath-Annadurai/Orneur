# Memory Continuum Evaluation V2 (Phase 5.1, spec §35-36)

Extends [EVALUATION.md](EVALUATION.md) (Phase 5's original 14-scenario
harness). **The original 14 scenarios are kept verbatim, never
replaced** — `orca/memory/eval_harness.py::run_all()` reports them
separately from the new closure cases (spec §36), so the original score
is never obscured or inflated by new passing cases.

## Original Phase 5 corpus — unchanged

**13 / 14 passed (0.929)** — identical to Phase 5's own reported result.
The one failure (`same_fact_phrased_differently_is_deduplicated`) is
kept as-is per spec §17's explicit instruction not to "fix" it with a
hard-coded phrase; no generic improvement was attempted this phase
(scope was memory authority/qualification, not the duplicate detector),
so there is no before/after to report for it.

## Phase 5.1 closure cases — new, reported separately

**9 / 9 passed (1.000)** — real run, `orca/memory/eval_harness.py::
CLOSURE_SCENARIOS`:

| Scenario | Result |
|---|---|
| working_memory_boundedness | PASS |
| working_memory_scope_isolation | PASS |
| legacy_unverified_fact_promotion | PASS |
| legacy_read_firewall | PASS |
| dual_write_idempotency | PASS |
| compatibility_deletion | PASS |
| fast_path_no_memory_request | PASS |
| memory_reflex_firewall_path | PASS |
| human_authoritative_vs_external_claim | PASS |

Two of these (`legacy_unverified_fact_promotion`,
`memory_reflex_firewall_path`) failed on first implementation with a
plain `NameError` (missing module-level imports in the eval harness
itself, not a defect in the code under test) — caught and fixed before
being reported as passing, not silently left broken or excluded from
the corpus.

## Why no headline number was "inflated"

9 new passing cases were NOT added to the original 14 to produce a
misleadingly higher combined score (e.g. "22/23, 96%") — the two corpora
are structurally separate return values
(`original_phase_5_corpus`/`phase_5_1_closure_cases`) in the harness's
own output, and this document reports both without merging them, per
spec §36's explicit instruction.
