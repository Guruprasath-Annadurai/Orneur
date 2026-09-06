# Hypothesis Space (Phase 6)

`orca/deliberation/contracts.py::Hypothesis`/`HypothesisSet` +
`orca/deliberation/hypothesis.py`'s explicit lifecycle transitions.

## Never silently deleted (spec §7)

A `FALSIFIED` hypothesis stays in the `HypothesisSet` forever — only its
`status` field changes. `falsify()` is **terminal**:
`_recompute_status()` returns immediately for an already-`FALSIFIED`
hypothesis, even if later evidence would otherwise support it — a
genuinely new claim needs a **new** `Hypothesis` object, preserving the
original falsification as a permanent audit record. Proven directly:
`tests/test_deliberation_contracts_hypothesis.py::
test_falsified_status_is_terminal`.

## Status transitions

| Transition | Trigger |
|---|---|
| `ACTIVE` → `SUPPORTED` | `record_supporting_evidence()`, no contradicting evidence |
| `ACTIVE`/`SUPPORTED` → `WEAKENED` | `record_contradicting_evidence()` outweighs supporting evidence |
| any (except terminal `FALSIFIED`) → `FALSIFIED` | `falsify()` — an explicit, decisive call (the Falsifier judged it genuinely broken, not merely weakened) |
| `ACTIVE`/`WEAKENED` → `UNRESOLVED` | `mark_unresolved()` — ran out of budget/rounds to further distinguish it |

## Bounded, not combinatorial (spec §8)

`HypothesisSet.add()` refuses beyond `max_hypotheses` (default 4,
matching `ReasoningPlan.max_hypotheses`) rather than growing unbounded.
`all_resolved()` is the set-level stop condition (spec §31): true once
no hypothesis is still `ACTIVE`/`WEAKENED`.

## Evidence-seeking, not more prose (spec §9)

`distinguishing_evidence_need(hypothesis_a, hypothesis_b)` produces a
structured `EvidenceNeed` — a question Truth Fabric or a tool can act
on, referencing both hypothesis ids — rather than asking a model to
"explain more."

## Assumption tracking (spec §10)

`Assumption` carries `verification_state`
(`EXPLICITLY_GIVEN`/`SUPPORTED`/`UNVERIFIED`/`CONTESTED`/`DISPROVEN`),
`source` (who asserted it), and `required_for` (which
hypotheses/arguments depend on it). An assumption never silently
disappears inside a prompt — the Falsifier's own output
(`TwinResult.unsupported_assumption_ids`) is a first-class, structured
field, not buried in free text.
