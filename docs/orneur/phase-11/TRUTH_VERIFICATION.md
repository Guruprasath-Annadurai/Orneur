# Phase 11.1 — Real Truth Fabric Verification

`orca/simulation/truth_verification.py` + `orca/simulation/truth_impact.py`.

## From conceptual to real

Phase 11's report described Truth Fabric integration as "conceptual/
documented only." Phase 11.1 converts this into a genuine runtime hook,
reusing `orca.truth.truth_fabric.TruthFabric.assess_evidence()` DIRECTLY
— the exact pattern `orca.agent.truth_hook.truth_check_sufficient()`
already established in Phase 8.1. No second, parallel truth/verification
stack was built.

## Deterministic trigger policy (never "verify everything")

`requires_truth_verification()` fires only when an
`AssumptionVerificationContext` flags the assumption as
freshness-sensitive, externally factual, high-impact, audit-grade,
contradicted, or stale/unknown. An assumption with none of these flags
is returned completely unchanged by `verify_assumption()` — zero Truth
Fabric calls, zero budget consumed.

## Existing Truth semantics only (spec §21)

`map_evidence_state_to_verification()`:

| `EvidenceState` | Assumption `verification_state` |
|---|---|
| `SUFFICIENT` | `VERIFIED` |
| `CONFLICTED` | `CONTESTED` |
| `STALE` | `STALE` |
| `INSUFFICIENT` (or anything else) | `UNVERIFIED` |

No invented parallel vocabulary.

## Real budget accounting (spec §23)

`verify_assumption()` forwards the caller's real `budget`
(`CognitiveBudget`) into `TruthFabric.assess_evidence()` — the exact
same object every other Truth Fabric caller uses. Simulation gets no
separate free allowance; if no `budget` is passed, none is consumed or
fabricated either (Truth Fabric's own budget-optional call path).

## Verdict impact — downgrade-only (spec §22, §45)

`orca.simulation.truth_impact.apply_truth_impact_to_verdict()`:

- Only applies when `is_high_risk=True`.
- `CONTESTED` (real conflicting evidence) → `REVISE`.
- `UNVERIFIED` (real insufficient evidence) → `INCONCLUSIVE`.
- `BLOCK` is left alone (already the worst outcome).
- **Never upgrades** a verdict — a `VERIFIED` assumption cannot turn a
  `BLOCK` into a `PASS`; verified directly.

## Fake verification has zero effect (spec §45)

`verify_assumption()` ALWAYS constructs a brand-new `Assumption` with a
FRESH `verification_state` computed from the real `TruthResult` — it
never reads or trusts the INPUT assumption's existing
`verification_state`. A model/tool that fabricates an `Assumption`
already marked `"VERIFIED"` (having never gone through Truth Fabric) is
silently overwritten the instant real verification runs. Verified
directly with a deliberately absurd pre-"VERIFIED" claim.

## Two real, non-fabricated paths verified end-to-end

1. **No evidence source** (`doc_store=None`): a high-impact assumption
   correctly resolves `UNVERIFIED` — a real filesystem-write `PASS`
   simulation is genuinely downgraded to `INCONCLUSIVE`.
2. **Real DocStore evidence**: an assumption whose claim is genuinely
   supported by a populated `orca.docs.store.DocStore` (keyword-fallback
   retrieval, no live model required for this path) correctly resolves
   `VERIFIED`.
