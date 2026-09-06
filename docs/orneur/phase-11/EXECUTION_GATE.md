# Phase 11 — Execution Gate

`orca/simulation/execution_gate.py::evaluate_execution_gate()`.

## The one thing this function answers

"Given what simulation found, is it even sane to ASK for real
authorization" — never "is this action authorized." Capability/Policy/
lease checks (Phase 8/9/10, unmodified) always still run after
`ALLOW_TO_PROCEED_TO_AUTHORIZATION`, independently.

## Decision table

| Requirement | Result | Decision |
|---|---|---|
| `REQUIRED` | `None` (simulation never ran) | `BLOCK` |
| any | `result.verdict == BLOCK` | `BLOCK` |
| any | `result.verdict == REVISE` | `REVISE_PLAN` |
| any | `result.verdict == INCONCLUSIVE` | `REQUIRE_REVIEW` (fail-closed default, spec §45) |
| any | `result.verdict in (PASS, PASS_WITH_WARNINGS)` | `ALLOW_TO_PROCEED_TO_AUTHORIZATION` |

`INCONCLUSIVE` is never silently treated as "no news is good news" —
spec §45's explicit instruction. A `REQUIRED` simulation that never
produced a result at all is `BLOCK`, not skipped.

## Structural proof simulation never authorizes

`orca/simulation/chamber.py` never imports or calls
`orca.agent.capability.check_capabilities()`,
`orca.agent.policy.evaluate_policy()`, or anything from
`orca.deliberation.court` — verified by source inspection in
`orca/simulation/eval_harness.py`'s scenarios 13-14. A `PASS` verdict
and `ALLOW_TO_PROCEED_TO_AUTHORIZATION` decision are both purely
advisory inputs to the SAME unmodified downstream authorization chain
every non-simulated action already goes through.
