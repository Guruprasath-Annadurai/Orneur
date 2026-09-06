# Counterfactual Engine (Phase 6)

`orca/deliberation/counterfactual.py`. Bounded, and never presented as
an observed fact (spec §25).

## Contract

```python
build_counterfactual(baseline_state, changed_variable, predicted_consequence, held_constant=None, uncertainty_note=None) -> Counterfactual
```

Every `Counterfactual` carries a non-empty `uncertainty_note` — a
default is supplied
("This is a counterfactual projection, not an observed outcome...")
when the caller doesn't provide one, so there is no code path that
produces a `Counterfactual` without an uncertainty disclosure attached.

## Bounded (spec §30)

`CounterfactualSet` refuses beyond `MAX_COUNTERFACTUALS_PER_REQUEST = 3`
— a request needing more than three distinct "what if" branches to
answer is treated as needing a different reasoning approach, not an
unbounded counterfactual tree.

## What this phase does not build

No Simulation Chamber (spec §62) — this is single-step, structured
counterfactual representation (baseline → one changed variable → one
predicted consequence), not a multi-step world simulation with branching
outcomes. That is explicitly deferred to a later phase, after the Agent
Runtime/Godmode foundation spec §62 names as its prerequisite.
