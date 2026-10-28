# FOUNDATION_01_FINAL_ENGINEERING_REPORT

**Milestone:** FOUNDATION LANDMARK-01 — Secure and Reliable ORNEUR Runtime  
**Owner:** Cursor (engineering). **Independent qualification:** Antigravity (not claimed).  
**Branch:** `cursor/foundation-landmark-01-backend-closure-1cdf`  
**Draft PR:** https://github.com/Guruprasath-Annadurai/Orneur/pull/132  
**Functional CI tip (product + CI recovery):** `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8`  
**Authoritative audit target:** GitHub PR #132 HEAD after evidence-freeze commit (see `FOUNDATION_01_TIP_SHA.txt`)  
**Date:** 28 October 2026 (Asia/Calcutta)

## Engineering verdict

**`VERIFIED_ENGINEERING`** at functional tip `2b6b6de…` — mandatory exact-head CI green.  
**Not** independently qualified. **Not** production-ready.

Full corrective narrative: `FOUNDATION_01_CORRECTIVE_CLOSURE_REPORT.md`.

## Selected architecture

**SQLite fencing epochs (PR #130).** Redis advisory. JSONL derived. Competing Redis-callback SoT (#131) rejected. See `AUTHORITATIVE_STORAGE_DECISION.md`.

## Completed implementation

1. Consolidated PR #126 (multi-turn, colon-safe Ollama IDs, temporary chat, message versions) onto #130 fencing.
2. `get_current_user_optional` fail-closed — present invalid credentials → **401**.
3. `orca/serve/admission.py` — `admit_serving` for chat / stream / ultra / vision / cognitive.
4. Atomic reservation + consume / release / replay (no check-then-increment race on those routes).
5. Stream pre-dispatch refusals as HTTP JSON (401/402/400/404/429) before SSE.
6. StreamRedactor DLP retained; ownership → non-leaking 404; temp-chat privacy tests.
7. CI recovery: G006 revoked-key 401; S2 stream HTTP JSON expectations; contract update.

## Corrected CI failures (this closeout)

| Failed SHA | Runs | Cause | Fix SHA |
|---|---|---|---|
| `1ffb7b8562de0dd819833c93471599692946f666` | `40719785862`, `40719797352` | Obsolete G006/S2 expectations vs stronger auth + stream admission | `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8` |

## Exact-head CI (functional tip `2b6b6de…`)

| Workflow | Run ID | Result |
|---|---|---|
| Test Suite (push) | [40733516543](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733516543) | **9/9 SUCCESS** |
| Test Suite (PR) | [40733526194](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733526194) | **9/9 SUCCESS** |
| Eval Static Checks | [40733526200](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40733526200) | **SUCCESS** |
| Deterministic Unit Tests | (within PR Test Suite) | **8941 passed, 372 skipped, 75 deselected, 7 xfailed** |

Document-bearing commits after `2b6b6de` create a new HEAD — verify that HEAD’s CI separately before Antigravity starts.

## Local foundation package (same functional tip)

```
145 passed, 2 skipped, 2 xfailed
```

- Skips: real Redis required (`test_p0_transcript_integrity`).
- XFails: G-020 agent tool confinement (known open, not waived as pass).

Commands: see Antigravity handoff / corrective report.

## Real-service evidence

| Capability | Status |
|---|---|
| SQLite + deterministic unit | Yes |
| Real Redis two-worker soak | **Unverified** (no Redis in this environment) |
| Live Ollama `llama3.2:1b` | **Unverified** (Ollama not available) |
| Browser integration | Claude owns FE; Cursor did not change FE branch |

## Known limitations

See `FOUNDATION_01_BLOCKER_REGISTER.md` (B08, B09, B10, B11, B12 persistence UX, G-020).

## Production readiness

**Not production-ready.** Draft PR only — no protected merge, no deploy, no paid infra, no model training.
