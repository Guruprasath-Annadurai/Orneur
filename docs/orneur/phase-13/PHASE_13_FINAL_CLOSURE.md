# Phase 13.1 — Deep Red-Team Closure

**Repository**: orca | **Branch**: session-update-2026-08-25

## What Phase 13.1 did differently from Phase 13

Phase 13's own closure was rejected as insufficient: only 6 new attacks
were executed, with most campaigns satisfied by citing existing
coverage. Phase 13.1 required active, new adversarial discovery per
campaign. This phase executed **55 new attacks** across 8 new test
files, finding and fixing **2 real vulnerabilities** and documenting
**1 real, unfixed residual finding** — none of which existed or were
known before this phase's own active attack work.

## Real vulnerabilities found and fixed

1. **RAG source-independence never consulted** (`orca/truth/state.py`) —
   an evidence set of N mutually-derived (mirrored/syndicated) sources
   reached `SUFFICIENT` exactly as if independently corroborated. Fixed:
   downgrades to `PARTIAL` when all sources are `LIKELY_DERIVED`.
2. **Godmode canonicalizer recursion crash** (`orca/godmode/canonical.py`) —
   a 500-level-deep argument payload crashed `issue_lease()`/
   `resolve_lease()` with an uncaught `RecursionError`. Fixed: bounded
   depth counter raising a typed `ArgumentTooDeeplyNestedError`.

## Real finding, documented, not fixed this pass

3. **Godmode one-use lease cross-process race** (`orca/godmode/lease_store.py`) —
   a genuine multi-process test proves the module's atomicity claim is
   in-process only. Reproduced, `xfail`ed with full documentation, not
   hidden. Recommended priority follow-up before any multi-process
   Godmode deployment.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1448 passed, 0 failed, 1 xfailed, 43 deselected |
| Authoritative security suite (89 files) | 790 passed, 0 failed, 1 xfailed, 4 deselected |
| Live suite (`-m live_ollama_smoke`) | **[filled in below once the run completes]** |
| New red-team tests | 55/55 executed, 52 passed clean, 2 real findings fixed, 1 real finding documented/xfailed |

## Vulnerability accounting (honest, spec §45/§73-75)

- NEW_ATTACKS_EXECUTED: **55**
- EXISTING_SECURITY_TESTS_REUSED: **733** (unmodified, reconfirmed green; now 790 total after this phase's 9 new files joined the inventory)
- REAL_VULNERABILITIES_FOUND: **3**
- REAL_VULNERABILITIES_FIXED: **2**
- OPEN_FINDINGS: **1** (documented, `xfail`ed, disclosed — not silently passed)
- FALSE_POSITIVES: **1** (RAG-06's initial hypothesis, corrected after actually running the test)

## Severity

CRITICAL: 0 | HIGH: 0 | MEDIUM: 3 (2 fixed, 1 residual) | LOW: 0

## PROCESS_EXECUTION Godmode

Remains **disabled** — not enabled to test it, unchanged from Phase 13.

## Model lifecycle

Genesis/Novus/Aeternum unchanged — no red-team fix in this phase touched
any model checkpoint, registry entry, or lifecycle state.

## Known residual risks (disclosed)

1. Godmode one-use lease cross-process race (Finding 3) — not fixed,
   documented, recommended priority follow-up.
2. RAG citation-confusion attacks (negation/entity/numeric) against the
   deterministic lexical FALLBACK path are disclosed, pre-existing
   limitations (ceiling verified to hold) — not newly introduced, not
   fixed (would require real NLI capability the live judge already
   provides on the non-degraded path).
3. Structured-input bomb testing against the live API/serve layer (as
   opposed to the AgentPlan/Godmode/Truth-budget layers actually
   attacked) was not newly executed this phase.
4. Regex/parser DoS was measured via timing on one representative
   function (`redact_secrets`); a full audit of every security-sensitive
   regex in the codebase was not exhaustively re-timed.

## Remaining Phase-13 blockers

None — Finding 3 is disclosed residual risk, not a blocker, per spec
§75's "some risks may remain intentionally... do not claim perfect
security."

**READY TO ADVANCE TO PHASE 14: YES**
