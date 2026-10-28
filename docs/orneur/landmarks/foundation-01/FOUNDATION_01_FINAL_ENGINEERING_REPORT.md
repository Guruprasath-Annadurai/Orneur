# FOUNDATION_01_FINAL_ENGINEERING_REPORT

**Milestone:** FOUNDATION LANDMARK-01 — Secure and Reliable ORNEUR Runtime  
**Owner:** Cursor (engineering). **Independent qualification:** Antigravity (not claimed here).  
**Branch:** `cursor/foundation-landmark-01-backend-closure-1cdf`  
**Exact SHA:** `7c8f7b0e3a2724e77f3be971f7b36cc17ebe530f`  
**Date:** 28 October 2026 (Asia/Calcutta)

## Starting baseline

Refreshed open PRs at assignment:

| PR | Tip SHA | CI (refreshed) |
|---|---|---|
| #125 | `9298b15…` | 9/9 SUCCESS |
| #126 | `7ea44ae…` | 9/9 SUCCESS |
| #127 | `2222508…` | 9/9 SUCCESS |
| #128 | `a6def68…` | 9/9 SUCCESS |
| #129 | `485ca95…` | 9/9 SUCCESS; merge CONFLICTING |
| #130 | `497073d…` | 8 SUCCESS + Deterministic pending at refresh |
| #131 | `040d694…` | 9/9 SUCCESS |

`main` remains far behind (`20a8546`, PR #51 merge) — work continues on isolated Cursor stacks, not protected merges.

## Selected architecture

**SQLite fencing epochs (PR #130).** Redis is advisory. JSONL is derived. See `AUTHORITATIVE_STORAGE_DECISION.md`.

## Completed implementation (this tip)

1. Consolidated PR #126 (multi-turn context, Ollama colon-safe IDs, temporary chat, message versions) onto #130 fencing base.
2. Fixed `get_current_user_optional` — invalid credentials fail closed (401).
3. Added `orca/serve/admission.py` — unified admit_serving for chat/stream/ultra/vision.
4. Replaced unsafe check-then-increment on chatbot routes with atomic reservation + consume/release.
5. SQLite turn meta carries `user_message_id` for edit overlays; `find_message` reads SQLite.
6. Temporary-chat lock unlink after flock release.
7. Landmark docs under `docs/orneur/landmarks/foundation-01/`.

## Defect corrections (actual)

- Invalid bearer → anonymous inference (middleware).
- Dual transcript SoT (#130 vs #131) — decision + single engine on branch.
- Chat/stream quota race — atomic admission.
- Missing multi-turn context on fencing branch — merge #126.
- Stream DLP preserved through merge (StreamRedactor retained).

## Test summary (this environment)

```
53 passed, 4 skipped  (targeted foundation package)
```

Commands: see Antigravity handoff.

## CI results

Exact-head CI for this tip: started after push; record conclusion in handoff updates when green. Do not treat ancestor PR CI as this tip’s CI.

## Real-service evidence

- SQLite + Python unit: yes  
- Real Redis two-worker soak: not completed here  
- Real Ollama `llama3.2:1b`: **not available** — evidence gap recorded  

## Known limitations / remaining blockers

See `FOUNDATION_01_BLOCKER_REGISTER.md` (B07 cognitive route, B08/B09 live distributed/Ollama, B11 Antigravity).

## Production readiness

**Not production-ready.** Not independently qualified. Draft PR only — no merge, no deploy, no paid infra.
