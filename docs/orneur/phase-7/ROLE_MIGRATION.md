# Role Migration (Phase 7.1 spec §5-9, §37)

## Migrated to live Society routing

| Function | Role(s) | Live production call? |
|---|---|---|
| `orca.truth.claims.extract_atomic_claims` (via `verify_answer`) | `CLAIM_EXTRACTOR` | **Yes** -- `CognitiveKernel` never overrides `tier`. |
| `orca.truth.verification.verify_claim` (via `verify_answer`) | `VERIFIER` | **Yes**. |
| `orca.truth.contradiction.detect_contradictions` (via `verify_answer`) | `VERIFIER` | **Yes** (same tier resolution as claim verification -- one judge role, matching the existing single-`tier`-for-all-three call pattern). |
| `orca.truth.corrective.reform_query` (via `assess_evidence`'s corrective loop) | `QUERY_REWRITER` | **Yes**, when a corrective round actually runs. |
| `orca.memory.candidates.extract_candidates_via_gateway` | `MEMORY_SELECTOR` | No -- zero production callers exist (verified). Migrated for correctness, disclosed as unwired. |
| `orca.deliberation.court.CognitiveCourt` Constructor/Falsifier | `CONSTRUCTOR` / `FALSIFIER` | **Yes** (since Phase 7). |

## Not migrated (disclosed, with reasons)

- **`TOOL_REASONER` (AgentLoop)**: `AgentLoop` selects one `Brain` object per session/request via the existing tier-resolution path, reused across every tool-reasoning turn within that session -- not a per-call role resolution point. Wiring Society in would mean restructuring `AgentLoop`'s Brain lifecycle, which spec §8 explicitly forbids ("without redesigning Agent Runtime"). `TOOL_REASONER`'s `RoleRequirement` is fully declared and tested (`orca/society/role_requirements.py`) for when a future phase does this properly.
- **`OrcaUltra`'s internal calls**: identical reasoning -- one `Brain` per pipeline run, and spec §9 explicitly forbids redesigning Ultra's workflow.
- **`SUMMARIZER`, `RETRIEVAL_PLANNER`, `CODER`, `CAUSAL_REASONER`, `COUNTERFACTUAL_REASONER`, `ARBITRATION_SUPPORT`, `INTENT_COMPILER`, `FAST_RESPONDER`**: declared roles with tested `RoleRequirement`s and exercised in the deterministic evaluation harness, but no live production call site currently exists in the codebase for these specific cognitive functions as distinct model calls (e.g. intent compilation and complexity assessment are today rule-based/deterministic in `orca/cognitive/`, not model calls at all -- correctly NOT migrated per spec §4).

## Falsifier taxonomy preserved (spec §10, §33)

`orca.deliberation.twin._validate_objection_kind()` (Phase 7 fix, unchanged this phase) still degrades any objection kind outside the declared 7-item taxonomy to `UNVALIDATED` -- schema validity is not confused with reasoning quality. Genesis-legacy's `FALSIFIER` capability remains `UNMEASURED` in its profile (`orca/society/profiles.py`), not upgraded to MEASURED/strong merely because the schema-validation mechanism now works structurally (spec §33's explicit instruction).

## Role output schemas (spec §10)

Every migrated role call already had (Phase 6) or now has (Phase 7.1) typed input/output: `extract_atomic_claims` returns `list[AtomicClaim]`, `verify_claim` returns a `ClaimSupport` with a bounded `ClaimSupportState` enum, `detect_contradictions` returns bounded `Contradiction`/`ContradictionRelationship` enums, `reform_query` returns a typed dict or `None`. No newly-migrated role introduces a new unvalidated taxonomy.
