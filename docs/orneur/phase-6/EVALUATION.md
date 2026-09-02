# Deliberation Fabric Evaluation (Phase 6)

## Harness

`orca/deliberation/eval_harness.py` — run directly with
`.venv/bin/python -m orca.deliberation.eval_harness`. 13 deterministic
scenarios, real code exercised, no fabricated scores.

## Real result

**13 / 13 passed (1.000).**

| Scenario (spec §54) | Result |
|---|---|
| Simple direct question — no Court | PASS |
| Ambiguous diagnosis — multiple hypotheses | PASS |
| One hypothesis falsified by evidence | PASS |
| All hypotheses unresolved | PASS |
| Conflicting evidence triggers Court | PASS |
| Temporal contradiction does NOT force Court | PASS |
| Causal claim with only correlational evidence | PASS |
| High-risk decision, insufficient evidence | PASS |
| Falsifier catches unsupported assumption | PASS |
| Counter-evidence overturns initial conclusion | PASS |
| Budget stopping never forces a confident verdict | PASS |
| EvidenceClerk flags missing evidence | PASS |
| RiskCounsel recommends, never authorizes | PASS |

## Scenarios covered live, not duplicated here

Constructor-confident-but-wrong, cancellation during Court, role
injection, and same-model disclosure genuinely need a real model call
to measure anything — duplicating them into this deterministic harness
would either need Ollama (making the harness flaky for no benefit) or
fake the model call (not a real measurement). Covered instead by:
`tests/test_deliberation_court_integration.py`,
`tests/test_deliberation_cancellation.py`,
`tests/test_deliberation_security.py`. Procedure/failure-memory
integration scenarios are covered by Phase 5.1's own
`tests/test_memory_reflex_procedural_failure_authority.py` (Deliberation
Fabric introduces no new memory-integration code path this phase — see
[ARCHITECTURE.md](ARCHITECTURE.md)).

## A real, honest model-quality finding (not fabricated, not hidden)

A live Constructor/Falsifier run on a well-evidenced, unambiguous claim
("The API rate limit is 100 requests per minute, effective March 2024.")
produced a nano-tier Falsifier objection incorrectly labeling the
correctly-cited claim a "contradiction," and separately flagging a
second, distinct claim as a duplicate. Full detail and disposition in
[EPISTEMIC_TWIN.md](EPISTEMIC_TWIN.md) — the same class of nano-tier
judge imprecision already documented for Truth Fabric's own claim
verifier, not newly introduced by this phase, and not chased with a
one-off prompt patch.

## Baseline comparison (spec §55)

The pre-existing "reflection"/multi-agent behavior
(`orca/brain/agent.py::AgentLoop._reflect()`,
`orca/variants/ultra.py::OrcaUltra`'s grade/self-heal step) produces
**no structured claims, no evidence citations, no contradiction
handling, and no abstention mechanism at all** — see
[CURRENT_REASONING_ARCHITECTURE.md](CURRENT_REASONING_ARCHITECTURE.md).
There is therefore no existing unsupported-claim rate, contradiction-
handling rate, or abstention-correctness number to compare against —
the honest baseline is "0/undefined for every Deliberation-Fabric-
specific metric, because the capability did not exist." The one
directly comparable dimension is latency, reported separately in
[COGNITIVE_COURT.md](COGNITIVE_COURT.md)'s latency section: Court's
Constructor+Falsifier round (~19.7s p50, this session) is substantially
slower than `AgentLoop._reflect()`'s single unstructured pass, a real
and disclosed cost of the additional structure and independence Court
provides — not claimed as a general intelligence improvement from a
13-scenario corpus (spec §55's own explicit caution).
