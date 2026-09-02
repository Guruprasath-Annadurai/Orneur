# Causal Reasoning (Phase 6)

`orca/deliberation/causal.py`. A causal claim requires **stronger**
support than a correlation claim (spec §24) — and that upgrade is never
inferred from prose alone.

## Classification rule

```python
assess_causal_relation(cause, effect, evidence_ids, *,
    temporal_precedence=False, mechanism_explained=False, controlled_comparison=False, prevents=False)
```

| Signals present | Relationship |
|---|---|
| No evidence at all | `UNKNOWN` |
| `controlled_comparison`, OR (`temporal_precedence` AND `mechanism_explained`) | `CAUSES` (or `PREVENTS` if `prevents=True`) |
| Exactly one of `temporal_precedence`/`mechanism_explained` | `CONTRIBUTES_TO` |
| Evidence exists, none of the above | `CORRELATES_WITH` |

The three boolean signals are **structured inputs the caller must
explicitly assert** (e.g. from a Constructor claim that stated a
mechanism, or evidence with genuine before/after ordering) — this
module never scans claim text itself and never upgrades a bare
association to causation on its own initiative. Proven directly:
`tests/test_deliberation_contracts_hypothesis.py::
test_evidence_alone_without_mechanism_is_correlation_only`.

## Bounded (spec §23)

`CausalGraph` refuses beyond `MAX_RELATIONS_PER_GRAPH = 20` — matching
the same "bounded everything" discipline as Truth Fabric's retrieval
planner and Memory Continuum's reflex registry.

## `correlation_only()`

Returns exactly the relations still resting on association evidence —
the set spec §24 wants explicitly distinguishable from real causal
claims, available as a single method call rather than something a
caller has to re-derive.
